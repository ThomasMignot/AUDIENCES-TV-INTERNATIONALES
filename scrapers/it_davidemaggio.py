"""
Scraper Italie — Davide Maggio (v2 — bloc structuré en priorité)

Source : https://www.davidemaggio.it/ascolti-tv
Publie chaque matin les audiences de la veille (parfois J-2 selon AGF).

Stratégie v2 :
1. Aller sur la page d'index /ascolti-tv
2. Identifier le lien vers l'article du dernier jour publié (pas le "Total Audience")
3. Lire cet article
4. PARSER EN PRIORITÉ le bloc structuré "I dati dei programmi di prima serata"
   qui liste 8-10 programmes avec logo de chaîne + nom + viewers + share dans
   un format ultra-clair. Avant on ratait des entrées parce qu'on parsait le
   paragraphe prose qui est fragile.
5. FALLBACK : si le bloc structuré n'est pas trouvé, on retombe sur le
   paragraphe prose (méthode v1).
6. Tri par viewers, top 5.
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
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
    # Logos URL → chaîne (pour le bloc structuré qui utilise les images)
    "rai-1": "Rai 1", "rai-2": "Rai 2", "rai-3": "Rai 3", "rai-4": "Rai 4",
    "canale-5": "Canale 5", "italia-1": "Italia 1", "rete-4": "Rete 4",
    "la-7": "La7", "tv8-logo": "TV8", "tv8-logo-1": "TV8", "tv8": "TV8",
    "nove-1": "Nove",
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
        if "total-audience" in href.lower():
            continue
        m = re.search(
            r"/ascolti-tv/ascolti-tv-(\w+)-(\d{1,2})-(\w+)-(\d{4})",
            href, re.IGNORECASE,
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
    cleaned = re.sub(r"^(su|sul|sulla|sulle)\s+", "", cleaned)
    return CHANNEL_NORMALIZE.get(cleaned)


def channel_from_logo_url(img_src: str) -> Optional[str]:
    """
    Devine la chaîne depuis l'URL du logo de l'image.
    Ex: 'Rai-1-150x150.png' → 'Rai 1', 'Canale-5-150x150.png' → 'Canale 5',
        'tv8-logo-1-150x150.jpeg' → 'TV8'
    """
    if not img_src:
        return None
    # Extraire le nom de fichier
    fname = img_src.rsplit("/", 1)[-1].lower()
    fname = re.sub(r"-?\d+x\d+", "", fname)  # enlever les dimensions
    fname = re.sub(r"\.(png|jpg|jpeg|webp|svg|avif)$", "", fname)  # enlever ext
    fname = fname.rstrip("-_ ")

    # Match exact d'abord
    if fname in CHANNEL_NORMALIZE:
        return CHANNEL_NORMALIZE[fname]
    # Sinon, on cherche si le filename commence par une clé connue
    # (ex: "tv8-logo-1" matche "tv8")
    for key, channel in CHANNEL_NORMALIZE.items():
        # On veut que la clé soit un préfixe complet (suivi d'un séparateur)
        if fname == key or fname.startswith(key + "-") or fname.startswith(key + "_"):
            return channel
    return None


def parse_italian_number(num_str: str) -> int:
    """ "2.741.000" → 2741000 (le point = séparateur de milliers en italien) """
    cleaned = num_str.replace(".", "").replace(",", "")
    return int(cleaned)


def parse_share(raw: str) -> float:
    """ "20.7%" → 20.7 · "20,7%" → 20.7 · "3%" → 3.0 """
    cleaned = raw.strip().rstrip("%").strip().replace(",", ".")
    return float(cleaned)


# ─── Stratégie 1 : bloc structuré "I dati dei programmi di prima serata" ──

def parse_structured_block(soup: BeautifulSoup) -> list[dict]:
    """
    Cherche le bloc avec <h6>I dati dei programmi di prima serata</h6>
    et extrait les 8-10 programmes qu'il contient.

    Format type :
        <h6>I dati dei programmi di prima serata</h6>
        <ul>
          <li>
            <img src=".../Rai-1-150x150.png">
            <h6>Roberta Valente</h6>
            <p>3.136.000</p>
            <p>20.7%</p>
          </li>
          ...
        </ul>

    Le HTML peut varier : <li>, <div>, structure flat... On essaie d'être tolérant.
    Stratégie : pour chaque "card" trouvée, on récupère img+titre+chiffres.
    """
    rows = []

    # Trouver le heading "I dati dei programmi di prima serata"
    target_heading = None
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = h.get_text(strip=True).lower()
        if "dati dei programmi di prima serata" in text:
            target_heading = h
            break

    if target_heading is None:
        log.info("Bloc structuré 'I dati dei programmi di prima serata' non trouvé")
        return []

    # Récupérer le conteneur qui suit le heading.
    # Le bloc est typiquement un <ul> ou un <div> qui suit immédiatement.
    # Heuristique : on cherche l'élément suivant qui contient des images.
    container = target_heading.find_next(["ul", "ol", "div", "section"])
    if container is None:
        log.info("Bloc structuré : aucun conteneur trouvé après le heading")
        return []

    # On itère sur les "items" (li, div...) qui contiennent une image + un texte
    # Approche tolérante : on cherche tous les <img> dans le conteneur, et pour
    # chacun on remonte/descend pour trouver les infos associées.
    items_found = 0
    for img in container.find_all("img"):
        img_src = img.get("src", "") or img.get("data-src", "")
        channel = channel_from_logo_url(img_src)
        if channel is None:
            continue

        # Trouver l'item parent qui contient cette image (li, div, article...)
        # On remonte jusqu'à un parent direct du conteneur principal
        item = img
        for _ in range(6):
            if item.parent is None or item.parent == container:
                break
            item = item.parent
            # Si on est dans un <li> ou un <div> isolé, on s'arrête
            if item.name in ("li", "article"):
                break

        # Extraire le texte de cet item
        item_text = item.get_text(" ", strip=True)
        if not item_text or len(item_text) < 5:
            continue

        # Chercher le nom du programme : c'est le 1er h6/strong qui n'est pas
        # un nombre ou un %. On peut aussi prendre la 1re ligne textuelle.
        program = None
        for h in item.find_all(["h6", "h5", "h4", "h3", "strong", "b"]):
            t = h.get_text(strip=True)
            if not t:
                continue
            # Exclure les chiffres/pourcentages
            if re.fullmatch(r"[\d.,%\s]+", t):
                continue
            program = t
            break
        if program is None:
            # Fallback : prendre la 1re ligne du texte qui ressemble à un titre
            lines = [l.strip() for l in item_text.split("\n") if l.strip()]
            for line in lines:
                if not re.fullmatch(r"[\d.,%\s]+", line) and len(line) > 2 and len(line) < 80:
                    program = line
                    break

        if not program:
            continue

        # Extraire viewers (nombre formaté X.XXX.XXX) et share (X.X%)
        # On cherche dans le texte de l'item
        viewers_match = re.search(r"\b(\d{1,3}(?:\.\d{3})+)\b", item_text)
        share_match = re.search(r"(\d{1,2}(?:[,.]\d{1,2})?)\s*%", item_text)

        if not viewers_match or not share_match:
            log.debug(f"  Skip item (chiffres manquants) : channel={channel}, program={program!r}")
            continue

        try:
            viewers = parse_italian_number(viewers_match.group(1))
            share = parse_share(share_match.group(1))
        except (ValueError, IndexError):
            continue

        # Filtre de cohérence : viewers doit être au moins 50k pour le prime
        # (sinon c'est probablement du bruit)
        if viewers < 50000:
            log.debug(f"  Skip item (viewers {viewers} trop faible) : {program}")
            continue

        # Évite les doublons : si on a déjà cette combinaison channel+program, on skip
        if any(r["channel"] == channel and r["program"].lower() == program.lower()
               for r in rows):
            continue

        rows.append({
            "channel": channel,
            "program": program,
            "viewers": viewers,
            "share": share,
        })
        items_found += 1

    log.info(f"Bloc structuré : {items_found} items extraits")
    return rows


# ─── Stratégie 2 : paragraphe prose (fallback) ──

def parse_intro_paragraph(soup: BeautifulSoup) -> list[dict]:
    """
    Méthode v1 (fallback) : parse le paragraphe prose qui décrit les programmes
    prime time avec le pattern "Su [chaîne] [programme] [verbe] X.XXX.XXX spettatori".
    """
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
            channel = normalize_channel(m.group("channel"))
            if channel is None:
                continue
            program = m.group("program").strip()
            program = re.sub(r"\s*[-–—]\s*$", "", program).strip()
            program = program.strip("*").strip()
            if len(program) > 80:
                program = re.split(r"\s[-–—]\s", program)[0].strip()
            viewers = parse_italian_number(m.group("viewers"))
            share = parse_share(m.group("share"))
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
    log.info(f"=== Scraping {COUNTRY_NAME} (v2) ===")

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

        # 3) STRATÉGIE 1 : parser le bloc structuré (8-10 programmes garantis)
        rows = parse_structured_block(article_soup)

        # 4) STRATÉGIE 2 (fallback) : si le bloc structuré n'a pas marché
        # ou a donné moins de 5 entrées, on complète avec le paragraphe prose
        if len(rows) < 5:
            log.info(f"Bloc structuré : {len(rows)} entrées, complément par paragraphe prose")
            prose_rows = parse_intro_paragraph(article_soup)
            # Merger en évitant les doublons (même chaîne + même programme)
            existing_keys = {(r["channel"], r["program"].lower()) for r in rows}
            for pr in prose_rows:
                key = (pr["channel"], pr["program"].lower())
                if key not in existing_keys:
                    rows.append(pr)
                    existing_keys.add(key)
            log.info(f"Après merge : {len(rows)} entrées")

        if not rows:
            raise RuntimeError("Aucune entrée extraite (ni bloc structuré, ni paragraphe)")

        # 5) Déduplication par chaîne (garder la plus grosse audience)
        top_by_channel: dict[str, dict] = {}
        for row in rows:
            ch = row["channel"]
            if ch not in top_by_channel or row["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = row

        # 6) Top 5 par viewers
        ranked = sorted(top_by_channel.values(), key=lambda x: x["viewers"], reverse=True)[:5]
        if not ranked:
            raise RuntimeError("Après dédup, aucune entrée")

        log.info(f"Top 5 retenu : {[(r['channel'], r['program'], r['viewers']) for r in ranked]}")

        entries = [
            make_entry(
                rank=i + 1,
                channel=r["channel"],
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
        # Fallback de date : hier (cohérent avec les autres scrapers, évite
        # les archives futures en cas de plantage)
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
