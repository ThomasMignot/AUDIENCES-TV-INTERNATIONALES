"""
Utilitaires partagés par tous les scrapers.
Format de données normalisé, helpers de parsing, I/O.
"""
from __future__ import annotations
 
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
 
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
 
 
@dataclass
class AudienceEntry:
    """Une ligne d'audience : un programme sur une chaîne, un soir donné."""
    rank: int                   # 1 à 5 (top 5 prime)
    channel: str                # "ZDF", "TF1", "BBC One"...
    channel_color: str          # clé de palette : blue, red, amber, green, teal, purple, pink, coral
    program: str                # titre original
    program_fr: Optional[str]   # titre français si adaptation officielle, sinon None
    viewers: int                # nombre de téléspectateurs (entier)
    share: float                # part de marché en % (ex: 17.8)
    source_url: str             # lien direct vers l'article qui fournit ce chiffre
 
 
@dataclass
class CountryReport:
    """Le top 5 d'un pays pour une date donnée."""
    country_code: str           # "DE", "ES", "IT"...
    country_name: str           # "Allemagne", "Espagne"...
    flag: str                   # emoji drapeau
    date: str                   # "2026-04-21" (date des diffusions, pas du scraping)
    source_name: str            # "DWDL.de · Die Quoten"
    source_url: str             # URL de la page source générale
    entries: list[AudienceEntry]
    scraped_at: str             # ISO timestamp du moment où on a scrapé
    status: str                 # "ok" | "partial" | "failed"
    error: Optional[str] = None
 
 
# ─── Helpers de parsing ────────────────────────────────────────────
 
def parse_german_number(text: str) -> float:
    """
    Convertit un nombre au format allemand/français en float.
    Ex: "3,42" → 3.42 · "1.234,56" → 1234.56
    """
    cleaned = text.strip().replace(" ", "").replace("\u00a0", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)
 
 
def parse_viewers_millions(text: str) -> int:
    """
    "3,42 Millionen" → 3420000 · "1,05 Mio." → 1050000
    Gère aussi "940.000" ou "940 000" → 940000
    """
    text = text.strip()
    m = re.search(r"([\d.,]+)\s*(?:Mio|Million|M)", text, re.IGNORECASE)
    if m:
        return int(parse_german_number(m.group(1)) * 1_000_000)
    m = re.search(r"([\d.,\s]+)", text)
    if m:
        raw = m.group(1).strip()
        if "." in raw and "," not in raw and len(raw.replace(".", "")) >= 4:
            return int(raw.replace(".", ""))
        if " " in raw:
            return int(raw.replace(" ", ""))
        return int(parse_german_number(raw))
    raise ValueError(f"Impossible de parser le nombre de téléspectateurs: {text!r}")
 
 
def parse_share_percent(text: str) -> float:
    """ "17,8 Prozent" → 17.8 · "22.3%" → 22.3 """
    m = re.search(r"([\d.,]+)\s*(?:%|Prozent)", text)
    if not m:
        raise ValueError(f"Impossible de parser la PDM: {text!r}")
    return parse_german_number(m.group(1))
 
 
# ─── Couleurs des chaînes ──────────────────────────────────────────
 
# Palette pastel cohérente, reprise par le dashboard
CHANNEL_COLORS: dict[str, str] = {
    # Allemagne
    "ZDF": "amber", "Das Erste": "blue", "ARD": "blue",
    "RTL": "red", "ProSieben": "pink", "Sat.1": "green",
    "SAT.1": "green", "Kabel Eins": "teal", "RTL2": "coral", "RTLzwei": "coral",
    "VOX": "purple",
    # Espagne
    "La 1": "red", "TVE": "red", "Antena 3": "amber", "A3": "amber",
    "Telecinco": "blue", "T5": "blue", "La Sexta": "green",
    "Cuatro": "purple",
    # Italie
    "Rai 1": "blue", "Rai 2": "teal", "Rai 3": "coral",
    "Canale 5": "red", "Italia 1": "amber", "Rete 4": "purple",
    "La7": "green",
    # UK
    "BBC One": "red", "BBC Two": "amber", "ITV1": "blue", "ITV": "blue",
    "Channel 4": "teal", "Channel 5": "purple",
    # USA
    "CBS": "blue", "NBC": "pink", "ABC": "amber", "Fox": "coral",
    "CW": "green", "The CW": "green",
    # Pays-Bas
    "NPO 1": "amber", "NPO 2": "teal", "NPO 3": "coral",
    "RTL 4": "red", "SBS 6": "blue", "Net 5": "purple",
    # Portugal
    "SIC": "red", "TVI": "blue", "RTP1": "amber", "RTP2": "teal",
    "CMTV": "coral",
    # Australie
    "Seven": "red", "Nine": "blue", "Ten": "amber",
    "ABC": "teal", "SBS": "purple",
}
 
 
def color_for(channel: str) -> str:
    """Retourne la couleur du pill pour une chaîne. Fallback 'gray' si inconnue."""
    return CHANNEL_COLORS.get(channel.strip(), "gray")
 
 
# ─── I/O sur disque ────────────────────────────────────────────────
 
def save_report(report: CountryReport) -> None:
    """
    Enregistre le rapport d'un pays.
    1. Met à jour data/latest.json (fusion avec les autres pays déjà scrapés du même jour)
    2. Met à jour data/archive/YYYY-MM-DD.json (même logique)
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
 
    archive_path = ARCHIVE_DIR / f"{report.date}.json"
    latest_path = DATA_DIR / "latest.json"
 
    # Charger l'existant ou créer
    existing = {}
    if archive_path.exists():
        existing = json.loads(archive_path.read_text(encoding="utf-8"))
 
    # Fusionner ce pays
    if "countries" not in existing:
        existing = {"date": report.date, "countries": {}}
    existing["countries"][report.country_code] = _report_to_dict(report)
    existing["last_updated"] = datetime.utcnow().isoformat() + "Z"
 
    # Écrire archive + latest
    archive_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✓ {report.country_code} — {len(report.entries)} entrées sauvegardées pour {report.date}")
 
 
def _report_to_dict(report: CountryReport) -> dict:
    """Sérialise un CountryReport en dict JSON-compatible."""
    d = asdict(report)
    return d
 
 
def yesterday() -> date:
    """Date de la veille (données de la veille, scrapées aujourd'hui)."""
    return date.today() - timedelta(days=1)
