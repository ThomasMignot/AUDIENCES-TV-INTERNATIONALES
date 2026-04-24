"""
Scraper France — Ozap / Puremédias

Source : https://www.ozap.com/tag/audiences_t14

Stratégie :
1. GET la page de tag "audiences" qui liste les articles récents
2. Identifier le dernier article "soirée" (format J+1, publié vers 9h) —
   on cherche un article dont le résumé commence par "Les audiences de la
   soirée du {jour} {date}" pour exclure les articles access 20h, pré-access,
   Netflix, radios, bilan saison, etc.
3. GET cet article, extraire le top 5 prime time
4. Format Ozap très stable : logo chaîne + TITRE + CATÉGORIE + X,X % + N téléspectateurs
5. Extraire la date de la soirée depuis le résumé (pas la date de publication)

France = pays de référence : on garde le TOP 5 strict, aucun seuil.
"""
from __future__ import annotations

import logging
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    AudienceEntry, CountryReport,
    color_for, save_report, make_entry,
)
from translations import translate


COUNTRY_CODE = "FR"
COUNTRY_NAME = "France"
FLAG = "🇫🇷"
SOURCE_NAME = "Ozap · Puremédias"
SOURCE_URL = "https://www.ozap.com/tag/audiences_t14"
LISTING_URL = "https://www.ozap.com/tag/audiences_t14"
BASE_URL = "https://www.ozap.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    # Pas d'Accept-Encoding explicite : on laisse requests/cloudscraper
    # ajouter automatiquement seulement les encodages qu'ils savent décoder
    # (sinon Ozap renvoie du Brotli non-décompressable et on reçoit des octets bruts)
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Mapping catégorie native Ozap → catégories internes du dashboard
# Ozap utilise : FILM, SERIE, MAGAZINE, JEU, TELEFILM, DOCUMENTAIRE,
#                HUMOUR, DIVERTISSEMENT, SPORT, JOURNAL TELEVISE, AUTRES
OZAP_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "FILM":              ("fiction", "🎬"),
    "SERIE":             ("fiction", "🎬"),
    "TELEFILM":          ("fiction", "🎬"),
    "MAGAZINE":          ("info", "📰"),
    "DOCUMENTAIRE":      ("info", "📰"),
    "JOURNAL TELEVISE":  ("info", "📰"),
    "INFORMATION":       ("info", "📰"),
    "JEU":               ("divertissement", "🎤"),
    "DIVERTISSEMENT":    ("divertissement", "🎤"),
    "HUMOUR":            ("divertissement", "🎤"),
    "TALK-SHOW":         ("divertissement", "🎤"),
    "TELE-REALITE":      ("divertissement", "🎤"),
    "MUSIQUE":           ("divertissement", "🎤"),
    "SPORT":             ("sport", "⚽"),
    "FOOTBALL":          ("sport", "⚽"),
    "AUTRES":            ("autre", "📺"),
}

MONTHS_FR: dict[str, int] = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

log = logging.getLogger("fr_ozap")


def strip_accents(s: str) -> str:
    """Retire les accents pour comparaison robuste."""
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _extract_link_title(a_tag) -> str:
    """
    Récupère le titre associé à un lien <a>. Plusieurs stratégies, dans l'ordre :
    1. Le texte direct du <a> (cas simple)
    2. Le texte d'un <h1>/<h2>/<h3> parent ou voisin
    3. L'attribut title= du lien
    4. Fallback : le slug de l'URL reformaté
    """
    # 1. Texte direct
    txt = a_tag.get_text(" ", strip=True)
    if txt and len(txt) > 5:
        return txt

    # 2. Chercher un heading dans l'arborescence proche
    for parent in a_tag.parents:
        if parent.name in ("article", "div", "section", "li"):
            heading = parent.find(["h1", "h2", "h3", "h4"])
            if heading:
                txt = heading.get_text(" ", strip=True)
                if txt and len(txt) > 5:
                    return txt
            # Ne pas remonter trop haut
            break

    # 3. Attribut title ou aria-label
    for attr in ("title", "aria-label"):
        val = a_tag.get(attr)
        if val and len(val) > 5:
            return val.strip()

    # 4. Fallback : slug de l'URL
    # .../actu/audiences-quel-score-pour-un-p-tit-truc-en-plus.../654519
    # → "audiences quel score pour un p tit truc en plus"
    href = a_tag.get("href", "")
    m = re.search(r"/actu/([^/]+?)(?:/\d+)?/?$", href)
    if m:
        slug = m.group(1).replace("-", " ")
        return slug

    return ""


