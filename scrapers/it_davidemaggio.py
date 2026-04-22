"""
Scraper Italie — Davide Maggio

Source : https://www.davidemaggio.it/ascolti-tv
Publie chaque matin les audiences de la veille (parfois J-2 selon AGF).

Stratégie :
1. Aller sur la page d'index /ascolti-tv
2. Identifier le lien vers l'article du dernier jour publié (pas celui "Total Audience")
3. Lire cet article
4. Parser le paragraphe d'intro qui liste les programmes prime time au format :
   "Su [CHAÎNE] **[PROGRAMME]** [verbe] X.XXX.XXX spettatori pari al Y.Y% di share"
5. Dédupliquer par chaîne, garder top 5
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


COUNTRY_CODE = "IT"
COUNTRY_NAME = "Italie"
FLAG = "🇮🇹"
SOURCE_NAME = "Davide Maggio · Ascolti TV"
SOURCE_URL = "https://www.davidemaggio.it/ascolti-tv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
}

# Normalisation des chaînes italiennes (gestion des variantes d'écriture)
CHANNEL_NORMALIZE = {
    "rai1": "Rai 1", "rai 1": "Rai 1", "raiuno": "Rai 1",
    "rai2": "Rai 2", "rai 2": "Rai 2", "raidue": "Rai 2",
    "rai3": "Rai 3", "rai 3": "Rai 3", "raitre": "Rai 3",
    "rai4": "Rai 4", "rai 4": "Rai 4",
    "canale5": "Canale 5", "canale 5": "Canale 5",
    "italia1": "Italia 1", "italia 1": "Italia 1",
    "rete4": "Rete 4", "rete 4": "Rete 4",
    "la7": "La7",
    "tv8": "TV8",
    "nove": "Nove", "sul nove": "Nove",
    "iris": "Iris",
    "la5": "La 5",
    "real time": "Real Time", "realtime": "Real Time",
}

MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

log = logging.getLogger("it_davidemaggio")


def find_latest_article_url(soup: BeautifulSoup) -> Optional[tuple[str, date]]:
    """
    Sur la page /ascolti-tv, trouve l'URL du dernier article "Ascolti TV | [jour] [date]".
    On ignore les articles "Total Audience" (streaming) pour n'avoir que le linéaire.
    Retourne (url, date) ou None.
    """
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Article pattern : /ascolti-tv/ascolti-tv-[jour]-[DD]-[mois]-[YYYY]
        # On exclut les variantes "total-audience"
        if "total-audience" in href.lower():
            continue
        m = re.search(
            r"/ascolti-tv/ascolti-tv-(\w+)-(\d{1,2})-(\w+)-(\d{4})",
            href,
            re.IGNORECASE,
        )
        if not m:
            continue
        day = int(m.group(2))
        month_name = m.group(3).lower()
        year = int(m.group(4))
        if month_name not in MONTHS_IT:
            continue
        try:
            article_date = date(year, MONTHS_IT[month_name], day)
            full_url = href if href.startswith("http") else f"https://www.davidemaggio.it{href}"
            log.info(f"Article trouvé : {full_url} (date {article_date})")
            return (full_url, article_date)
        except ValueError:
            continue
    return None


def normalize_channel(raw: str) -> Optional[str]:
    """Normalise un nom de chaîne italien. Retourne None si non reconnue."""
    cleaned = raw.strip().lower()
    # Enlever "su" / "sul" / "sulla" / "sulle" en préfixe
    cleaned = re.sub(r"^(su|sul|sulla|sulle)\s+", "", cleaned)
    return CHANNEL_NORMALIZE.get(cleaned)


def parse_italian_number(num_str: str) -> int:
    """ "2.741.000" → 2741000 (le point = séparateur de milliers en italien) """
    return int(num_str.replace(".", "").replace(",", ""))


def parse_intro_paragraph(soup: BeautifulSoup) -> list[dict]:
    """
    Trouve le paragraphe d'intro principale de l'article (celui qui liste les programmes
    prime time) et parse chaque mention "Su [chaîne] [programme] ... spettatori pari al X%".
    """
    # Chercher le premier paragraphe contenant plusieurs mentions "Su Rai" ou "Su Canale"
    best_p = None
    best_count = 0
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        count = len(re.findall(r"\b[Ss]u (?:Rai|Canale|Italia|Rete|La7|Tv8|TV8|Nove|Iris)", text))
        if count > best_count and "spettatori" in text.lower():
            best_count = count
            best_p = text
    if best_p is None:
        log.warning("Paragraphe d'intro non trouvé, fallback sur body complet")
        best_p = soup.get_text(" ", strip=True)

    log.info(f"Paragraphe d'intro : {len(best_p)} chars, {best_count} mentions chaînes")

    # Pattern capture ultra robuste :
    # "Su [CHAINE] [PROGRAMME] [verbe] X.XXX.XXX spettatori ... Y.Y%"
    # CRUCIAL : [program] doit s'arrêter AVANT le premier chiffre de viewers,
    # sinon la regex traverse plusieurs phrases. On utilise [^.]+? pour rester
    # dans la même phrase ET on met une limite de 80 chars pour éviter les catastrophes.
    row_pattern = re.compile(
        r"[Ss]u\s+(?P<channel>Rai\s?\d|Canale\s?5|Italia\s?1|Rete\s?4|La7|Tv8|TV8|Nove|Iris)"
        r"\s+(?P<program>[^.]{1,80}?)"
        r"\s+(?:interessa|conquista|intrattiene|totalizza|raccoglie|incolla\s+davanti\s+al\s+video|"
        r"raggiunge|appassiona|sigla|convince|segna|ottiene|colleziona|raduna|coinvolge|arriva\s+a|"
        r"è\s+seguito\s+da|è\s+scelto\s+da|è\s+visto\s+da|è\s+la\s+scelta\s+di|fa\s+sintonizzare|"
        r"dà\s+il\s+buongiorno\s+a|tiene\s+informati)"
        r"\s+(?P<viewers>[\d.]+)\s+spettatori"
        r"[^.]{0,80}?"
        r"(?:pari\s+al(?:l')?|con\s+(?:uno|un)\s+share\s+del|con\s+il|del|al|e\s+(?:il|al)|\()"
        r"\s*(?P<share>\d{1,2}(?:[,.]\d)?)\s*%",
        re.IGNORECASE,
    )

    rows = []
    for m in row_pattern.finditer(best_p):
        try:
            channel_raw = m.group("channel")
            channel = normalize_channel(channel_raw)
            if channel is None:
                continue
            program = m.group("program").strip()
            # Nettoyer : enlever les ** de markdown, – en début, trop d'espaces
            program = re.sub(r"\s*[-–—]\s*$", "", program).strip()
            program = program.strip("*").strip()
            if len(program) > 80:
                # Si trop long, probable faux positif — on coupe au premier –
                program = re.split(r"\s[-–—]\s", program)[0].strip()

            viewers = parse_italian_number(m.group("viewers"))
            share = float(m.group("share").replace(",", "."))
            rows.append({
                "channel": channel,
                "program": program,
                "viewers": viewers,
                "share": share,
            })
        except (ValueError, KeyError) as e:
            log.debug(f"Skip ligne mal parsée : {e}")
            continue

    log.info(f"Parsé {len(rows)} lignes du paragraphe prime time")
    return rows


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} ===")

    try:
        # 1) Trouver l'URL du dernier article + sa date
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        index_soup = BeautifulSoup(r.text, "html.parser")

        result = find_latest_article_url(index_soup)
        if result is None:
            raise RuntimeError("Aucun article 'Ascolti TV' récent trouvé")
        article_url, effective_date = result

        # 2) Fetch l'article
        r2 = requests.get(article_url, headers=HEADERS, timeout=30)
        r2.raise_for_status()
        article_soup = BeautifulSoup(r2.text, "html.parser")

        # 3) Parser les lignes
        rows = parse_intro_paragraph(article_soup)
        if not rows:
            raise RuntimeError("Aucune ligne extraite du paragraphe d'intro")

        # 4) Déduplication par chaîne (plus grosse audience)
        top_by_channel: dict[str, dict] = {}
        for row in rows:
            ch = row["channel"]
            if ch not in top_by_channel or row["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = row

        # 5) Top 5 par viewers
        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]
        if not ranked:
            raise RuntimeError("Après dédup, aucune entrée")

        log.info(f"Top 5 retenu : {[(r['channel'], r['program'], r['viewers']) for r in ranked]}")

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

        status = "ok" if len(entries) == 5 else "partial"

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
