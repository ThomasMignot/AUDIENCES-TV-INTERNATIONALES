"""
Scraper Pays-Bas — Televizier.nl (v3 — parsing renforcé)

Source : https://www.televizier.nl/kijkcijfers
Chaque matin (~7h-11h NL, y compris weekend), Televizier publie un article
"De TV van gisteren" qui commente 2-4 programmes du prime time de la veille
avec leurs téléspectateurs.

Stratégie v3 :
1. Page index : on liste tous les articles "kijkcijfers" et on prend celui
   avec la date la plus récente extraite de son titre/breadcrumb
   (ne pas se fier à l'ordre du DOM qui inclut sidebars et anciens articles).
2. Article : on parse en deux temps :
   - Sections par <h2> = noms de programmes (filtres permissifs)
   - Pour chaque section, on cherche viewers et chaîne dans le texte qui suit
   - On collecte AUSSI le chiffre potentiellement présent dans l'intro
     (avant le premier <h2>) qui correspond souvent au programme du h2 #1.

Limites connues :
- Pas de PDM (part de marché) → on met 0.0
- 2-4 programmes par jour seulement → status "partial"
- Format prose : changements possibles → on log abondamment pour diagnostiquer
"""
from __future__ import annotations

import logging
import re
import sys
import unicodedata
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


COUNTRY_CODE = "NL"
COUNTRY_NAME = "Pays-Bas"
FLAG = "🇳🇱"
SOURCE_NAME = "Televizier · De TV van gisteren"
SOURCE_URL = "https://www.televizier.nl/kijkcijfers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.5",
    # Note : pas d'Accept-Encoding explicite pour laisser requests gérer
    # la décompression automatiquement (cf. fix similaire dans fr_ozap.py)
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

MONTHS_NL = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

DAYS_NL = "(?:maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)"

# Chaînes reconnues dans le texte des articles
CHANNELS = {
    "NPO 1": "NPO 1", "NPO1": "NPO 1",
    "NPO 2": "NPO 2", "NPO2": "NPO 2",
    "NPO 3": "NPO 3", "NPO3": "NPO 3",
    "RTL 4": "RTL 4", "RTL4": "RTL 4",
    "RTL 5": "RTL 5", "RTL5": "RTL 5",
    "RTL 8": "RTL 8", "RTL8": "RTL 8",
    "SBS 6": "SBS 6", "SBS6": "SBS 6",
    "SBS 9": "SBS 9", "SBS9": "SBS 9",
    "Net 5": "Net 5", "Net5": "Net 5",
    "Veronica": "Veronica",
}

log = logging.getLogger("nl_televizier")


def list_kijkcijfers_articles(soup: BeautifulSoup) -> list[dict]:
    """
    Liste tous les liens vers des articles 'kijkcijfers' depuis la page index.
    Pour chacun, on essaie d'extraire une date depuis le contexte autour du lien
    (texte type "Kijkcijfers zondag 26 april 2026" en label de la liste).

    Retourne une liste de dicts {url, date_hint, position} dans l'ordre du DOM.
    """
    articles = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/kijkcijfers/" not in href:
            continue
        # Filtrer les pages d'index
        if re.search(r"/kijkcijfers/?$", href):
            continue
        if re.search(r"/kijkcijfers/\d+/?$", href):
            continue
        # Éviter les liens vers les tags
        if "/tag/" in href:
            continue

        full_url = href if href.startswith("http") else f"https://www.televizier.nl{href}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Chercher un indice de date dans le texte autour du lien
        # (sur la page index, le label "Kijkcijfers zondag 26 april 2026" précède
        # ou accompagne le titre du lien)
        date_hint = None
        # On regarde le parent et ses enfants directs
        for ancestor in [a.parent, a.parent.parent if a.parent else None]:
            if ancestor is None:
                continue
            txt = ancestor.get_text(" ", strip=True)
            d = _extract_date_from_text(txt)
            if d:
                date_hint = d
                break
        # Fallback : voir si la date est dans le href
        if date_hint is None:
            d = _extract_date_from_text(href.replace("-", " "))
            if d:
                date_hint = d

        articles.append({
            "url": full_url,
            "date_hint": date_hint,
            "title": a.get_text(" ", strip=True)[:100],
        })

    log.info(f"DEBUG: {len(articles)} articles 'kijkcijfers' candidats listés")
    return articles


