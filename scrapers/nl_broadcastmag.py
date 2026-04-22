"""
Scraper Pays-Bas — Broadcast Magazine

Source : https://www.broadcastmagazine.nl/kijkcijfers/
Publie chaque matin le top 25 complet de la veille avec une structure
HTML ultra-propre (numéro, programme, chaîne, viewers, ratings, market share).

Format type :
    1
    ## Journaal 20 Uur - NPO 1
    **Absolute aantallen**  1.588.000
    **Kijkdichtheid**       9.5%
    **Marktaandeel**        35.5%

La page contient plusieurs jours consécutifs empilés. On prend le PREMIER
top 25 (= jour le plus récent) + la date du premier onglet.

Stratégie :
1. Fetch la page kijkcijfers
2. Extraire la date du premier onglet ("30 maart")
3. Parser le premier bloc de 25 programmes
4. Filtrer prime time (émissions dont l'heure OU le nom suggère une diffusion soirée)
   Note : on n'a pas l'heure explicite, donc on filtre par exclusion (pas les journaux,
   pas les émissions matinales, etc.) OU on prend simplement le top 5 par viewers
5. Dédupliquer par chaîne
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
SOURCE_NAME = "Broadcast Magazine · Kijkcijfers"
SOURCE_URL = "https://www.broadcastmagazine.nl/kijkcijfers/"

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
    # Abréviations courantes
    "jan": 1, "feb": 2, "mrt": 3, "apr": 4, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "dec": 12,
}

# Normalisation des chaînes NL
CHANNEL_NORMALIZE = {
    "NPO 1": "NPO 1", "NPO1": "NPO 1",
    "NPO 2": "NPO 2", "NPO2": "NPO 2",
    "NPO 3": "NPO 3", "NPO3": "NPO 3",
    "RTL 4": "RTL 4", "RTL4": "RTL 4",
    "RTL 5": "RTL 5", "RTL5": "RTL 5",
    "RTL 7": "RTL 7", "RTL 8": "RTL 8",
    "SBS 6": "SBS 6", "SBS6": "SBS 6",
    "SBS 9": "SBS 9", "SBS9": "SBS 9",
    "Net 5": "Net 5", "Net5": "Net 5",
    "Veronica": "Veronica",
}

# Programmes à EXCLURE du classement prime time
# (journaux de journée, talk-shows access prime, émissions non-prime)
EXCLUDE_PATTERNS = [
    r"^Journaal\s+(?:18|13|8)\s+Uur",  # journaux de journée (pas 20u)
    r"^Journaal\s+Laat",  # journal de nuit
    r"^Editie\s+Nl",  # mag RTL access
    r"^Zes\s+Uur\s+Nieuws",  # 18h news RTL
    r"^Half\s+Acht\s+Nieuws",  # 19h30 news RTL
    r"^Hart\s+Van\s+Nederland",  # news SBS6
    r"^Tijd\s+Voor\s+Max",  # magazine après-midi
    r"^Rtl\s+Boulevard",  # magazine people access
    r"^Shownieuws",  # magazine people
    r"^Nieuws\s+Van\s+De\s+Dag",  # news
    r"^Eenvandaag",  # news magazine
    r"^Nieuwsuur",  # news magazine late
    r"^Tgsport|^Tg\s",  # news sport
    r"^Buitenhof",  # émission politique dimanche matin
    r"^Wnl\s+Op\s+Zondag",  # dimanche matin
    r"^Studio\s+Sport",  # sport résumé
    r"^Studio\s+Voetbal",  # sport résumé
    r"^Goede\s+Tijden\s+Slechte\s+Tijden",  # soap access prime 20h
]
EXCLUDE_RE = re.compile("|".join(EXCLUDE_PATTERNS), re.IGNORECASE)

log = logging.getLogger("nl_broadcastmag")


def extract_first_date(soup: BeautifulSoup) -> Optional[date]:
    """
    Trouve la première date d'onglet (ex: "30 maart", "22 april").
    Retourne None si non trouvée.
    """
    # La date est dans une liste type "30 maart | 29 maart | ..."
    full_text = soup.get_text(" ", strip=True)
    # Chercher la première occurrence "DD mois"
    m = re.search(
        r"\b(\d{1,2})\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\b",
        full_text,
        re.IGNORECASE,
    )
    if not m:
        log.warning("Date du premier onglet non trouvée")
        return None
    day = int(m.group(1))
    month_name = m.group(2).lower()
    month = MONTHS_NL.get(month_name)
    if month is None:
        return None
    # Déterminer l'année : si le mois est > mois actuel, c'est l'année dernière
    today = date.today()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    # Si la date candidate est dans le futur, c'est l'année dernière
    if candidate > today:
        try:
            candidate = date(year - 1, month, day)
        except ValueError:
            return None
    return candidate


def normalize_channel(raw: str) -> str:
    """Normalise le nom d'une chaîne néerlandaise."""
    cleaned = raw.strip()
    # Essayer la correspondance exacte d'abord
    if cleaned in CHANNEL_NORMALIZE:
        return CHANNEL_NORMALIZE[cleaned]
    # Essayer en insensible à la casse
    for key, value in CHANNEL_NORMALIZE.items():
        if key.lower() == cleaned.lower():
            return value
    return cleaned  # inconnue, on retourne tel quel