def _list_audience_candidates(listing_soup: BeautifulSoup) -> list[dict]:
    """
    Collecte tous les articles 'Audiences' de la page de listing, en excluant
    les formats qui NE sont pas des récaps de prime-time (access 20h,
    pré-access, Netflix, radio, bilan de saison, SVOD, etc.).

    Retourne une liste ordonnée (plus récent en premier, puisque Ozap trie
    ses articles par date descendante).
    """
    candidates = []
    seen_urls = set()

    # Debug : combien de liens <a> au total sur la page ?
    all_links = listing_soup.find_all("a", href=True)
    audience_links = [a for a in all_links if re.search(r"/actu/audiences?[-/]", a.get("href", ""))]
    log.info(f"DEBUG: {len(all_links)} liens totaux, dont {len(audience_links)} vers /actu/audiences...")

    for a in audience_links:
        href = a["href"]
        if href.startswith("/"):
            href = BASE_URL + href
        if not href.startswith(BASE_URL):
            continue
        if href in seen_urls:
            continue

        # Extraction robuste du titre (avec fallback sur le slug d'URL)
        title = _extract_link_title(a)
        if not title:
            continue

        title_lower = strip_accents(title.lower())
        href_lower = href.lower()

        # EXCLUSIONS — articles qui ne sont PAS un récap de prime-time
        # On teste sur title ET href pour être robuste aux deux sources
        combined = f"{title_lower} {href_lower}"
        if "access-20h" in combined or "access 20h" in combined:
            continue
        if "pre-access" in combined or "pré-access" in title.lower():
            continue
        if "netflix" in combined:
            continue
        if "audiences-svod" in combined or " svod " in combined:
            continue
        if " radio" in combined or "-radio" in combined:
            continue
        if "bilan" in combined:
            continue
        if "top articles" in combined:
            continue

        # INCLUSION : le titre commence par "audiences" (avec ou sans deux-points)
        # OU l'URL suit le pattern /actu/audiences-...
        # Comme on a déjà filtré sur /actu/audiences/ plus haut, on garde tous
        # ceux qui ont passé les exclusions.
        seen_urls.add(href)
        candidates.append({"url": href, "title": title[:100]})

    return candidates


# Pattern qui identifie un vrai article de récap prime-time : le chapeau
# contient "Les audiences de la soirée du {jour} DD {mois} YYYY"
# (ou "journée" pour les samedis/dimanches où Ozap publie un récap global).
EVENING_CHAPO_PATTERN = re.compile(
    r"audiences? de la (soir[ée]e|journ[ée]e) du\s+[a-zéû]+\s+\d{1,2}\s+[a-zéèûô]+\s+\d{4}",
    re.IGNORECASE
)


def _is_evening_article(article_soup: BeautifulSoup) -> bool:
    """
    Vérifie que l'article contient bien le chapeau caractéristique
    d'un récap soirée ET qu'on y trouve des logos de chaînes (sanity check).
    """
    text = article_soup.get_text(" ", strip=True)
    if not EVENING_CHAPO_PATTERN.search(text):
        return False
    # Sanity check : au moins 3 logos de chaînes Ozap
    channel_imgs = article_soup.find_all("img", src=re.compile(r"/channels/\d+\."))
    return len(channel_imgs) >= 3


