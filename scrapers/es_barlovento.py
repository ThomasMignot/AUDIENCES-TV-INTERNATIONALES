"""
Scraper Espagne — Barlovento Comunicación (v2 — robustesse renforcée)

Source : https://barloventocomunicacion.es/audiencias-tv-ayer/

Format de la section prime time :
    "A continuación, se detallan los programas con mejores audiencias en el
    prime time del [jour], [DD] de [mois] de [YYYY] (con emisión entre las
    22:00 y las 24:00 horas):

    1. (La1) **BARRIO ESPERANZA <ESPERANZA>**: 15,3% y 1.611.000.
    2. (Antena3) **UNA NUEVA VIDA**: 9,8% y 954.000.
    ..."

Stratégie v2 :
1. Fetch la page récap "audiencias-tv-ayer" qui contient le résumé du jour
2. Si la section prime time n'est pas trouvée (page modifiée), fallback :
   suivre le lien "Audiencias DD de mois" vers l'article daily détaillé
3. Patterns multiples pour matcher différentes variantes de format
4. Logs détaillés pour diagnostiquer les échecs
5. Dédup par chaîne (1 entrée max), top 5
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime, timedelta
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
    "tv3": "TV3",
}

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

log = logging.getLogger("es_barlovento")


def extract_date(soup: BeautifulSoup, full_text: str) -> Optional[date]:
    """
    Cherche la date des audiences.
    Priorité au pattern "del [jour] DD de mes de YYYY" qui apparaît dans
    l'intro du prime time (date des audiences = la veille du jour de scraping).
    """
    # Pattern 1 : "prime time del [jour] DD de [mois] de YYYY"
    # C'est la formule la plus fiable car elle indique explicitement la date
    # des audiences (et pas la date d'aujourd'hui).
    m = re.search(
        r"prime time del\s+\w+\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
        full_text, re.IGNORECASE,
    )
    if m:
        try:
            month = MONTHS_ES.get(m.group(2).lower())
            if month:
                return date(int(m.group(3)), month, int(m.group(1)))
        except ValueError:
            pass

    # Pattern 2 : "ayer [jour] DD de mes" (présent dans l'intro)
    m = re.search(
        r"ayer\s+\w+\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
        full_text, re.IGNORECASE,
    )
    if m:
        try:
            month = MONTHS_ES.get(m.group(2).lower())
            if month:
                return date(int(m.group(3)), month, int(m.group(1)))
        except ValueError:
            pass

    # Pattern 3 : "Audiencias DD de mes YYYY" (titre H3, fallback)
    m = re.search(
        r"Audiencias\s+(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})",
        full_text, re.IGNORECASE,
    )
    if m:
        try:
            month = MONTHS_ES.get(m.group(2).lower())
            if month:
                return date(int(m.group(3)), month, int(m.group(1)))
        except ValueError:
            pass

    return None


def normalize_channel(raw: str) -> str:
    """Normalise le nom d'une chaîne."""
    return CHANNEL_NORMALIZE.get(raw.strip().lower(), raw.strip())


def parse_spanish_number(num_str: str) -> int:
    """ "1.611.000" → 1611000 (le point = séparateur de milliers en espagnol) """
    return int(num_str.replace(".", "").replace(",", ""))


def parse_prime_time_section(full_text: str) -> list[dict]:
    """
    Extrait les lignes numérotées de la section prime time.
    Format type : "1. (La1) **BARRIO ESPERANZA <ESPERANZA>**: 15,3% y 1.611.000."
    """
    # Plusieurs patterns testés du plus spécifique au plus permissif.
    # Le format de Barlovento varie selon les jours, on prévoit large.
    prime_markers = [
        r"mejores audiencias en el prime time",  # le plus stable
        r"detallan los programas[^.]{0,200}?prime time",
        r"en el prime time[^.]*?(?:22:00|22\s*h|22\.00)",
        r"prime time[^.]{0,200}?(?:22:00|22\s*h|22\.00)",
    ]
    start_idx = None
    matched_pattern = None
    for marker in prime_markers:
        m = re.search(marker, full_text, re.IGNORECASE | re.DOTALL)
        if m:
            start_idx = m.end()
            matched_pattern = marker[:60]
            break

    if start_idx is None:
        # Diagnostic : où trouve-t-on "prime time" dans le texte ?
        prime_time_occurrences = list(re.finditer(r"prime[\s-]*time", full_text, re.IGNORECASE))
        log.error(f"Section prime time non trouvée. {len(prime_time_occurrences)} occurrences "
                  f"de 'prime time' dans {len(full_text)} chars de texte.")
        for m in prime_time_occurrences[:5]:
            ctx = full_text[max(0, m.start()-30):m.end()+100]
            log.error(f"  Contexte : {ctx!r}")
        return []

    log.info(f"Section prime time trouvée via : {matched_pattern!r}")

    # Limiter le scope aux ~3000 premiers caractères après le marqueur
    scope = full_text[start_idx:start_idx + 3000]

    # Pattern : "1. (Chaîne) PROGRAMME : XX,X% y X.XXX.XXX"
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


