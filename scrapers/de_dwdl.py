"""
Scraper Allemagne — DWDL.de / Zahlenzentrale (v2)
 
Source : https://www.dwdl.de/zahlenzentrale/
 
La page Zahlenzentrale publie directement un tableau HTML
"Meistgesehene Sendungen (ab 3)" avec le top 25 du dernier jour disponible,
au format : heure | titre | viewers (Mio) | PDM (%).
 
La date est indiquée dans un heading du type "Die Quoten-Charts von
[Jour], dem DD.MM.YYYY". On extrait cette date comme référence (elle
peut être de J-1 ou J-2 selon l'heure de publication).
 
Stratégie v2 :
1. Fetch la page Zahlenzentrale
2. Extraire la date affichée (c'est "la date des chiffres", pas la date du scraping)
3. Parser le tableau "Meistgesehene Sendungen (ab 3)"
4. Filtrer au prime time (émissions commençant entre 19h45 et 22h30)
5. Mapper les noms de programmes aux chaînes (via heuristique)
6. Prendre les 5 meilleures audiences prime time
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
 
 
COUNTRY_CODE = "DE"
COUNTRY_NAME = "Allemagne"
FLAG = "🇩🇪"
SOURCE_NAME = "DWDL.de · Zahlenzentrale"
SOURCE_URL = "https://www.dwdl.de/zahlenzentrale/"
 
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
}
 
# Heuristique d'attribution programme → chaîne.
# DWDL ne met pas le nom de la chaîne dans le tableau, seulement le programme.
# Astuce : [ß\u00df] ou [ss] en alternance permet de matcher "große" ET "grosse"
# et [''] pour matcher apostrophes droites ET typographiques
# Les patterns les plus spécifiques d'abord (Das Erste avant ZDF pour éviter conflits)
PROGRAM_TO_CHANNEL: list[tuple[re.Pattern, str]] = [
    # Das Erste (ARD) — patterns très spécifiques à cette chaîne
    (re.compile(r"\b(?:Tagesschau|Tagesthemen|Tatort|Brennpunkt|Plusminus|In aller Freundschaft|Sturm der Liebe|Wer wei(?:ß|ss)? denn sowas|Report Mainz|Panorama|Kontraste|hart aber fair|Anne Will|Maischberger|Kein einfacher Mord)", re.IGNORECASE), "Das Erste"),
    # ZDF
    (re.compile(r"\b(?:heute journal|heute-show|heute\s+Xpress|heute - in Europa|auslandsjournal|Markus Lanz|Bares f(?:ü|u)r Rares|SOKO|Watzmann ermittelt|Friesland|Wilsberg|Der Bergdoktor|Fr(?:ü|u)hling|besseresser|Ein Fall f(?:ü|u)r zwei|Kommissarin Heller|Der Staatsanwalt|Doc Caro|Die Rosenheim-Cops|heute journal update|ZDF)", re.IGNORECASE), "ZDF"),
    # "heute" tout seul (sans suffixe) → ZDF
    (re.compile(r"^heute$", re.IGNORECASE), "ZDF"),
    # RTL
    (re.compile(r"\b(?:RTL Aktuell|Gute Zeiten|GZSZ|Alles was z(?:ä|a)hlt|AWZ|Exclusiv|Wer wird Million(?:ä|a)r|Stern TV|Inside Ferrero|Inside\s|Ninja Warrior|Let['\u2019]?s Dance|Bauer sucht Frau|Das Supertalent|Deutschland sucht den Superstar|DSDS|Die Bachelorette|Der Bachelor|Ich bin ein Star|Dschungelcamp|Das gro(?:ße|sse) Promibacken|RTL)\b", re.IGNORECASE), "RTL"),
    # ProSieben
    (re.compile(r"\b(?:Germany['\u2019]?s Next Topmodel|GNTM|TV total|The Voice of Germany|Joko\s*(?:&|und)\s*Klaas|taff|Galileo|Circus HalliGalli|Schlag den Star|Wer stiehlt mir die Show|Zervakis|Fake News|Kings of Scam|Ender['\u2019]?s Game|ProSieben)", re.IGNORECASE), "ProSieben"),
    # Sat.1
    (re.compile(r"\b(?:Sat\.1|The Voice Senior|Ronzheimer|Promis unter Palmen|Akte|Navy CIS|Criminal Minds|Ein Hof zum Verlieben|Landarztpraxis|K11|Das gro(?:ße|sse) Backen)", re.IGNORECASE), "Sat.1"),
    # VOX
    (re.compile(r"\b(?:VOX|Kitchen Impossible|Die H(?:ö|o)hle der L(?:ö|o)wen|Hot oder Schrott|Prominent!|Goodbye Deutschland|auto mobil|Shopping Queen|Das perfekte Dinner)", re.IGNORECASE), "VOX"),
    # Kabel Eins
    (re.compile(r"\b(?:kabel eins|Kabel Eins|Rosins Restaurants|Achtung Kontrolle|Abenteuer Leben|Mein Lokal[, ]Dein Lokal)", re.IGNORECASE), "Kabel Eins"),
    # RTLzwei
    (re.compile(r"\b(?:RTL[Zz]wei|RTL 2|Hartz Rot Gold|Armes Deutschland|Love Island|Berlin Tag und Nacht|K(?:ö|o)ln 50667|Die Wollnys|Hartes Deutschland)", re.IGNORECASE), "RTLzwei"),
]
 
# Prime time : 19h45 à 22h30 (le prime allemand commence vers 20h15)
PRIME_START_MIN = 19 * 60 + 45
PRIME_END_MIN = 22 * 60 + 30
 
log = logging.getLogger("de_dwdl")
 
 
def extract_date_from_page(soup: BeautifulSoup) -> Optional[date]:
    """Cherche 'Die Quoten-Charts von ..., dem DD.MM.YYYY' dans les headings."""
    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(strip=True)
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
        if m and ("Quoten" in text or "Charts" in text):
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
    # Fallback : chercher n'importe où dans le contenu
    body_text = soup.get_text()
    m = re.search(r"Quoten-Charts von [^,]+, dem (\d{1,2})\.(\d{1,2})\.(\d{4})", body_text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    log.warning("Date du tableau non trouvée")
    return None
 
 
def parse_time_to_minutes(time_str: str) -> Optional[int]:
    m = re.match(r"(\d{1,2}):(\d{2})", time_str.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))
 
 
def parse_viewers_mio(text: str) -> Optional[int]:
    """ "3,804 Mio" → 3804000 """
    m = re.search(r"([\d,]+)\s*Mio", text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return int(float(raw) * 1_000_000)
    except ValueError:
        return None
 
 
def parse_share_pct(text: str) -> Optional[float]:
    """ "17,4%" → 17.4 """
    m = re.search(r"([\d,]+)\s*%", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None
 
 
def guess_channel(program: str) -> Optional[str]:
    for pattern, channel in PROGRAM_TO_CHANNEL:
        if pattern.search(program):
            return channel
    return None
 
 
def parse_main_table(soup: BeautifulSoup) -> list[dict]:
    """Extrait les lignes du tableau 'Meistgesehene Sendungen (ab 3)'."""
    target_table = None
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)
        if "Meistgesehene Sendungen" in text and "ab 3" in text:
            target_table = table
            break
    # Fallback : premier gros tableau avec "Mio" et "%"
    if target_table is None:
        for table in soup.find_all("table"):
            text = table.get_text(" ", strip=True)
            if "Mio" in text and "%" in text and len(text) > 200 and text.count("Mio") >= 5:
                target_table = table
                log.info("Fallback: tableau détecté par heuristique")
                break
 
    if target_table is None:
        log.error("Aucun tableau d'audiences trouvé")
        return []
 
    rows = []
    for tr in target_table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 4:
            continue
        time_idx = next((i for i, c in enumerate(cells) if re.match(r"\d{1,2}:\d{2}$", c.strip())), None)
        if time_idx is None or time_idx + 3 >= len(cells):
            continue
        time_min = parse_time_to_minutes(cells[time_idx])
        title = cells[time_idx + 1].strip()
        viewers = parse_viewers_mio(cells[time_idx + 2])
        share = parse_share_pct(cells[time_idx + 3])
        if time_min is None or not title or viewers is None or share is None:
            continue
        rows.append({
            "time_min": time_min, "time_str": cells[time_idx],
            "program": title, "viewers": viewers, "share": share,
        })
    log.info(f"Parsed {len(rows)} lignes du tableau")
    return rows
 
 
def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} ===")
 
    try:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
 
        effective_date = extract_date_from_page(soup) or date.today()
        log.info(f"Date effective des chiffres : {effective_date}")
 
        all_rows = parse_main_table(soup)
        if not all_rows:
            raise RuntimeError("Tableau des audiences vide ou non trouvé")
 
        prime_rows = [r for r in all_rows if PRIME_START_MIN <= r["time_min"] <= PRIME_END_MIN]
        log.info(f"Prime time : {len(prime_rows)} lignes (sur {len(all_rows)})")
 
        # 1 entrée max par chaîne (la plus grosse audience)
        top_by_channel: dict[str, dict] = {}
        unknown_programs = []
        for row in prime_rows:
            channel = guess_channel(row["program"])
            if channel is None:
                unknown_programs.append(row["program"])
                continue
            if channel not in top_by_channel or row["viewers"] > top_by_channel[channel]["viewers"]:
                top_by_channel[channel] = {**row, "channel": channel}
 
        if unknown_programs:
            log.info(f"Chaînes non identifiées pour : {unknown_programs}")
 
        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]
 
        if not ranked:
            raise RuntimeError("Aucune entrée prime time identifiable")
 
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
