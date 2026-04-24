"""
Scraper Espagne — Barlovento Comunicación

Source : https://barloventocomunicacion.es/audiencias-tv-ayer/
Publie chaque matin les audiences de la veille avec une structure très stable.

Format du prime time (partie qui nous intéresse) :

    A continuación, se detallan los programas con mejores audiencias en el prime time
    del [jour], [DD] de [mois] de [YYYY] (con emisión entre las 22:00 y las 24:00 horas):

    1. (La1) **BARRIO ESPERANZA <ESPERANZA>**: 15,3% y 1.611.000.
    2. (Antena3) **UNA NUEVA VIDA**: 9,8% y 954.000.
    3. (Telecinco) **SUPERVIVIENTES:CONEXION HONDURAS**: 11,6% y 924.000.
    ...

Stratégie :
1. Fetch la page
2. Extraire la date depuis l'intro ou le titre H3
3. Parser les lignes numérotées de la section prime time
4. Dédupliquer par chaîne (1 entrée max par chaîne)
5. Garder le top 5
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
    color_for, save_report, make_entry,
)
from translations import translate


COUNTRY_CODE = "ES"
COUNTRY_NAME = "Espagne"
FLAG = "🇪🇸"
SOURCE_NAME = "Barlovento Comunicación"
SOURCE_URL = "https://barloventocomunicacion.es/audiencias-tv-ayer/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Normalisation des noms de chaînes : ce que Barlovento écrit → nom affiché
CHANNEL_NORMALIZE = {
    "la1": "La 1",
    "la 1": "La 1",
    "la2": "La 2",
    "la 2": "La 2",
    "antena3": "Antena 3",
    "antena 3": "Antena 3",
    "a3": "Antena 3",
    "telecinco": "Telecinco",
    "t5": "Telecinco",
    "lasexta": "La Sexta",
    "la sexta": "La Sexta",
    "cuatro": "Cuatro",
    "energy": "Energy",
    "neox": "Neox",
    "fdf": "FDF",
    "trece": "Trece",
    "be mad": "Be Mad",
    "divinity": "Divinity",
    "paramount": "Paramount Network",
    "paramount network": "Paramount Network",
}

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

log = logging.getLogger("es_barlovento")


def extract_date(soup: BeautifulSoup, full_text: str) -> Optional[date]:
    """
    Cherche la date dans plusieurs endroits possibles :
    - Titre H3 : "Audiencias 19 de abril 2026"
    - Texte : "del domingo 19 de abril de 2026"
    """
    patterns = [
        r"Audiencias\s+(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})",
        r"del\s+\w+\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
        r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if not m:
            continue
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        if month_name in MONTHS_ES:
            try:
                return date(year, MONTHS_ES[month_name], day)
            except ValueError:
                continue
    return None


def normalize_channel(raw: str) -> str:
    """Normalise le nom d'une chaîne ("La1" → "La 1", "A3" → "Antena 3")."""
    return CHANNEL_NORMALIZE.get(raw.strip().lower(), raw.strip())


def parse_spanish_number(num_str: str) -> int:
    """ "1.611.000" → 1611000 (le point est séparateur de milliers en espagnol) """
    return int(num_str.replace(".", "").replace(",", ""))


def parse_prime_time_section(full_text: str) -> list[dict]:
    """
    Extrait les lignes numérotées de la section prime time.
    Format type : "1. (La1) **BARRIO ESPERANZA <ESPERANZA>**: 15,3% y 1.611.000."
    """
    # Trouver le début de la section prime time
    prime_markers = [
        r"en el prime time[^\n]*\(con emisión entre las 22",
        r"mejores audiencias en el prime time",
        r"prime time[^\n]*?(?:22:00|22 h)",
    ]
    start_idx = None
    for marker in prime_markers:
        m = re.search(marker, full_text, re.IGNORECASE)
        if m:
            start_idx = m.end()
            break
    if start_idx is None:
        log.error("Section prime time non trouvée")
        return []

    # Limiter le scope aux ~3000 premiers caractères après le marqueur
    scope = full_text[start_idx:start_idx + 3000]

    # Pattern : "1. (Chaîne) PROGRAMME : XX,X% y X.XXX.XXX"
    # Le programme peut contenir des : (ex: "SUPERVIVIENTES:CONEXION HONDURAS")
    # Astuce : on utilise le pattern "share%" comme ancre robuste (digit,digit% ou digit%)
    # et on capture tout ce qui est entre ) et ce share% comme program
    row_pattern = re.compile(
        r"(?P<rank>\d{1,2})\.\s*"
        r"\((?P<channel>[^)]+)\)\s*"
        r"\*{0,2}(?P<program>.+?)\*{0,2}\s*:\s*"
        r"(?P<share>\d{1,2}(?:[,.]\d)?)\s*%\s*y\s*"
        r"(?P<viewers>[\d.]+)",
        re.IGNORECASE | re.DOTALL,
    )

    rows = []
    for m in row_pattern.finditer(scope):
        try:
            share = float(m.group("share").replace(",", "."))
            viewers = parse_spanish_number(m.group("viewers"))
            channel = normalize_channel(m.group("channel"))
            program = m.group("program").strip().strip("*").strip()
            # Nettoyer : enlever les "< >" de métadonnées mais garder les infos
            # Ex: "BARRIO ESPERANZA <ESPERANZA>" → on garde tel quel, c'est lisible
            rows.append({
                "rank": int(m.group("rank")),
                "channel": channel,
                "program": program,
                "viewers": viewers,
                "share": share,
            })
        except (ValueError, KeyError):
            continue

    log.info(f"Parsed {len(rows)} lignes de la section prime time")
    return rows