def find_evening_article_url(listing_soup: BeautifulSoup,
                              session: Optional[requests.Session] = None) -> Optional[tuple[str, BeautifulSoup]]:
    """
    Identifie l'article de récap soirée le plus récent.

    Stratégie robuste : on liste tous les candidats "Audiences : ..." non
    exclus, puis on les ouvre un par un (max 5) et on garde le premier qui
    contient le pattern caractéristique "Les audiences de la soirée du ...".

    Retourne (url, soup) pour éviter un re-fetch dans run().
    """
    candidates = _list_audience_candidates(listing_soup)
    log.info(f"{len(candidates)} candidats 'Audiences' après filtrage de base")

    if not candidates:
        return None

    sess = session or requests
    # On ne teste que les premiers candidats (les plus récents). Limite à 5
    # pour éviter de boucler si Ozap a changé son format.
    for cand in candidates[:5]:
        try:
            r = sess.get(cand["url"], headers=HEADERS, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            if _is_evening_article(soup):
                log.info(f"Article retenu : {cand['title']} → {cand['url']}")
                return cand["url"], soup
            else:
                log.info(f"Candidat écarté (pas un récap soirée) : {cand['title']}")
        except requests.RequestException as e:
            log.warning(f"Erreur en ouvrant {cand['url']}: {e}")
            continue

    return None


def extract_evening_date(article_soup: BeautifulSoup) -> Optional[date]:
    """
    Cherche 'soirée du {jour} DD {mois} YYYY' dans le résumé/chapeau de l'article.
    Fallback : extraire la date de publication et soustraire 1 jour.
    """
    text = article_soup.get_text(" ", strip=True)

    # Pattern 1 : "soirée du {jour} DD {mois} YYYY"
    m = re.search(
        r"soir[ée]e du [a-zéû]+\s+(\d{1,2})\s+([a-zéèûô]+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        day = int(m.group(1))
        month_name = strip_accents(m.group(2).lower())
        year = int(m.group(3))
        month = MONTHS_FR.get(month_name)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # Pattern 2 : "journée du {jour} DD {mois} YYYY" (cas samedi/dimanche)
    m = re.search(
        r"journ[ée]e du [a-zéû]+\s+(\d{1,2})\s+([a-zéèûô]+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        day = int(m.group(1))
        month_name = strip_accents(m.group(2).lower())
        year = int(m.group(3))
        month = MONTHS_FR.get(month_name)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # Pattern 3 : date de publication → on retire 1 jour
    m = re.search(
        r"Publi[ée] le (\d{1,2})\s+([a-zéèûô]+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        day = int(m.group(1))
        month_name = strip_accents(m.group(2).lower())
        year = int(m.group(3))
        month = MONTHS_FR.get(month_name)
        if month:
            try:
                from datetime import timedelta
                return date(year, month, day) - timedelta(days=1)
            except ValueError:
                pass

    log.warning("Date de la soirée non trouvée dans l'article")
    return None


def parse_viewers_fr(text: str) -> Optional[int]:
    """
    "5 501 000 téléspectateurs" → 5501000
    "552 000 téléspectateurs" → 552000
    """
    text = text.strip()
    m = re.search(r"([\d][\d\s\u00a0]*\d)", text)
    if not m:
        return None
    raw = m.group(1).replace("\u00a0", "").replace(" ", "")
    try:
        return int(raw)
    except ValueError:
        return None


def parse_share_fr(text: str) -> Optional[float]:
    """
    "32.5 %" → 32.5 · "32,5 %" → 32.5 · "32.5" → 32.5
    """
    m = re.search(r"([\d]+[.,]?\d*)\s*%?", text.strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def extract_channel_from_img(img_tag) -> Optional[str]:
    """
    Les logos chaînes ont un alt= ou sont dans un <img src=...channels/N.jpg>.
    On priorise l'attribut alt qui contient le nom en clair.
    """
    if img_tag is None:
        return None
    alt = img_tag.get("alt", "").strip()
    if alt and alt not in ("", "commercial_link", "puremedias", "player2", "Webedia"):
        return alt
    # Fallback : analyser le src (moins fiable)
    src = img_tag.get("src", "")
    channel_id_match = re.search(r"/channels/(\d+)\.", src)
    if channel_id_match:
        # Mapping id → nom (depuis ce qu'on a vu sur la page)
        id_to_name = {
            "1": "TF1", "2": "France 2", "3": "France 3", "4": "Canal+",
            "6": "M6", "13": "TMC", "43": "TFX", "336": "W9",
            "499": "CSTAR", "532": "Gulli", "533": "Arte",
            "534": "France 5", "723": "TF1 Series Film",
            "725": "6ter", "726": "RMC Story", "727": "RMC Découverte",
            "728": "RMC Life",
        }
        return id_to_name.get(channel_id_match.group(1))
    return None


def _split_title_and_category(raw_title: str) -> tuple[str, Optional[str]]:
    """
    Détache la catégorie collée à la fin d'un titre.

    Ex:
      "UN P'TIT TRUC EN PLUS FILM" → ("UN P'TIT TRUC EN PLUS", "FILM")
      "FLASHBACK SERIE"           → ("FLASHBACK", "SERIE")
      "TROPIQUES CRIMINELS"       → ("TROPIQUES CRIMINELS", None)
      "DESTRUCTION DE POMPEI : SCENARIO D'UNE APOCALYPSE DOCUMENTAIRE"
                                  → ("DESTRUCTION DE POMPEI : SCENARIO D'UNE APOCALYPSE", "DOCUMENTAIRE")

    On cherche le suffixe dans l'ensemble des catégories Ozap connues.
    Priorise les suffixes les plus longs (DOCUMENTAIRE avant DOC...).
    """
    if not raw_title:
        return raw_title, None

    stripped = raw_title.strip()
    # Teste les catégories par longueur décroissante pour éviter qu'une
    # catégorie courte (JEU) capture prématurément un cas qui termine par
    # une catégorie plus longue (TELEJEU si ça existait).
    sorted_categories = sorted(OZAP_CATEGORY_MAP.keys(), key=len, reverse=True)

    upper = stripped.upper()
    for cat in sorted_categories:
        # Match strict : la catégorie doit être en fin, précédée d'un espace
        # (pour ne pas couper un vrai mot qui se terminerait par "FILM", etc.)
        suffix = " " + cat
        if upper.endswith(suffix) and len(stripped) > len(suffix):
            new_title = stripped[: -len(suffix)].strip()
            # Garde le titre intact (casse d'origine)
            return new_title, cat

    return stripped, None


def parse_top_programs(article_soup: BeautifulSoup, source_url: str) -> list[dict]:
    """
    Parse le top des programmes depuis un article Ozap.

    Structure HTML observée (répétée pour chaque programme) :
      <img alt="{ChaîneName}" src=".../channels/N.jpg">
      TITRE DU PROGRAMME (souvent en MAJUSCULES)
      CATEGORIE (FILM, SERIE, MAGAZINE, JEU, TELEFILM, ...)
      X.X %   (ou X,X %)
      NNN NNN téléspectateurs

    Les entrées apparaissent par ordre décroissant de PDM.
    On itère sur toutes les <img> dont le src contient /channels/ et on
    parse les 4 lignes de texte qui suivent dans l'ordre du document.
    """
    programs = []

    # Stratégie : trouver chaque <img> de chaîne, puis prendre le texte
    # suivant dans le flux du document. On travaille avec la liste ordonnée
    # des éléments texte/img pour respecter l'ordre d'apparition.
    #
    # On cherche toutes les img channel logos
    channel_imgs = article_soup.find_all("img", src=re.compile(r"/channels/\d+\."))

    for img in channel_imgs:
        channel = extract_channel_from_img(img)
        if not channel:
            continue

        # Trouver les 4 textes suivants (titre, catégorie, %, téléspectateurs)
        # en parcourant les éléments suivants dans l'ordre du DOM.
        texts_after = []
        current = img
        # Remonter au parent pour chercher les nœuds suivants
        # Parcours en ordre DFS à partir du parent immédiat
        parent = img.parent
        if parent is None:
            continue

        # On collecte les textes apparaissant APRÈS cette image et AVANT
        # la prochaine image channel (ou avant la fin du document).
        next_imgs_channels = channel_imgs[channel_imgs.index(img) + 1:]
        next_channel_img = next_imgs_channels[0] if next_imgs_channels else None

        # Parcourir tous les éléments suivants jusqu'à la prochaine img channel
        for sibling in img.find_all_next():
            if sibling is next_channel_img:
                break
            if sibling.name == "img" and sibling.get("src", "").find("/channels/") != -1:
                break  # sécurité double
            text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
            if not text:
                continue
            # On ne veut que les textes "feuilles" (pas les conteneurs englobants)
            # Heuristique : on prend les <p>, <div> sans enfant bloquant, <span> atomiques
            # Simplement : on prend les lignes de texte dédupliquées
            # En pratique on regarde les NavigableString ou les éléments text-only
            if sibling.name in ("p", "div", "span") and sibling.find(["p", "div", "table"]) is None:
                text_clean = sibling.get_text(" ", strip=True)
                if text_clean and text_clean not in [t for t in texts_after]:
                    texts_after.append(text_clean)
                    if len(texts_after) >= 6:  # marge de sécurité
                        break

        if len(texts_after) < 4:
            continue

        # Maintenant, on identifie les 4 champs dans les textes récoltés :
        # - Titre : première ligne (souvent en majuscules, non vide)
        # - Catégorie : ligne courte en majuscules unique (FILM, SERIE, etc.)
        # - PDM : contient "%"
        # - Téléspectateurs : contient "téléspectateurs" ou "téléspectateur"
        title = None
        category_raw = None
        share_val = None
        viewers_val = None

        for t in texts_after:
            t_stripped = t.strip()
            if not t_stripped:
                continue
            # Téléspectateurs
            if viewers_val is None and ("téléspectateur" in t_stripped.lower() or "telespectateur" in strip_accents(t_stripped.lower())):
                viewers_val = parse_viewers_fr(t_stripped)
                continue
            # PDM
            if share_val is None and "%" in t_stripped and len(t_stripped) < 15:
                share_val = parse_share_fr(t_stripped)
                continue
            # Catégorie : ligne courte, en majuscules, connue
            up = t_stripped.upper()
            if category_raw is None and up in OZAP_CATEGORY_MAP and len(t_stripped) < 30:
                category_raw = up
                continue
            # Titre : première ligne non-attrapée, longueur raisonnable, contient des lettres
            if title is None and len(t_stripped) >= 2 and len(t_stripped) < 200 and re.search(r"[A-Za-zÀ-ÿ]", t_stripped):
                # Exclure les lignes trivialement non-titres
                if "téléspectateur" in t_stripped.lower():
                    continue
                if t_stripped.lower() in ("médiamétrie", "medialimetrie"):
                    continue
                title = t_stripped
                continue

        if not title or viewers_val is None or share_val is None:
            log.debug(f"Programme incomplet pour {channel}: title={title}, viewers={viewers_val}, share={share_val}")
            continue

        # Si la catégorie est collée à la fin du titre (cas fréquent quand Ozap
        # utilise une seule balise pour titre+catégorie), on la détache.
        # Ex: "UN P'TIT TRUC EN PLUS FILM" → title="UN P'TIT TRUC EN PLUS", category="FILM"
        title, extracted_category = _split_title_and_category(title)
        if extracted_category and category_raw is None:
            category_raw = extracted_category
        elif extracted_category and category_raw != extracted_category:
            # Le titre avait une catégorie ET on en a trouvé une séparée : on
            # préfère celle séparée (plus fiable), mais on a quand même nettoyé
            # le titre, donc c'est tout bon.
            pass

        # Catégorie par défaut si Ozap ne donne rien de reconnu
        if category_raw is None:
            category_raw = "AUTRES"

        programs.append({
            "channel": channel,
            "program": title,
            "category_raw": category_raw,
            "viewers": viewers_val,
            "share": share_val,
        })

    # Dédupliquer par (channel, program) au cas où
    seen = set()
    deduped = []
    for p in programs:
        key = (p["channel"], p["program"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    log.info(f"Programmes parsés : {len(deduped)}")
    return deduped


def make_entry_fr(rank: int, channel: str, program: str, viewers: int,
                   share: float, source_url: str, category_raw: str) -> AudienceEntry:
    """
    Version FR de make_entry : on utilise la catégorie native Ozap
    plutôt que de laisser categories.py deviner.
    """
    category, emoji = OZAP_CATEGORY_MAP.get(category_raw.upper(), ("autre", "📺"))
    program_fr = translate(program)
    return AudienceEntry(
        rank=rank,
        channel=channel,
        channel_color=color_for(channel),
        program=program,
        program_fr=program_fr,
        viewers=viewers,
        share=share,
        source_url=source_url,
        category=category,
        category_emoji=emoji,
    )


def _looks_like_html(text: str) -> bool:
    """
    Vérifie qu'une réponse ressemble à du HTML lisible. Si la réponse est
    compressée et que l'auto-décompression a échoué, on va recevoir une
    chaîne de bytes corrompus que .text mappe en caractères étranges.
    """
    if len(text) < 200:
        return False
    # On cherche au moins UN marqueur HTML classique dans les 2000 premiers chars
    sample = text[:2000].lower()
    markers = ("<html", "<!doctype", "<head", "<body", "<a ", "<div", "<meta")
    return any(m in sample for m in markers)


def _try_decompress(raw_bytes: bytes) -> str:
    """
    Tente de décompresser des bytes bruts (brotli, gzip, deflate) en HTML UTF-8.
    Retourne le HTML décodé, ou une chaîne vide si rien ne marche.
    """
    # Brotli
    try:
        import brotli  # type: ignore
        decoded = brotli.decompress(raw_bytes).decode("utf-8", errors="replace")
        if _looks_like_html(decoded):
            log.info("Décompression brotli réussie")
            return decoded
    except Exception as e:
        log.debug(f"Brotli: {e}")

    # gzip
    try:
        import gzip
        decoded = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
        if _looks_like_html(decoded):
            log.info("Décompression gzip réussie")
            return decoded
    except Exception as e:
        log.debug(f"Gzip: {e}")

    # deflate (zlib)
    try:
        import zlib
        decoded = zlib.decompress(raw_bytes).decode("utf-8", errors="replace")
        if _looks_like_html(decoded):
            log.info("Décompression deflate réussie")
            return decoded
    except Exception as e:
        log.debug(f"Deflate: {e}")

    log.warning("Aucune décompression n'a fonctionné, HTML inutilisable")
    return ""


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} ===")

    try:
        # cloudscraper contourne les protections anti-bot (Cloudflare, DataDome...)
        # que Webedia applique sur Ozap. Fallback sur requests si non installé.
        if HAS_CLOUDSCRAPER:
            session = cloudscraper.create_scraper(
                browser={
                    "browser": "chrome",
                    "platform": "darwin",
                    "desktop": True,
                }
            )
            log.info("Using cloudscraper")
        else:
            session = requests.Session()
            log.warning("cloudscraper non disponible, fallback sur requests (risque de blocage)")
        session.headers.update(HEADERS)

        # 1. Récupérer la page de listing
        r = session.get(LISTING_URL, timeout=30)
        r.raise_for_status()
        log.info(f"DEBUG: listing HTTP {r.status_code}, {len(r.text)} chars, "
                 f"content-type={r.headers.get('content-type', 'n/a')}, "
                 f"encoding={r.headers.get('content-encoding', 'none')}")

        # Sanity check : la réponse doit contenir du HTML lisible
        html = r.text
        if not _looks_like_html(html):
            log.warning("Réponse non-HTML détectée, tentative de décompression manuelle...")
            html = _try_decompress(r.content)
            log.info(f"DEBUG: après décompression : {len(html)} chars")

        listing_soup = BeautifulSoup(html, "html.parser")

        # 2. Identifier le bon article (et récupérer son contenu en même temps)
        result = find_evening_article_url(listing_soup, session=session)
        if not result:
            # Dump les premiers caractères du HTML brut pour diagnostic
            preview = r.text[:1500].replace("\n", " ")
            log.warning(f"DEBUG: aperçu HTML reçu : {preview!r}")
            raise RuntimeError("Aucun article 'soirée' trouvé sur la page de listing")
        article_url, article_soup = result

        # 3. Extraire la date de la soirée
        evening_date = extract_evening_date(article_soup) or date.today()
        log.info(f"Date de la soirée : {evening_date}")

        # 4. Parser les programmes
        programs = parse_top_programs(article_soup, article_url)
        if not programs:
            raise RuntimeError("Aucun programme extrait de l'article")

        # 5. Trier par téléspectateurs décroissant (sécurité — l'ordre DOM
        #    devrait déjà être correct puisque Ozap trie par PDM)
        programs.sort(key=lambda p: p["viewers"], reverse=True)

        # 6. Top 5 strict — France = pays de référence, pas de seuil
        top5 = programs[:5]

        entries = [
            make_entry_fr(
                rank=i + 1,
                channel=p["channel"],
                program=p["program"],
                viewers=p["viewers"],
                share=p["share"],
                source_url=article_url,
                category_raw=p["category_raw"],
            )
            for i, p in enumerate(top5)
        ]

        log.info(f"Top 5 retenu : {[(e.channel, e.program, e.viewers) for e in entries]}")

        status = "ok" if len(entries) == 5 else "partial"

        return CountryReport(
            country_code=COUNTRY_CODE, country_name=COUNTRY_NAME, flag=FLAG,
            date=evening_date.isoformat(),
            source_name=SOURCE_NAME, source_url=article_url,
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
