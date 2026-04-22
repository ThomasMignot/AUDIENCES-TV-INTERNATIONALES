"""
Scraper Allemagne — DWDL.de / Zahlenzentrale

Source : https://www.dwdl.de/zahlenzentrale/
Publie chaque matin (vers 13h heure allemande) les audiences de la veille.
Format : articles avec titre du type "TV-Quoten am [Jour]: ...",
chaque article liste le top prime time avec téléspectateurs et PDM.

Stratégie :
1. On récupère la page d'accueil /zahlenzentrale/ qui liste les derniers articles
2. On identifie l'article daté de la veille (celui qui commence par "TV-Quoten am ...")
3. On parse l'article pour extraire le top 5 prime time
4. On normalise et on sauvegarde

Ce scraper est pensé comme un MODÈLE réutilisable pour les autres pays :
- Séparation claire entre fetch / parse / normalize
- Logs explicites à chaque étape
- Gestion d'erreur qui ne plante pas tout le pipeline si une source tombe
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from common import (
    AudienceEntry, CountryReport,
    color_for, parse_share_percent, parse_viewers_millions,
    save_report, yesterday,
)
from translations import translate


# ─── Config ────────────────────────────────────────────────────────

COUNTRY_CODE = "DE"
COUNTRY_NAME = "Allemagne"
FLAG = "🇩🇪"
SOURCE_NAME = "DWDL.de · Die Quoten"
SOURCE_URL = "https://www.dwdl.de/zahlenzentrale/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
}

# Chaînes allemandes qu'on considère comme "majeures" pour le prime time
MAJOR_CHANNELS = {
    "Das Erste", "ARD", "ZDF", "RTL", "ProSieben", "Sat.1", "SAT.1",
    "VOX", "Kabel Eins", "RTLzwei", "RTL2",
}

log = logging.getLogger("de_dwdl")


# ─── Étape 1 : trouver l'article de la veille ──────────────────────

def find_article_url_for_date(target: date) -> Optional[str]:
    """
    Retourne l'URL de l'article "TV-Quoten am [jour]" daté de `target`.
    None si aucun article trouvé (le scraping peut tourner trop tôt).
    """
    log.info("Fetching liste des articles Zahlenzentrale…")
    r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # DWDL structure ses liens d'articles sous /zahlenzentrale/XXXXX/slug/
    # On cherche ceux dont le slug contient "tvquoten" ou "tv-quoten"
    links = soup.select("a[href*='/zahlenzentrale/']")
    candidates: list[tuple[str, str]] = []
    for a in links:
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not href or not text:
            continue
        if re.search(r"/zahlenzentrale/\d+/", href) and "tv" in href.lower() and "quot" in href.lower():
            full_url = href if href.startswith("http") else f"https://www.dwdl.de{href}"
            candidates.append((full_url, text))

    # Mapping jour de la semaine allemand → index
    WEEKDAY_DE = {
        0: "montag", 1: "dienstag", 2: "mittwoch", 3: "donnerstag",
        4: "freitag", 5: "samstag", 6: "sonntag",
    }
    target_day = WEEKDAY_DE[target.weekday()]

    # On prend le premier article qui mentionne le bon jour de la semaine
    for url, text in candidates:
        combined = (url + " " + text).lower()
        if target_day in combined:
            log.info(f"Article candidat trouvé: {url}")
            return url

    # Fallback : premier article qui contient "tvquoten"
    if candidates:
        log.warning(f"Pas de match strict pour {target_day}, fallback sur le premier")
        return candidates[0][0]

    log.error("Aucun article 'TV-Quoten' trouvé sur la page d'accueil")
    return None


# ─── Étape 2 : parser l'article ────────────────────────────────────

def parse_article(url: str) -> list[AudienceEntry]:
    """
    Lit un article DWDL et extrait les audiences prime time du top 5.
    DWDL écrit en prose : "7,37 Millionen (21,5 Prozent Marktanteil) bei [Programm] auf [Sender]"
    On extrait les patterns récurrents.
    """
    log.info(f"Parsing article {url}…")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Le contenu de l'article est dans .article-body ou un conteneur similaire
    body = soup.select_one("article, .article-body, main, .content")
    if body is None:
        body = soup

    text = body.get_text(" ", strip=True)

    # Pattern : "X,XX Millionen" puis "XX,X Prozent" proches, dans un rayon de ~200 chars
    # On capture aussi le nom du programme (entre guillemets allemands „…" ou "..." )
    # et idéalement le sender mentionné
    PATTERN = re.compile(
        r"(?P<viewers>[\d,.]+\s*(?:Mio|Millionen))[^.]{0,80}?"
        r"(?P<share>[\d,.]+\s*(?:%|Prozent))",
        re.IGNORECASE,
    )
    # Nom de programme entre guillemets typographiques allemands
    PROGRAM_PATTERN = re.compile(r"[„\"»]([^„\"«»]{3,80})[\"«»]")

    entries: list[dict] = []
    for m in PATTERN.finditer(text):
        start = max(0, m.start() - 300)
        end = min(len(text), m.end() + 100)
        context = text[start:end]

        # Trouver le nom du programme le plus proche (avant le match de préférence)
        programs = PROGRAM_PATTERN.findall(context[: m.start() - start + 50])
        program = programs[-1].strip() if programs else None

        # Trouver la chaîne mentionnée dans le contexte
        channel = None
        for ch in MAJOR_CHANNELS:
            if re.search(rf"\b{re.escape(ch)}\b", context):
                channel = ch
                break
        if channel == "SAT.1":
            channel = "Sat.1"  # normalisation

        try:
            viewers = parse_viewers_millions(m.group("viewers"))
            share = parse_share_percent(m.group("share"))
        except ValueError as e:
            log.debug(f"Skip match non parsable: {e}")
            continue

        if not program or not channel:
            continue
        # Filtre prime time : au moins 500 000 téléspectateurs (seuil typique)
        if viewers < 500_000:
            continue

        entries.append({
            "channel": channel,
            "program": program,
            "viewers": viewers,
            "share": share,
        })

    # Dédupliquer (même programme peut être mentionné plusieurs fois dans l'article)
    seen = set()
    deduped: list[dict] = []
    for e in entries:
        key = (e["channel"], e["program"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    # Trier par téléspectateurs décroissants, garder les 5 premiers
    deduped.sort(key=lambda x: x["viewers"], reverse=True)
    top5 = deduped[:5]

    log.info(f"Extracted {len(top5)} entrées du top 5")

    return [
        AudienceEntry(
            rank=i + 1,
            channel=e["channel"],
            channel_color=color_for(e["channel"]),
            program=e["program"],
            program_fr=translate(e["program"]),
            viewers=e["viewers"],
            share=e["share"],
            source_url=url,  # lien direct vers l'article DWDL
        )
        for i, e in enumerate(top5)
    ]


# ─── Étape 3 : orchestration ───────────────────────────────────────

def run(target_date: Optional[date] = None) -> CountryReport:
    """Point d'entrée du scraper. target_date=None → audiences de la veille."""
    if target_date is None:
        target_date = yesterday()

    log.info(f"=== Scraping {COUNTRY_NAME} pour le {target_date.isoformat()} ===")

    try:
        article_url = find_article_url_for_date(target_date)
        if article_url is None:
            raise RuntimeError(f"Pas d'article trouvé pour {target_date}")

        entries = parse_article(article_url)
        if not entries:
            raise RuntimeError("Article trouvé mais aucune audience extraite")

        status = "ok" if len(entries) == 5 else "partial"

        return CountryReport(
            country_code=COUNTRY_CODE,
            country_name=COUNTRY_NAME,
            flag=FLAG,
            date=target_date.isoformat(),
            source_name=SOURCE_NAME,
            source_url=SOURCE_URL,
            entries=entries,
            scraped_at=datetime.utcnow().isoformat() + "Z",
            status=status,
        )

    except Exception as e:
        log.exception("Scraping failed")
        return CountryReport(
            country_code=COUNTRY_CODE, country_name=COUNTRY_NAME, flag=FLAG,
            date=target_date.isoformat(), source_name=SOURCE_NAME, source_url=SOURCE_URL,
            entries=[], scraped_at=datetime.utcnow().isoformat() + "Z",
            status="failed", error=str(e),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    report = run()
    save_report(report)
    if report.status == "failed":
        sys.exit(1)