def find_daily_article_url(soup: BeautifulSoup) -> Optional[str]:
    """
    Sur la page récap, cherche le lien vers l'article daily détaillé du jour
    (ex: /audiencias-diarias/audiencias-27-de-abril/).
    Utilisé en fallback si la page récap ne contient pas la section prime time.
    """
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/audiencias-diarias/audiencias-" in href:
            full_url = href if href.startswith("http") else f"https://barloventocomunicacion.es{href}"
            log.info(f"Article daily trouvé : {full_url}")
            return full_url
    return None


def format_program_title(raw: str) -> str:
    """
    Transforme 'BARRIO ESPERANZA <ESPERANZA>' en 'Barrio Esperanza (Esperanza)'.
    """
    text = raw.replace("<", "(").replace(">", ")").strip()

    LOWERCASE_WORDS = {
        "de", "del", "la", "el", "los", "las", "y", "o", "u",
        "en", "a", "al", "con", "por", "para", "sin", "sobre",
        "un", "una", "unos", "unas", "the", "of", "and", "in", "on",
    }
    KEEP_UPPER = {"TV", "CSI", "NCIS", "OT", "UFC", "NBA", "NFL", "UK", "US", "EE", "UU", "DNI", "IVA", "PIB"}

    tokens = re.findall(r"\w+|[^\w\s]+|\s+", text, re.UNICODE)
    result = []
    word_count = 0
    for tok in tokens:
        if tok.isspace() or not tok.strip():
            result.append(tok)
            continue
        if not any(c.isalnum() for c in tok):
            result.append(tok)
            continue
        word_count += 1
        upper_tok = tok.upper()
        lower_tok = tok.lower()

        if upper_tok in KEEP_UPPER:
            result.append(upper_tok)
        elif word_count > 1 and lower_tok in LOWERCASE_WORDS:
            result.append(lower_tok)
        else:
            result.append(tok[0].upper() + tok[1:].lower())

    return "".join(result)


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} (v2) ===")

    try:
        # 1. Fetcher la page récap principale
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        full_text = soup.get_text(" ", strip=True)
        log.info(f"DEBUG: page récap HTTP {r.status_code}, {len(r.text)} chars HTML, "
                 f"{len(full_text)} chars text, encoding={r.encoding}")

        # 2. Extraire la date des audiences (= la veille du scraping en nominal)
        # IMPORTANT : ne PAS faire fallback sur date.today(), sinon on archive
        # à la date d'aujourd'hui des données de la veille → archives futures.
        effective_date = extract_date(soup, full_text)
        if effective_date is None:
            effective_date = date.today() - timedelta(days=1)
            log.warning(f"Date non extraite, fallback sur hier : {effective_date}")
        else:
            log.info(f"Date effective : {effective_date}")

        # 3. Parser la section prime time depuis la page récap
        rows = parse_prime_time_section(full_text)

        # 4. FALLBACK : si la section prime time n'est pas dans la page récap,
        # on suit le lien vers l'article daily et on parse celui-là.
        if not rows:
            log.info("Section prime time absente de la page récap, fallback sur article daily")
            daily_url = find_daily_article_url(soup)
            if daily_url:
                try:
                    r2 = requests.get(daily_url, headers=HEADERS, timeout=30)
                    r2.raise_for_status()
                    daily_soup = BeautifulSoup(r2.text, "html.parser")
                    daily_text = daily_soup.get_text(" ", strip=True)
                    log.info(f"DEBUG: article daily {len(daily_text)} chars text")
                    rows = parse_prime_time_section(daily_text)
                except requests.RequestException as e:
                    log.warning(f"Erreur en chargeant l'article daily : {e}")

        if not rows:
            raise RuntimeError("Aucune ligne prime time extraite (page récap + article daily)")

        # 5. Déduplication : 1 entrée max par chaîne (la plus grosse audience)
        top_by_channel: dict[str, dict] = {}
        for row in rows:
            ch = row["channel"]
            if ch not in top_by_channel or row["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = row

        # 6. Tri par viewers, top 5
        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]

        if not ranked:
            raise RuntimeError("Après dédup, aucune entrée")

        log.info(f"Top 5 retenu : {[(r['channel'], r['program'], r['viewers']) for r in ranked]}")

        # 7. Chercher l'URL de l'article détaillé pour mettre dans source_url
        detail_url = SOURCE_URL
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if "audiencias-diarias" in href and effective_date.strftime("%d") in text:
                detail_url = href if href.startswith("http") else f"https://barloventocomunicacion.es{href}"
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
        # Fallback de date : hier (cohérent avec les autres scrapers)
        fallback_date = target_date or (date.today() - timedelta(days=1))
        return CountryReport(
            country_code=COUNTRY_CODE, country_name=COUNTRY_NAME, flag=FLAG,
            date=fallback_date.isoformat(),
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