def format_program_title(raw: str) -> str:
    """
    Transforme 'BARRIO ESPERANZA <ESPERANZA>' en 'Barrio Esperanza (Esperanza)'.
    Barlovento écrit tout en majuscules, on rend ça plus lisible.

    Règles :
    - Title case (première lettre de chaque mot en majuscule)
    - Les articles / prépositions courts (de, la, el, y, en, a, al, los, las, un, una)
      restent en minuscules SAUF en début de titre
    - Les sigles connus (TV, CSI, MasterChef, NCIS, OT, UFC) sont préservés
    """
    text = raw.replace("<", "(").replace(">", ")").strip()

    # Mots qui restent en minuscules (sauf s'ils sont le premier mot)
    LOWERCASE_WORDS = {
        "de", "del", "la", "el", "los", "las", "y", "o", "u",
        "en", "a", "al", "con", "por", "para", "sin", "sobre",
        "un", "una", "unos", "unas", "the", "of", "and", "in", "on",
    }
    # Sigles à préserver tels quels (en MAJUSCULES)
    KEEP_UPPER = {"TV", "CSI", "NCIS", "OT", "UFC", "NBA", "NFL", "UK", "US", "EE", "UU", "DNI", "IVA", "PIB"}

    # Séparer en tokens en préservant la ponctuation
    tokens = re.findall(r"\w+|[^\w\s]+|\s+", text, re.UNICODE)
    result = []
    word_count = 0  # compte les mots (pour savoir si c'est le premier)
    for tok in tokens:
        if tok.isspace() or not tok.strip():
            result.append(tok)
            continue
        if not any(c.isalnum() for c in tok):
            # Ponctuation seule
            result.append(tok)
            continue
        # C'est un mot
        word_count += 1
        upper_tok = tok.upper()
        lower_tok = tok.lower()

        if upper_tok in KEEP_UPPER:
            result.append(upper_tok)
        elif word_count > 1 and lower_tok in LOWERCASE_WORDS:
            result.append(lower_tok)
        else:
            # Capitalize : première majuscule, reste minuscule
            result.append(tok[0].upper() + tok[1:].lower())

    return "".join(result)


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} ===")

    try:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        # Extraire la date des audiences (date de la veille dans le cas nominal)
        effective_date = extract_date(soup, full_text) or date.today()
        log.info(f"Date effective : {effective_date}")

        # Parser la section prime time
        rows = parse_prime_time_section(full_text)
        if not rows:
            raise RuntimeError("Aucune ligne prime time extraite")

        # Déduplication : 1 entrée max par chaîne (la plus grosse audience)
        top_by_channel: dict[str, dict] = {}
        for row in rows:
            ch = row["channel"]
            if ch not in top_by_channel or row["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = row

        # Tri par viewers, top 5
        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]

        if not ranked:
            raise RuntimeError("Après dédup, aucune entrée")

        log.info(f"Top 5 retenu : {[(r['channel'], r['program'], r['viewers']) for r in ranked]}")

        # Chercher l'URL de l'article détaillé du jour (lien "Audiencias XX de mois YYYY")
        detail_url = SOURCE_URL
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if "audiencias-diarias" in href and effective_date.strftime("%d") in text:
                detail_url = href
                break

        entries = [
            make_entry(
                rank=i + 1,
                channel=r["channel"],
                program=format_program_title(r["program"]),
                program_fr=translate(r["program"]),
                viewers=r["viewers"],
                share=r["share"],
                source_url=detail_url,
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