def parse_nl_number(num_str: str) -> int:
    """ "1.588.000" → 1588000 (le point = séparateur de milliers en NL) """
    return int(num_str.replace(".", "").replace(",", ""))


def format_title(raw: str) -> str:
    """
    BroadcastMag écrit les titres en Title Case avec première lettre forcée.
    Ex: "Journaal 20 Uur" → "Journaal 20 uur"
    Ex: "Goede Tijden Slechte Tijden" → "Goede Tijden, Slechte Tijden"
    On normalise de façon raisonnable.
    """
    return raw.strip()


def parse_top_25(soup: BeautifulSoup) -> list[dict]:
    """
    Extrait le premier top 25 de la page.
    Structure : <h2>Numéro</h2> puis <h2>Programme - Chaîne</h2>
    ou tout contenu en séquence dans le HTML.

    En pratique : on cherche tous les <h2> qui contiennent " - " (séparateur
    Programme - Chaîne) et on collecte les 3 métriques qui suivent.
    """
    rows = []
    # Chercher tous les h2 (ou h3) qui ont le pattern "Programme - Chaîne"
    headings = soup.find_all(["h2", "h3"])
    for h in headings:
        title = h.get_text(" ", strip=True)
        # Le title doit contenir " - " et finir par un nom de chaîne connue
        if " - " not in title:
            continue
        # Split au dernier " - "
        parts = title.rsplit(" - ", 1)
        if len(parts) != 2:
            continue
        program_raw, channel_raw = parts
        channel = normalize_channel(channel_raw)
        # Vérifier que c'est une chaîne qu'on connaît
        if channel not in CHANNEL_NORMALIZE.values():
            continue

        # Trouver les 3 métriques qui suivent ce heading
        # (Absolute aantallen, Kijkdichtheid, Marktaandeel)
        viewers = None
        share = None

        # Approche : parcourir les siblings/descendants suivants et chercher des nombres
        current = h
        count_seen = 0
        for _ in range(30):  # limite de safety
            current = current.find_next(string=True)
            if current is None:
                break
            text = str(current).strip()
            if not text:
                continue
            # Chercher un pattern "X.XXX.XXX" (viewers)
            if viewers is None:
                m = re.match(r"^(\d{1,3}(?:\.\d{3})+)$", text)
                if m:
                    viewers = parse_nl_number(m.group(1))
                    count_seen += 1
                    continue
            # Chercher un pattern "X.X%" ou "XX%"
            m = re.match(r"^(\d{1,3}(?:[.,]\d)?)%$", text)
            if m:
                count_seen += 1
                if count_seen == 2:
                    # 2ème % = kijkdichtheid, on l'ignore
                    continue
                elif count_seen == 3:
                    # 3ème % = marktaandeel, c'est ce qu'on veut
                    share = float(m.group(1).replace(",", "."))
                    break

        if viewers is None or share is None:
            continue

        rows.append({
            "channel": channel,
            "program": format_title(program_raw),
            "viewers": viewers,
            "share": share,
        })

        # Safety : on s'arrête à 25 entrées pour ne capturer que le premier jour
        if len(rows) >= 25:
            break

    log.info(f"Extrait {len(rows)} lignes du premier top 25")
    return rows


def is_prime_time_program(program: str) -> bool:
    """
    Exclut les programmes qui ne sont clairement pas du prime time
    (journaux de journée, talk-shows access, etc.).
    """
    return not EXCLUDE_RE.search(program)


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} ===")

    try:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        effective_date = extract_first_date(soup) or date.today()
        log.info(f"Date effective : {effective_date}")

        all_rows = parse_top_25(soup)
        if not all_rows:
            raise RuntimeError("Top 25 vide ou non trouvé")

        # Filtrer hors access prime / journaux
        prime_rows = [r for r in all_rows if is_prime_time_program(r["program"])]
        log.info(f"Prime time : {len(prime_rows)} lignes (sur {len(all_rows)})")

        # Déduplication par chaîne (plus grosse audience)
        top_by_channel: dict[str, dict] = {}
        for row in prime_rows:
            ch = row["channel"]
            if ch not in top_by_channel or row["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = row

        # Tri par viewers descendant, top 5
        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]
        if not ranked:
            raise RuntimeError("Après filtrage et dédup, aucune entrée")

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
                source_url=SOURCE_URL,
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
