"""
Scraper France — Ozap / Puremédias (avec dédup par chaîne)
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
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

OZAP_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "FILM": ("fiction", "🎬"), "SERIE": ("fiction", "🎬"), "TELEFILM": ("fiction", "🎬"),
    "MAGAZINE": ("info", "📰"), "DOCUMENTAIRE": ("info", "📰"),
    "JOURNAL TELEVISE": ("info", "📰"), "INFORMATION": ("info", "📰"),
    "JEU": ("divertissement", "🎤"), "DIVERTISSEMENT": ("divertissement", "🎤"),
    "HUMOUR": ("divertissement", "🎤"), "TALK-SHOW": ("divertissement", "🎤"),
    "TELE-REALITE": ("divertissement", "🎤"), "MUSIQUE": ("divertissement", "🎤"),
    "SPORT": ("sport", "⚽"), "FOOTBALL": ("sport", "⚽"),
    "AUTRES": ("autre", "📺"),
}

MONTHS_FR: dict[str, int] = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

log = logging.getLogger("fr_ozap")


def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _extract_link_title(a_tag) -> str:
    txt = a_tag.get_text(" ", strip=True)
    if txt and len(txt) > 5:
        return txt
    for parent in a_tag.parents:
        if parent.name in ("article", "div", "section", "li"):
            heading = parent.find(["h1", "h2", "h3", "h4"])
            if heading:
                txt = heading.get_text(" ", strip=True)
                if txt and len(txt) > 5:
                    return txt
            break
    for attr in ("title", "aria-label"):
        val = a_tag.get(attr)
        if val and len(val) > 5:
            return val.strip()
    href = a_tag.get("href", "")
    m = re.search(r"/actu/([^/]+?)(?:/\d+)?/?$", href)
    if m:
        return m.group(1).replace("-", " ")
    return ""


def _list_audience_candidates(listing_soup: BeautifulSoup) -> list[dict]:
    candidates = []
    seen_urls = set()
    all_links = listing_soup.find_all("a", href=True)
    audience_links = [a for a in all_links if re.search(r"/actu/audiences?[-/]", a.get("href", ""))]
    log.info(f"DEBUG: {len(all_links)} liens totaux, dont {len(audience_links)} vers /actu/audiences...")

    for a in audience_links:
        href = a["href"]
        if href.startswith("/"):
            href = BASE_URL + href
        if not href.startswith(BASE_URL) or href in seen_urls:
            continue
        title = _extract_link_title(a)
        if not title:
            continue
        title_lower = strip_accents(title.lower())
        href_lower = href.lower()
        combined = f"{title_lower} {href_lower}"
        if "access-20h" in combined or "access 20h" in combined: continue
        if "pre-access" in combined or "pré-access" in title.lower(): continue
        if "netflix" in combined: continue
        if "audiences-svod" in combined or " svod " in combined: continue
        if " radio" in combined or "-radio" in combined: continue
        if "bilan" in combined: continue
        if "top articles" in combined: continue
        seen_urls.add(href)
        candidates.append({"url": href, "title": title[:100]})
    return candidates


EVENING_CHAPO_PATTERN = re.compile(
    r"audiences? de la (soir[ée]e|journ[ée]e) du\s+[a-zéû]+\s+\d{1,2}\s+[a-zéèûô]+\s+\d{4}",
    re.IGNORECASE
)


def _is_evening_article(article_soup: BeautifulSoup) -> bool:
    text = article_soup.get_text(" ", strip=True)
    if not EVENING_CHAPO_PATTERN.search(text):
        return False
    channel_imgs = article_soup.find_all("img", src=re.compile(r"/channels/\d+\."))
    return len(channel_imgs) >= 3


def find_evening_article_url(listing_soup: BeautifulSoup,
                              session: Optional[requests.Session] = None) -> Optional[tuple[str, BeautifulSoup]]:
    candidates = _list_audience_candidates(listing_soup)
    log.info(f"{len(candidates)} candidats 'Audiences' après filtrage de base")
    if not candidates:
        return None
    sess = session or requests
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
    text = article_soup.get_text(" ", strip=True)
    for pattern in [
        r"soir[ée]e du [a-zéû]+\s+(\d{1,2})\s+([a-zéèûô]+)\s+(\d{4})",
        r"journ[ée]e du [a-zéû]+\s+(\d{1,2})\s+([a-zéèûô]+)\s+(\d{4})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                month = MONTHS_FR.get(strip_accents(m.group(2).lower()))
                if month:
                    return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass
    m = re.search(r"Publi[ée] le (\d{1,2})\s+([a-zéèûô]+)\s+(\d{4})", text, re.IGNORECASE)
    if m:
        try:
            month = MONTHS_FR.get(strip_accents(m.group(2).lower()))
            if month:
                return date(int(m.group(3)), month, int(m.group(1))) - timedelta(days=1)
        except ValueError:
            pass
    log.warning("Date de la soirée non trouvée dans l'article")
    return None


def parse_viewers_fr(text: str) -> Optional[int]:
    text = text.strip()
    m = re.search(r"([\d][\d\s\u00a0]*\d)", text)
    if not m: return None
    try:
        return int(m.group(1).replace("\u00a0", "").replace(" ", ""))
    except ValueError:
        return None


def parse_share_fr(text: str) -> Optional[float]:
    m = re.search(r"([\d]+[.,]?\d*)\s*%?", text.strip())
    if not m: return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def extract_channel_from_img(img_tag) -> Optional[str]:
    if img_tag is None: return None
    alt = img_tag.get("alt", "").strip()
    if alt and alt not in ("", "commercial_link", "puremedias", "player2", "Webedia"):
        return alt
    src = img_tag.get("src", "")
    channel_id_match = re.search(r"/channels/(\d+)\.", src)
    if channel_id_match:
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
    if not raw_title:
        return raw_title, None
    stripped = raw_title.strip()
    sorted_categories = sorted(OZAP_CATEGORY_MAP.keys(), key=len, reverse=True)
    upper = stripped.upper()
    for cat in sorted_categories:
        suffix = " " + cat
        if upper.endswith(suffix) and len(stripped) > len(suffix):
            return stripped[: -len(suffix)].strip(), cat
    return stripped, None


def parse_top_programs(article_soup: BeautifulSoup, source_url: str) -> list[dict]:
    programs = []
    channel_imgs = article_soup.find_all("img", src=re.compile(r"/channels/\d+\."))

    for img in channel_imgs:
        channel = extract_channel_from_img(img)
        if not channel:
            continue
        texts_after = []
        if img.parent is None:
            continue
        next_imgs_channels = channel_imgs[channel_imgs.index(img) + 1:]
        next_channel_img = next_imgs_channels[0] if next_imgs_channels else None
        for sibling in img.find_all_next():
            if sibling is next_channel_img:
                break
            if sibling.name == "img" and sibling.get("src", "").find("/channels/") != -1:
                break
            text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
            if not text:
                continue
            if sibling.name in ("p", "div", "span") and sibling.find(["p", "div", "table"]) is None:
                text_clean = sibling.get_text(" ", strip=True)
                if text_clean and text_clean not in [t for t in texts_after]:
                    texts_after.append(text_clean)
                    if len(texts_after) >= 6:
                        break

        if len(texts_after) < 4:
            continue

        title = None
        category_raw = None
        share_val = None
        viewers_val = None

        for t in texts_after:
            t_stripped = t.strip()
            if not t_stripped:
                continue
            if viewers_val is None and ("téléspectateur" in t_stripped.lower() or "telespectateur" in strip_accents(t_stripped.lower())):
                viewers_val = parse_viewers_fr(t_stripped)
                continue
            if share_val is None and "%" in t_stripped and len(t_stripped) < 15:
                share_val = parse_share_fr(t_stripped)
                continue
            up = t_stripped.upper()
            if category_raw is None and up in OZAP_CATEGORY_MAP and len(t_stripped) < 30:
                category_raw = up
                continue
            if title is None and len(t_stripped) >= 2 and len(t_stripped) < 200 and re.search(r"[A-Za-zÀ-ÿ]", t_stripped):
                if "téléspectateur" in t_stripped.lower():
                    continue
                if t_stripped.lower() in ("médiamétrie", "medialimetrie"):
                    continue
                title = t_stripped
                continue

        if not title or viewers_val is None or share_val is None:
            continue

        title, extracted_category = _split_title_and_category(title)
        if extracted_category and category_raw is None:
            category_raw = extracted_category
        if category_raw is None:
            category_raw = "AUTRES"

        programs.append({
            "channel": channel,
            "program": title,
            "category_raw": category_raw,
            "viewers": viewers_val,
            "share": share_val,
        })

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
    category, emoji = OZAP_CATEGORY_MAP.get(category_raw.upper(), ("autre", "📺"))
    return AudienceEntry(
        rank=rank, channel=channel, channel_color=color_for(channel),
        program=program, program_fr=translate(program),
        viewers=viewers, share=share, source_url=source_url,
        category=category, category_emoji=emoji,
    )


def _looks_like_html(text: str) -> bool:
    if len(text) < 200:
        return False
    sample = text[:2000].lower()
    markers = ("<html", "<!doctype", "<head", "<body", "<a ", "<div", "<meta")
    return any(m in sample for m in markers)


def _try_decompress(raw_bytes: bytes) -> str:
    for name, mod_func in [
        ("brotli", lambda: __import__("brotli").decompress(raw_bytes)),
        ("gzip", lambda: __import__("gzip").decompress(raw_bytes)),
        ("deflate", lambda: __import__("zlib").decompress(raw_bytes)),
    ]:
        try:
            decoded = mod_func().decode("utf-8", errors="replace")
            if _looks_like_html(decoded):
                log.info(f"Décompression {name} réussie")
                return decoded
        except Exception as e:
            log.debug(f"{name}: {e}")
    log.warning("Aucune décompression n'a fonctionné, HTML inutilisable")
    return ""


def run(target_date: Optional[date] = None) -> CountryReport:
    log.info(f"=== Scraping {COUNTRY_NAME} ===")

    try:
        if HAS_CLOUDSCRAPER:
            session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "darwin", "desktop": True}
            )
            log.info("Using cloudscraper")
        else:
            session = requests.Session()
        session.headers.update(HEADERS)

        r = session.get(LISTING_URL, timeout=30)
        r.raise_for_status()
        log.info(f"DEBUG: listing HTTP {r.status_code}, {len(r.text)} chars, "
                 f"encoding={r.headers.get('content-encoding', 'none')}")

        html = r.text
        if not _looks_like_html(html):
            log.warning("Réponse non-HTML, tentative de décompression...")
            html = _try_decompress(r.content)
        listing_soup = BeautifulSoup(html, "html.parser")

        result = find_evening_article_url(listing_soup, session=session)
        if not result:
            raise RuntimeError("Aucun article 'soirée' trouvé sur la page de listing")
        article_url, article_soup = result

        # Date effective : fallback sur HIER si extraction échoue
        evening_date = extract_evening_date(article_soup)
        if evening_date is None:
            evening_date = date.today() - timedelta(days=1)
            log.warning(f"Date non extraite, fallback sur hier : {evening_date}")
        else:
            log.info(f"Date de la soirée : {evening_date}")

        programs = parse_top_programs(article_soup, article_url)
        if not programs:
            raise RuntimeError("Aucun programme extrait de l'article")

        # Tri par viewers décroissant
        programs.sort(key=lambda p: p["viewers"], reverse=True)

        # NOUVEAU : 1 entrée max par chaîne (cohérent avec DE/ES/IT).
        # On garde le programme le mieux classé par chaîne, ce qui élimine
        # mécaniquement les access 20h éventuellement remontés à côté du
        # prime time (le prime fait quasi toujours plus d'audience).
        top_by_channel: dict[str, dict] = {}
        for p in programs:
            ch = p["channel"]
            if ch not in top_by_channel or p["viewers"] > top_by_channel[ch]["viewers"]:
                top_by_channel[ch] = p

        # Top 5 strict après dédup
        top5 = sorted(top_by_channel.values(), key=lambda p: p["viewers"], reverse=True)[:5]

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

        log.info(f"Top 5 retenu (1 prog max/chaîne) : {[(e.channel, e.program, e.viewers) for e in entries]}")

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