def _extract_date_from_text(text: str) -> Optional[date]:
    """Cherche un pattern date dutch dans un texte arbitraire."""
    if not text:
        return None
    # Format complet : "vrijdag 24 april 2026" ou "24 april 2026"
    m = re.search(
        rf"(?:{DAYS_NL}\s+)?(\d{{1,2}})\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\s+(\d{{4}})",
        text,
        re.IGNORECASE,
    )
    if not m:
        # Format avec le mois sans année (rare, ex: "zondag 26 april")
        m = re.search(
            rf"(?:{DAYS_NL}\s+)?(\d{{1,2}})\s+(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\b",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None
        # Pas d'année → on suppose l'année courante
        try:
            return date(date.today().year, MONTHS_NL[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            return None
    try:
        return date(int(m.group(3)), MONTHS_NL[m.group(2).lower()], int(m.group(1)))
    except (ValueError, KeyError):
        return None


def pick_best_article(articles: list[dict]) -> Optional[dict]:
    """
    Choisit l'article le plus récent en se basant sur date_hint.
    En cas d'égalité (ou pas de hint), prend le premier dans l'ordre du DOM
    (qui est généralement chronologiquement décroissant sur Televizier).
    """
    if not articles:
        return None

    # Articles avec date connue
    dated = [a for a in articles if a["date_hint"] is not None]
    if dated:
        # On prend la date la plus récente, mais on s'assure qu'elle n'est
        # pas trop dans le futur (sécurité : pas plus tard qu'aujourd'hui+1)
        max_acceptable = date.today() + timedelta(days=1)
        valid = [a for a in dated if a["date_hint"] <= max_acceptable]
        if valid:
            best = max(valid, key=lambda a: a["date_hint"])
            log.info(f"Article le plus récent (par date) : {best['date_hint']} → {best['url']}")
            return best

    # Fallback : le premier dans l'ordre du DOM
    log.info(f"Aucune date hint, fallback sur le premier article : {articles[0]['url']}")
    return articles[0]


def extract_date_from_article(soup: BeautifulSoup) -> Optional[date]:
    """
    Dans l'article, cherche le texte 'Kijkcijfers [jour] DD [mois] [YYYY]'
    qui indique la date de DIFFUSION (et pas de publication).
    """
    full_text = soup.get_text(" ", strip=True)
    # Pattern complet avec "Kijkcijfers" en préfixe
    m = re.search(
        rf"Kijkcijfers\s+(?:{DAYS_NL}\s+)?(\d{{1,2}})\s+"
        r"(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)"
        r"\s+(\d{4})",
        full_text,
        re.IGNORECASE,
    )
    if m:
        try:
            return date(int(m.group(3)), MONTHS_NL[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            pass
    # Fallback : chercher juste une date dutch dans les 500 premiers chars
    return _extract_date_from_text(full_text[:500])


# ─── Parsing programmes ────────────────────────────────────────────

# Pattern qui matche un nombre de téléspectateurs dutch.
# Formats : "845.000 kijkers" / "1.013.000 kijkers" / "bijna 700.000 kijkers"
# / "1,3 miljoen kijkers" / "1 miljoen kijkers"
VIEWERS_PATTERN = re.compile(
    r"(?:(\d{1,3}(?:\.\d{3})+)|(\d+(?:[,.]\d+)?)\s*miljoen)"
    r"\s*(?:kijkers|mensen|keken|stemmen)?",
    re.IGNORECASE,
)


def _parse_viewers_match(match) -> Optional[int]:
    """Convertit un match VIEWERS_PATTERN en int."""
    if match.group(1):  # format "X.XXX.XXX"
        return int(match.group(1).replace(".", ""))
    if match.group(2):  # format "X,X miljoen"
        return int(float(match.group(2).replace(",", ".")) * 1_000_000)
    return None


def find_channel_in_text(text: str) -> Optional[str]:
    """Cherche un nom de chaîne dans un fragment de texte."""
    for needle in sorted(CHANNELS.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(needle)}\b", text, re.IGNORECASE):
            return CHANNELS[needle]
    return None


def find_first_viewers(text: str) -> Optional[int]:
    """Cherche le premier nombre de téléspectateurs dans un texte."""
    m = VIEWERS_PATTERN.search(text)
    if m:
        # Ne renvoyer que si suivi d'un mot clé "kijkers/mensen/keken"
        # ou si c'est un nombre clairement formaté en milliers (X.XXX.XXX)
        whole = m.group(0).lower()
        if any(kw in whole for kw in ("kijker", "mens", "kijken", "kijken")):
            return _parse_viewers_match(m)
        # Nombre formaté en milliers (X.XXX.XXX) → probablement viewers
        if m.group(1) and len(m.group(1).replace(".", "")) >= 6:
            return _parse_viewers_match(m)
    # Fallback explicite : chercher uniquement les "X.XXX.XXX kijkers"
    m = re.search(
        r"(\d{1,3}(?:\.\d{3})+)\s+(?:kijkers|mensen|keken)",
        text, re.IGNORECASE,
    )
    if m:
        return int(m.group(1).replace(".", ""))
    # Fallback : "bijna XXX.XXX kijkers"
    m = re.search(
        r"(\d{1,3}(?:\.\d{3})+)\s+(?:kijkers|mensen)",
        text, re.IGNORECASE,
    )
    if m:
        return int(m.group(1).replace(".", ""))
    return None


def is_program_heading(title: str) -> bool:
    """
    Heuristique : un h2/h3 désigne-t-il vraiment un programme ?

    On accepte les titres courts, sans ponctuation forte de phrase
    (?, !, : sauf en début), et qui ne sont pas dans la liste noire.
    """
    if not title or len(title) < 3:
        return False
    if len(title) > 80:
        return False
    if len(title.split()) > 10:
        return False

    # Liste noire des titres récurrents qui ne sont jamais des programmes
    BLACKLIST = {
        "televizier.nl", "stem nu hier op de",
        "gouden televizier-ring 2026", "gouden televizier-ring",
        "meer over", "meer nieuws voor jou", "laatste nieuws",
        "de tv van gisteren", "pak je kans",
        "spannend", "spannend!", "chaos",
        "kijkcijfers", "service", "abonneren",
        "stem nu", "ring", "winnen", "kijktips",
        "tv-nieuws", "home", "nieuws",
    }
    lower = title.lower().strip().rstrip(":!?.,")
    if lower in BLACKLIST:
        return False
    if lower.startswith("kijkcijfers "):
        return False
    if lower.startswith("de tv van gisteren"):
        return False
    if lower.startswith("tussenstand "):
        return False
    if lower.startswith("terugkijken "):
        return False
    if lower.startswith("eerste beelden"):
        return False

    # Si le titre contient ":" en milieu (= sous-titre éditorial type
    # "De TV van gisteren: kijkers zien..."), on rejette.
    # Mais on accepte ":" en fin (rare mais possible).
    if ":" in title and not title.rstrip().endswith(":"):
        return False
    # Un point d'interrogation ou exclamation = teaser, pas programme.
    if "?" in title or "!" in title:
        return False

    return True


def parse_article(soup: BeautifulSoup, article_url: str) -> list[dict]:
    """
    Extrait les programmes d'un article. Stratégie :

    1. Récupérer toutes les sections "programme" délimitées par les <h2>/<h3>
       passant le filtre `is_program_heading`.
    2. Pour chaque section, collecter le texte des paragraphes jusqu'au prochain
       heading. Y chercher viewers et chaîne.
    3. Pour le PREMIER programme (h2 #1), inclure aussi le texte d'intro
       (avant le premier h2) — c'est souvent là que sont mentionnés les
       chiffres du programme principal.
    """
    rows = []

    # Récupérer le texte d'intro (avant le 1er heading "programme")
    first_program_h = None
    for h in soup.find_all(["h2", "h3"]):
        if is_program_heading(h.get_text(" ", strip=True)):
            first_program_h = h
            break

    intro_text = ""
    if first_program_h is not None:
        # Tous les <p> avant le 1er h2-programme
        for p in soup.find_all("p"):
            if p.find_next(["h2", "h3"]) is None:
                continue
            # Vérifier que ce <p> est avant first_program_h dans le DOM
            # (en parcourant les éléments suivants depuis l'intro)
            try:
                if first_program_h in list(p.find_all_next(["h2", "h3"])):
                    intro_text += " " + p.get_text(" ", strip=True)
            except Exception:
                pass

    log.info(f"DEBUG: intro de {len(intro_text)} chars, "
             f"premier prog = {first_program_h.get_text(' ', strip=True)[:50] if first_program_h else None!r}")

    # Identifier toutes les sections programme
    program_headings = [
        h for h in soup.find_all(["h2", "h3"])
        if is_program_heading(h.get_text(" ", strip=True))
    ]
    log.info(f"DEBUG: {len(program_headings)} h2/h3 retenus comme programmes : "
             f"{[h.get_text(' ', strip=True)[:40] for h in program_headings]}")

    seen_programs = set()  # éviter les doublons

    for idx, h in enumerate(program_headings):
        title = h.get_text(" ", strip=True)
        if title.lower() in seen_programs:
            continue
        seen_programs.add(title.lower())

        # Collecter le texte de cette section (jusqu'au prochain heading)
        section_text = ""
        current = h
        for _ in range(15):  # un peu plus généreux qu'avant
            current = current.find_next(["p", "h2", "h3", "blockquote"])
            if current is None:
                break
            if current.name in ("h2", "h3"):
                break
            # Ignorer les blockquotes (souvent des tweets, pas du contenu utile)
            if current.name == "blockquote":
                continue
            section_text += " " + current.get_text(" ", strip=True)

        # Pour le PREMIER programme, prefix avec l'intro
        # (c'est là que sont souvent les chiffres du prog principal)
        full_text = section_text
        if idx == 0 and intro_text:
            full_text = intro_text + " " + section_text

        viewers = find_first_viewers(full_text)
        channel = find_channel_in_text(full_text)
        # Fallback chaîne : intro globale
        if channel is None and intro_text:
            channel = find_channel_in_text(intro_text)

        if viewers is None or channel is None:
            log.info(f"  Skip '{title}' : viewers={viewers}, channel={channel}")
            continue

        rows.append({
            "channel": channel,
            "program": title,
            "viewers": viewers,
            "share": 0.0,
        })
        log.info(f"  OK '{title}' : {channel}, {viewers} kijkers")

    return rows


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} (Televizier v3) ===")

    try:
        # 1. Page index → liste des articles
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        index_soup = BeautifulSoup(r.text, "html.parser")
        log.info(f"DEBUG: index HTTP {r.status_code}, {len(r.text)} chars")

        articles = list_kijkcijfers_articles(index_soup)
        if not articles:
            raise RuntimeError("Aucun article 'kijkcijfers' trouvé sur la page index")

        # 2. Choisir le plus récent (par date_hint)
        best = pick_best_article(articles)
        if best is None:
            raise RuntimeError("Pas d'article candidat valide")
        article_url = best["url"]

        # 3. Fetcher l'article
        r2 = requests.get(article_url, headers=HEADERS, timeout=30)
        r2.raise_for_status()
        article_soup = BeautifulSoup(r2.text, "html.parser")

        # 4. Date effective (depuis l'article lui-même = plus fiable que le hint)
        effective_date = extract_date_from_article(article_soup)
        if effective_date is None:
            # Fallback sur le hint, ou hier
            effective_date = best.get("date_hint") or (date.today() - timedelta(days=1))
            log.warning(f"Date non extraite de l'article, fallback sur {effective_date}")
        else:
            log.info(f"Date effective des données : {effective_date}")

        # 5. Parser les programmes
        rows = parse_article(article_soup, article_url)
        if not rows:
            raise RuntimeError("Aucun programme extrait de l'article")

        # 6. Tri par viewers (pas de dédup par chaîne — Televizier ne donne
        # que 2-4 programmes par jour, mieux vaut tous les afficher même si
        # 2 sont sur la même chaîne).
        ranked = sorted(rows, key=lambda x: x["viewers"], reverse=True)[:5]
        log.info(f"Top retenu : {[(r['channel'], r['program'], r['viewers']) for r in ranked]}")

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

        # status "ok" si on a 5+ entrées, sinon "partial"
        # (Televizier donne souvent 2-4 programmes, c'est attendu)
        status = "ok" if len(entries) >= 5 else "partial"

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
        # Fallback de date : hier (pas aujourd'hui), pour ne pas créer
        # d'archives à des dates futures (cohérent avec fr_ozap.py et de_dwdl.py)
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
