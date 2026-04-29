"""
Utilitaires partagés par tous les scrapers.
Format de données normalisé, helpers de parsing, I/O.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
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
    category: str = "autre"     # "fiction" | "divertissement" | "info" | "sport" | "autre"
    category_emoji: str = "📺"  # emoji associé à la catégorie
    wikipedia_url: str = ""     # lien Wikipédia dans la langue du pays (généré auto par make_entry)


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
    # France
    "TF1": "blue", "France 2": "red", "France 3": "amber",
    "France 4": "teal", "France 5": "purple",
    "M6": "coral", "W9": "pink", "6ter": "pink",
    "Arte": "purple", "Canal+": "green", "Canal +": "green",
    "TMC": "blue", "TFX": "coral", "TF1 Series Film": "blue",
    "TF1 Séries Films": "blue",
    "C8": "amber", "CStar": "teal", "CSTAR": "teal",
    "Gulli": "pink", "RMC Story": "coral", "RMC Découverte": "amber",
    "RMC Decouverte": "amber", "RMC Life": "teal",
    "NRJ 12": "red", "NRJ12": "red",
    "TV Breizh": "teal", "Paris Première": "purple", "Paris Premiere": "purple",
    "Chérie 25": "pink", "Cherie 25": "pink",
    "LCI": "blue", "Franceinfo": "blue", "BFM TV": "red", "CNews": "blue",
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
    "SBS": "purple",
}


def color_for(channel: str) -> str:
    """Retourne la couleur du pill pour une chaîne. Fallback 'gray' si inconnue."""
    return CHANNEL_COLORS.get(channel.strip(), "gray")


# ─── Liens Wikipédia par pays ──────────────────────────────────────

# Code pays → code langue Wikipédia (= sous-domaine wikipedia.org)
COUNTRY_TO_WIKI_LANG: dict[str, str] = {
    "FR": "fr",
    "DE": "de",
    "ES": "es",
    "IT": "it",
    "NL": "nl",
    "BE": "fr",   # Belgique francophone par défaut (à raffiner si besoin)
    "PT": "pt",
    "GB": "en",
    "US": "en",
    "CA": "en",   # Canada anglophone par défaut
    "AU": "en",
    "BR": "pt",
    "DK": "da",
    "SE": "sv",
}

# Mots qu'on enlève en début/fin de titre avant de générer l'URL
# (ex: "FILM", "SERIE", "TELEFILM" qui viennent d'Ozap et ne sont pas
# dans les vrais titres des programmes)
TITLE_NOISE_SUFFIXES = (
    "FILM", "SERIE", "TELEFILM", "MAGAZINE", "DOCUMENTAIRE",
    "JEU", "DIVERTISSEMENT", "HUMOUR", "MUSIQUE", "SPORT",
    "TALK-SHOW", "JOURNAL TELEVISE", "INFORMATION", "AUTRES",
)


def _clean_program_for_wiki(program: str) -> str:
    """
    Nettoie un nom de programme avant d'en faire une URL Wikipédia.
    - Retire les suffixes parasites (FILM, SERIE, ...)
    - Coupe au premier ":" ou "<" (sous-titres / épisodes)
      Ex: "EL HORMIGUERO <BAD GYAL>" → "EL HORMIGUERO"
          "LA ISLA DE LAS TENTACIONES:EXPRESS" → "LA ISLA DE LAS TENTACIONES"
          "Tatort: Gegen die Zeit" → "Tatort"
    - Met en title case si le titre est tout en majuscules (cas Ozap, Barlovento)
    """
    if not program:
        return ""

    cleaned = program.strip()

    # Retirer les suffixes parasites en fin (ex: "UN P'TIT TRUC EN PLUS FILM")
    upper = cleaned.upper()
    for suffix in sorted(TITLE_NOISE_SUFFIXES, key=len, reverse=True):
        suffix_with_space = " " + suffix
        if upper.endswith(suffix_with_space):
            cleaned = cleaned[: -len(suffix_with_space)].strip()
            upper = cleaned.upper()
            break

    # Couper au premier "<" (sous-titres entre chevrons type Barlovento)
    if "<" in cleaned:
        cleaned = cleaned.split("<", 1)[0].strip()

    # Couper au premier ":" suivi d'espace ou texte (sous-titres)
    # Garder "N.C.I.S." mais couper "Tatort: Gegen die Zeit"
    m = re.search(r":\s*[A-Za-zÀ-ÿ]", cleaned)
    if m and m.start() > 1:  # >1 pour ne pas couper "N:foo"
        cleaned = cleaned[: m.start()].strip()

    # Couper aux séparateurs "/" et " - " et " – " (variantes éditoriales)
    for sep in [" / ", " - ", " – ", " — "]:
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip()

    # Si tout en majuscules (cas Ozap, Barlovento), title case
    if cleaned.isupper() and len(cleaned) > 3:
        # Title case basique en respectant les apostrophes : UN P'TIT → Un P'tit
        cleaned = " ".join(
            w.capitalize() if "'" not in w else
            "'".join(part.capitalize() for part in w.split("'"))
            for w in cleaned.split()
        )

    return cleaned


def wikipedia_url_for(program: str, country_code: str) -> str:
    """
    Génère un lien Wikipédia vers la fiche du programme dans la langue du pays.
    Utilise l'API Wikipédia pour vérifier que la page existe vraiment :
    - Si la page existe au titre deviné → URL directe
    - Sinon, recherche Wikipédia → URL du 1er résultat trouvé
    - Si rien ne marche → URL de la page de recherche (fallback)

    Le résultat est mis en cache (en mémoire) pour ne pas re-pinguer
    la même URL plusieurs fois dans un même run.

    Wikipédia n'a pas de rate limit pour ce volume (25 pings/jour max).
    """
    if not program:
        return ""

    lang = COUNTRY_TO_WIKI_LANG.get(country_code, "en")
    cleaned = _clean_program_for_wiki(program)

    if not cleaned:
        return f"https://{lang}.wikipedia.org/wiki/Special:Search?search="

    # 1. Essai de la page directe (titre deviné)
    direct = _check_wiki_page_exists(cleaned, lang)
    if direct:
        return direct

    # 2. Recherche Wikipédia → 1er résultat
    found = _search_wiki(cleaned, lang)
    if found:
        return found

    # 3. Fallback : page de recherche avec titre prérempli
    from urllib.parse import quote
    return f"https://{lang}.wikipedia.org/wiki/Special:Search?search={quote(cleaned)}"


# Cache mémoire pour éviter de re-pinguer la même URL plusieurs fois
# pendant un run (6 cron/jour × 5 pays × 5 programmes pourraient générer
# beaucoup de requêtes redondantes sinon).
_WIKI_CACHE: dict[tuple[str, str], Optional[str]] = {}


def _check_wiki_page_exists(title: str, lang: str) -> Optional[str]:
    """
    Vérifie via l'API REST de Wikipédia si une page existe au titre exact.
    Retourne l'URL canonique si elle existe, None sinon.

    API utilisée : /api/rest_v1/page/summary/{title} qui renvoie 200 si
    la page existe (ou redirige vers la page canonique), 404 sinon.
    """
    cache_key = ("exists", lang, title)
    if cache_key in _WIKI_CACHE:
        return _WIKI_CACHE[cache_key]

    from urllib.parse import quote
    import requests as _requests

    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}"
    try:
        r = _requests.get(
            url,
            headers={"User-Agent": "AudiencesTV-Dashboard/1.0 (veille personnelle)"},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            # Wikipédia peut renvoyer une page de désambiguïsation ("disambiguation")
            # ou une redirection. On les accepte toutes : c'est mieux qu'une 404.
            page_url = data.get("content_urls", {}).get("desktop", {}).get("page")
            if page_url:
                _WIKI_CACHE[cache_key] = page_url
                return page_url
            # Fallback : URL construite depuis le titre canonique retourné
            canonical = data.get("title", title).replace(" ", "_")
            page_url = f"https://{lang}.wikipedia.org/wiki/{quote(canonical)}"
            _WIKI_CACHE[cache_key] = page_url
            return page_url
        # 404 : la page n'existe pas
        _WIKI_CACHE[cache_key] = None
        return None
    except Exception:
        # En cas d'erreur réseau, on ne cache pas (on retentera plus tard)
        return None


def _search_wiki(query: str, lang: str) -> Optional[str]:
    """
    Cherche un terme sur Wikipédia et retourne l'URL du 1er résultat.
    Utilise l'API search qui est bien plus tolérante que les URL directes.
    """
    cache_key = ("search", lang, query)
    if cache_key in _WIKI_CACHE:
        return _WIKI_CACHE[cache_key]

    from urllib.parse import quote
    import requests as _requests

    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        r = _requests.get(
            api_url,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 1,
                "format": "json",
            },
            headers={"User-Agent": "AudiencesTV-Dashboard/1.0 (veille personnelle)"},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            results = data.get("query", {}).get("search", [])
            if results:
                title = results[0].get("title", "").replace(" ", "_")
                if title:
                    page_url = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
                    _WIKI_CACHE[cache_key] = page_url
                    return page_url
        _WIKI_CACHE[cache_key] = None
        return None
    except Exception:
        return None


def make_entry(
    rank: int, channel: str, program: str, viewers: int, share: float,
    source_url: str, program_fr: Optional[str] = None,
    country_code: Optional[str] = None,
) -> AudienceEntry:
    """
    Crée une AudienceEntry avec catégorisation automatique et lien Wikipédia.

    `country_code` est optionnel pour rétrocompatibilité, mais le passer
    génère un lien Wikipédia dans la langue du pays (sinon fallback en).
    """
    # Import local pour éviter import circulaire au chargement du module
    from categories import categorize, category_badge
    cat = categorize(program)
    badge = category_badge(cat)
    # Génération du lien Wikipédia. Si pas de country_code, on fallback sur EN.
    wiki = wikipedia_url_for(program, country_code or "")
    return AudienceEntry(
        rank=rank,
        channel=channel,
        channel_color=color_for(channel),
        program=program,
        program_fr=program_fr,
        viewers=viewers,
        share=share,
        source_url=source_url,
        category=cat,
        category_emoji=badge["emoji"],
        wikipedia_url=wiki,
    )


# ─── Champs à PRÉSERVER lors de la réécriture d'un pays ──────────
# Ces champs sont ajoutés par commentary.py APRÈS le scraping.
# Les scrapers ne doivent pas les écraser quand ils sauvegardent.
PRESERVED_FIELDS = ("commentary", "commentary_date")


def _merge_preserve(old_entry: dict, new_entry: dict) -> dict:
    """
    Retourne new_entry enrichi des champs préservés qu'on trouvait dans old_entry.
    Utilisé pour ne pas effacer les commentaires générés par commentary.py
    quand un scraper réécrit son entrée dans latest.json / archive/*.json.
    """
    merged = dict(new_entry)
    for field in PRESERVED_FIELDS:
        if field in old_entry and field not in merged:
            merged[field] = old_entry[field]
    return merged


# ─── I/O sur disque ────────────────────────────────────────────────

def save_report(report: CountryReport) -> None:
    """
    Enregistre le rapport d'un pays.
    1. Met à jour data/archive/YYYY-MM-DD.json (le jour des diffusions de ce pays)
    2. Met à jour data/latest.json qui AGRÈGE TOUS les pays scrapés récemment.

    IMPORTANT : latest.json n'est JAMAIS écrasé par l'archive d'un seul jour.
    On merge systématiquement l'entrée de ce pays dans le latest existant,
    en PRÉSERVANT les autres pays déjà présents ET les champs commentary /
    commentary_date qui auraient été ajoutés par commentary.py.

    BONUS : si une entrée n'a pas de wikipedia_url (ancien format ou scraper
    qui ne passe pas country_code), on génère le lien à la sauvegarde.
    Ça permet de migrer les anciennes entrées en douceur.
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Migration en douceur : compléter wikipedia_url manquant pour les
    # scrapers qui n'auraient pas encore été mis à jour pour passer
    # country_code à make_entry.
    for entry in report.entries:
        if not entry.wikipedia_url:
            entry.wikipedia_url = wikipedia_url_for(entry.program, report.country_code)

    archive_path = ARCHIVE_DIR / f"{report.date}.json"
    latest_path = DATA_DIR / "latest.json"

    # ── 1. Mettre à jour l'archive du jour concerné ──────────────
    existing_archive: dict = {}
    if archive_path.exists():
        try:
            existing_archive = json.loads(archive_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            existing_archive = {}

    if "countries" not in existing_archive:
        existing_archive = {"date": report.date, "countries": {}}

    old_archive_entry = existing_archive["countries"].get(report.country_code, {})
    new_archive_entry = _merge_preserve(old_archive_entry, _report_to_dict(report))
    existing_archive["countries"][report.country_code] = new_archive_entry
    existing_archive["last_updated"] = datetime.utcnow().isoformat() + "Z"

    archive_path.write_text(
        json.dumps(existing_archive, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── 2. Mettre à jour latest.json en PRÉSERVANT les autres pays ──
    existing_latest: dict = {"countries": {}}
    if latest_path.exists():
        try:
            loaded = json.loads(latest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "countries" in loaded:
                existing_latest = loaded
        except (json.JSONDecodeError, ValueError):
            pass

    if "countries" not in existing_latest:
        existing_latest["countries"] = {}

    old_latest_entry = existing_latest["countries"].get(report.country_code, {})
    new_latest_entry = _merge_preserve(old_latest_entry, _report_to_dict(report))
    existing_latest["countries"][report.country_code] = new_latest_entry
    existing_latest["last_updated"] = datetime.utcnow().isoformat() + "Z"

    all_dates = [
        c.get("date") for c in existing_latest["countries"].values()
        if c.get("date")
    ]
    if all_dates:
        existing_latest["date"] = max(all_dates)

    latest_path.write_text(
        json.dumps(existing_latest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✓ {report.country_code} — {len(report.entries)} entrées sauvegardées pour {report.date}")


def _report_to_dict(report: CountryReport) -> dict:
    """Sérialise un CountryReport en dict JSON-compatible."""
    d = asdict(report)
    return d


def yesterday() -> date:
    """Date de la veille (données de la veille, scrapées aujourd'hui)."""
    return date.today() - timedelta(days=1)
