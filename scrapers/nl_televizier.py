"""
Scraper Pays-Bas — Televizier.nl (remplace Broadcast Magazine gelé au 30/03)

Source : https://www.televizier.nl/kijkcijfers
Chaque matin (~7h50-9h15 NL), Televizier publie un article "De TV van gisteren"
qui commente 3 programmes du prime time de la veille avec leurs téléspectateurs.

Structure :
- Page index avec liste de liens vers les articles
- Chaque article contient :
  - "Kijkcijfers [jour] [DD] [mois] [année]" en titre
  - 3 sections ## [Programme] avec la chaîne et les téléspectateurs dans le texte

Limites connues :
- Pas de PDM (part de marché) → on met 0.0
- Seulement 3 programmes par jour (pas un top 5 complet) → status "partial"
- L'approche est éditoriale (sélection des programmes "qui font parler")
  plutôt qu'un top 5 strict par viewers

IMPORTANT : usage respectueux — 1 requête index + 1 requête article par jour,
rate-limited, User-Agent identifiant un projet de veille personnelle.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    AudienceEntry, CountryReport,
    color_for, save_report,
)
from translations import translate


COUNTRY_CODE = "NL"
COUNTRY_NAME = "Pays-Bas"
FLAG = "🇳🇱"
SOURCE_NAME = "Televizier · De TV van gisteren"
SOURCE_URL = "https://www.televizier.nl/kijkcijfers"

# User-Agent identifiant clairement un projet de veille personnelle
# (meilleure pratique : transparent sur l'usage)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.5",
}

MONTHS_NL = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

# Chaînes reconnues (tout le reste = ignoré)
CHANNELS = {
    "NPO 1": "NPO 1", "NPO1": "NPO 1",
    "NPO 2": "NPO 2", "NPO2": "NPO 2",
    "NPO 3": "NPO 3", "NPO3": "NPO 3",
    "RTL 4": "RTL 4", "RTL4": "RTL 4",
    "RTL 5": "RTL 5", "RTL5": "RTL 5",
    "SBS 6": "SBS 6", "SBS6": "SBS 6",
    "SBS 9": "SBS 9", "SBS9": "SBS 9",
    "Net 5": "Net 5", "Net5": "Net 5",
    "Veronica": "Veronica",
    "NPO Start": "NPO Start",
}

log = logging.getLogger("nl_televizier")


def find_latest_article(soup: BeautifulSoup) -> Optional[tuple[str, date]]:
    """
    Sur la page index, trouve le premier article "De TV van gisteren".
    Retourne (url, date effective de diffusion) ou None.

    La date est extraite du texte "Kijkcijfers [jour] DD [mois] [YYYY]"
    qui apparaît juste avant chaque titre d'article.
    """
    # Chercher le premier lien vers /kijkcijfers/de-tv-van-gisteren-*
    # ou /kijkcijfers/kijkcijfers-* (certains articles n'ont pas le préfixe)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/kijkcijfers/" not in href:
            continue
        # Filtrer les pages d'index (/kijkcijfers, /kijkcijfers/1, etc.)
        if re.search(r"/kijkcijfers/?$", href) or re.search(r"/kijkcijfers/\d+/?$", href):
            continue
        # On a un article individuel
        full_url = href if href.startswith("http") else f"https://www.televizier.nl{href}"
        return (full_url, None)  # la date sera extraite dans l'article lui-même
    return None


def extract_date_from_article(soup: BeautifulSoup) -> Optional[date]:
    """
    Dans un article, cherche le texte "Kijkcijfers [jour] DD [mois] YYYY"
    qui indique la date de DIFFUSION (pas de publication).
    """
    full_text = soup.get_text(" ", strip=True)
    m = re.search(
        r"Kijkcijfers\s+(?:maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)?\s*"
        r"(\d{1,2})\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)"
        r"\s+(\d{4})",
        full_text,
        re.IGNORECASE,
    )
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS_NL.get(m.group(2).lower())
    year = int(m.group(3))
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_channel_in_text(text: str) -> Optional[str]:
    """
    Cherche un nom de chaîne dans un fragment de texte.
    Retourne le nom normalisé, ou None.
    """
    # On teste les noms plus longs en premier pour éviter que "NPO 1" soit
    # matché comme "NPO" dans "NPO 11" (peu probable mais sécurité)
    for needle in sorted(CHANNELS.keys(), key=len, reverse=True):
        # Mot entier, insensible à la casse
        if re.search(rf"\b{re.escape(needle)}\b", text, re.IGNORECASE):
            return CHANNELS[needle]
    return None


def parse_viewers_from_text(text: str) -> Optional[int]:
    """
    Cherche un nombre de téléspectateurs dans un texte.
    Formats gérés :
    - "720.000 kijkers" / "792.000 mensen" / "618.000 kijkers"
    - "bijna 700.000 kijkers"
    - "1,3 miljoen kijkers" / "1.3 million"
    Retourne None si non trouvé.
    """
    # Format "X.XXX.XXX kijkers|mensen"
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)\s+(?:kijkers|mensen|keken)", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(".", ""))
    # Format "X,X miljoen" (rare mais possible)
    m = re.search(r"(\d+[,.]\d+)\s+miljoen", text, re.IGNORECASE)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1_000_000)
    # Format "X miljoen"
    m = re.search(r"(\d+)\s+miljoen", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 1_000_000
    return None


def parse_article(soup: BeautifulSoup) -> list[dict]:
    """
    Parse un article Televizier pour extraire les programmes + viewers + chaîne.

    Stratégie : chaque programme a un titre <h2>, et les 1-2 paragraphes qui suivent
    contiennent le nom de la chaîne + les téléspectateurs. En fallback, on cherche
    la chaîne dans le paragraphe d'intro global de l'article (souvent mentionnée là).
    """
    rows = []

    # Texte d'intro global (avant le premier h2) pour fallback
    intro_text = ""
    for p in soup.find_all("p"):
        # On s'arrête quand on rencontre un h2 (fin de l'intro)
        if p.find_previous(["h2", "h3"]) is not None:
            break
        intro_text += " " + p.get_text(" ", strip=True)
    # Alternative plus large : les 3 premiers paragraphes
    all_paragraphs = soup.find_all("p")[:5]
    if not intro_text.strip():
        intro_text = " ".join(p.get_text(" ", strip=True) for p in all_paragraphs)

    log.debug(f"Intro text : {intro_text[:200]!r}")

    # Trouver tous les <h2> qui sont probablement des noms de programmes
    # Stratégie : on cherche les h2 qui se trouvent DANS le corps de l'article
    # (pas dans les sidebars/footers/navigation)
    headings = soup.find_all(["h2", "h3"])
    for h in headings:
        title = h.get_text(" ", strip=True)
        # Filtrer les titres vides ou trop longs
        if not title or len(title) < 3 or len(title) > 80:
            continue
        # Exclure explicitement les h2 standards du site
        EXCLUDE_EXACT = {
            "televizier.nl", "stem nu hier op de",
            "gouden televizier-ring 2026", "meer over",
            "meer nieuws voor jou", "laatste nieuws",
            "gouden televizier-ring", "de tv van gisteren",
            "pak je kans", "spannend", "spannend!", "chaos",
            "zou het een match zijn?", "pauw & de wit & moggré",
        }
        if title.lower().strip() in EXCLUDE_EXACT:
            continue
        # Exclure les titres qui ressemblent à des teasers d'articles (contiennent ':')
        # mais garder ceux qui ont juste un point (Mr. Frank Visser, Dr. Wheeler, etc.)
        if ":" in title or "?" in title or "!" in title:
            continue
        # Exclure les titres longs qui ressemblent à des phrases
        # (plus de 8 mots = souvent un teaser d'article)
        if len(title.split()) > 8:
            continue
        # Exclure le titre de l'article principal
        if title.lower().startswith("de tv van gisteren"):
            continue
        if title.lower().startswith("kijkcijfers"):
            continue

        # Collecter les 2-3 paragraphes suivants qui contiennent l'info
        collected_text = ""
        current = h
        for _ in range(6):
            current = current.find_next(["p", "h2", "h3"])
            if current is None:
                break
            # Si on retombe sur un autre heading, on s'arrête
            if current.name in ("h2", "h3"):
                break
            collected_text += " " + current.get_text(" ", strip=True)

        if not collected_text:
            continue

        channel = find_channel_in_text(collected_text)
        # Fallback : si pas de chaîne trouvée dans les paragraphes locaux,
        # chercher dans l'intro globale de l'article (souvent mentionnée là-bas)
        if channel is None:
            channel = find_channel_in_text(intro_text)

        viewers = parse_viewers_from_text(collected_text)

        if channel is None or viewers is None:
            log.debug(f"Skip '{title}' : chaîne={channel}, viewers={viewers}")
            continue

        # Nettoyer le titre du programme
        program = title.strip()

        rows.append({
            "channel": channel,
            "program": program,
            "viewers": viewers,
            "share": 0.0,  # PDM non fournie par Televizier
        })

    log.info(f"Parsé {len(rows)} programmes depuis l'article")
    return rows


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} (Televizier) ===")

    try:
        # 1. Fetcher la page index
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        index_soup = BeautifulSoup(r.text, "html.parser")

        result = find_latest_article(index_soup)
        if result is None:
            raise RuntimeError("Aucun article récent trouvé sur la page index")
        article_url, _ = result
        log.info(f"Article le plus récent : {article_url}")

        # 2. Fetcher l'article
        r2 = requests.get(article_url, headers=HEADERS, timeout=30)
        r2.raise_for_status()
        article_soup = BeautifulSoup(r2.text, "html.parser")

        # 3. Extraire la date de diffusion
        effective_date = extract_date_from_article(article_soup)
        if effective_date is None:
            log.warning("Date non extraite de l'article, fallback sur date d'hier")
            effective_date = (target_date or date.today())
        log.info(f"Date effective des données : {effective_date}")

        # 4. Parser les programmes
        rows = parse_article(article_soup)
        if not rows:
            raise RuntimeError("Aucun programme extrait de l'article")

        # 5. Tri par viewers et dédup par chaîne (on garde le top par chaîne)
        top_by_channel: dict[str, dict] = {}
        for row in rows:
            ch = row["channel"]
            if ch not in top_by_channel or row["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = row

        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]
        log.info(f"Top retenu : {[(r['channel'], r['program'], r['viewers']) for r in ranked]}")

        entries = [
            AudienceEntry(
                rank=i + 1,
                channel=r["channel"],
                channel_color=color_for(r["channel"]),
                program=r["program"],
                program_fr=translate(r["program"]),
                viewers=r["viewers"],
                share=r["share"],
                source_url=article_url,
            )
            for i, r in enumerate(ranked)
        ]

        # Status "partial" car Televizier ne donne que 3-4 programmes par jour
        status = "ok" if len(entries) >= 5 else "partial"

        return CountryReport(
            country_code=COUNTRY_CODE, country_name=COUNTRY_NAME, flag=FLAG,
            date=effective_date.isoformat(),
            source_name=SOURCE_NAME, source_url=SOURCE_URL,
            entries=entries,
            scraped_at=datetime.utcnow().isoformat() + "Z",
            status=status,
        )

    except Exception as e:
        log.exception("Scraping failed")
        return CountryReport(
            country_code=COUNTRY_CODE, country_name=COUNTRY_NAME, flag=FLAG,
            date=(target_date or date.today()).isoformat(),
            source_name=SOURCE_NAME, source_url=SOURCE_URL,
            entries=[],
            scraped_at=datetime.utcnow().isoformat() + "Z",
            status="failed", error=str(e),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    report = run()
    save_report(report)
    if report.status == "failed":
        sys.exit(1)
