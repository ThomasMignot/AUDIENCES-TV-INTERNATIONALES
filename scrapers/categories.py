"""
Catégorisation des émissions TV par genre.

5 catégories :
  - 🎬 fiction         → séries TV, téléfilms, films cinéma
  - 🎤 divertissement  → jeux, quiz, variétés, téléréalité, talk-shows
  - 📰 info            → JT, magazines d'actualité, débats, documentaires
  - ⚽ sport            → matchs, compétitions, émissions sportives
  - 📺 autre           → fallback si la catégorie n'est pas déterminée

La fonction categorize() combine deux approches :
1. Dictionnaire exact (PROGRAM_CATEGORIES) — pour les émissions connues
2. Heuristiques par mots-clés — pour les inconnues

Politique : en cas de doute, on retourne 'autre' (jamais deviner).
"""
from __future__ import annotations

import re
from typing import Literal

Category = Literal["fiction", "divertissement", "info", "sport", "autre"]

CATEGORY_META: dict[Category, dict] = {
    "fiction":         {"emoji": "🎬", "label": "fiction"},
    "divertissement":  {"emoji": "🎤", "label": "divertissement"},
    "info":            {"emoji": "📰", "label": "info"},
    "sport":           {"emoji": "⚽", "label": "sport"},
    "autre":           {"emoji": "📺", "label": "autre"},
}


# ─── Dictionnaire de programmes connus ────────────────────────────

PROGRAM_CATEGORIES: dict[str, Category] = {
    # ── INFO ─────────────────────────────────────────────────────
    # Allemagne
    "tagesschau": "info",
    "tagesthemen": "info",
    "heute": "info",
    "heute journal": "info",
    "heute-show": "divertissement",  # satire d'actu, plutôt divertissement
    "heute journal update": "info",
    "auslandsjournal": "info",
    "brennpunkt": "info",
    "monitor": "info",
    "report mainz": "info",
    "panorama": "info",
    "kontraste": "info",
    "plusminus": "info",
    "markus lanz": "info",
    "anne will": "info",
    "maischberger": "info",
    "hart aber fair": "info",
    "besseresser": "info",
    "stern tv": "info",
    "frontal": "info",
    "rtl aktuell": "info",
    "37 grad": "info",
    # Espagne
    "antena 3 noticias 1": "info",
    "antena 3 noticias 2": "info",
    "antena 3 noticias": "info",
    "telediario": "info",
    "informativos t5": "info",
    "la sexta noticias": "info",
    "la noche en 24h": "info",
    "la revuelta": "divertissement",
    "el hormiguero": "divertissement",
    "el intermedio": "info",  # satire d'actu, plus info que divertissement
    # Italie
    "tg1": "info", "tg2": "info", "tg3": "info", "tg5": "info",
    "tg la7": "info", "tgla7": "info",
    "tg2 post": "info",
    "newsroom": "info",
    "quarta repubblica": "info",
    "otto e mezzo": "info",
    "e sempre cartabianca": "info",
    "è sempre cartabianca": "info",
    "dimartedì": "info",
    "farwest": "info",
    "le iene": "info",  # magazine d'enquête
    "report": "info",
    "che tempo che fa": "divertissement",  # talk-show
    "belve": "divertissement",  # interview show
    "stern tv": "info",
    # Pays-Bas
    "journaal 20 uur": "info",
    "journaal 18 uur": "info",
    "journaal laat": "info",
    "nieuwsuur": "info",
    "hart van nederland": "info",
    "eenvandaag": "info",
    "vandaag inside": "info",  # talk sport/actu
    "nos journaal": "info",
    "half acht nieuws": "info",
    "zes uur nieuws": "info",
    "editie nl": "info",
    "rtl boulevard": "divertissement",  # magazine people
    "shownieuws": "divertissement",
    "pauw en de wit": "info",
    "het verhaal van nederland": "info",  # docu historique
    "mr. frank visser doet uitspraak": "divertissement",
    "heel holland bakt": "divertissement",
    "heel holland bakt elke dag": "divertissement",

    # ── DIVERTISSEMENT ─────────────────────────────────────────
    # Allemagne
    "wer wird millionär": "divertissement",
    "wer wird millionär?": "divertissement",
    "tv total": "divertissement",
    "the voice of germany": "divertissement",
    "the voice senior": "divertissement",
    "germany's next topmodel": "divertissement",
    "germany’s next topmodel": "divertissement",
    "germanys next topmodel": "divertissement",
    "gntm": "divertissement",
    "let's dance": "divertissement",
    "let’s dance": "divertissement",
    "das supertalent": "divertissement",
    "das große promibacken": "divertissement",
    "das grosse promibacken": "divertissement",
    "promibacken": "divertissement",
    "schlag den star": "divertissement",
    "joko & klaas": "divertissement",
    "wer stiehlt mir die show": "divertissement",
    "wer weiß denn sowas": "divertissement",
    "wer weiss denn sowas": "divertissement",
    "bares für rares": "divertissement",
    "bares fur rares": "divertissement",
    "inside ferrero": "info",  # docu-reportage
    "ninja warrior germany": "divertissement",
    "bauer sucht frau": "divertissement",
    "dschungelcamp": "divertissement",
    "ich bin ein star": "divertissement",
    "dsds": "divertissement",
    "der bachelor": "divertissement",
    "die bachelorette": "divertissement",
    # Espagne
    "pasapalabra": "divertissement",
    "masterchef": "divertissement",
    "la isla de las tentaciones": "divertissement",
    "supervivientes": "divertissement",
    "gran hermano": "divertissement",
    "gran hermano vip": "divertissement",
    "casados a primera vista": "divertissement",
    "first dates": "divertissement",
    "la voz": "divertissement",
    "operación triunfo": "divertissement",
    "ot": "divertissement",
    "got talent españa": "divertissement",
    "got talent": "divertissement",
    "tu cara me suena": "divertissement",
    "cuarto milenio": "info",  # docu paranormal
    "horizonte": "info",
    "lo de evole": "info",  # interview
    # Italie
    "la ruota della fortuna": "divertissement",
    "la ruota dei campioni": "divertissement",
    "affari tuoi": "divertissement",
    "grande fratello": "divertissement",
    "grande fratello vip": "divertissement",
    "amici": "divertissement",
    "amici di maria de filippi": "divertissement",
    "isola dei famosi": "divertissement",
    "l'isola dei famosi": "divertissement",
    "l'eredità": "divertissement",
    "l'eredità - la sfida dei 7": "divertissement",
    "avanti un altro": "divertissement",
    "the floor": "divertissement",
    "the floor – ne rimarrà solo uno": "divertissement",
    "ballando con le stelle": "divertissement",
    "tale e quale show": "divertissement",
    "stasera italia": "info",
    "striscia la notizia": "divertissement",
    "canzonissima": "divertissement",
    "italia's got talent": "divertissement",
    "italia’s got talent": "divertissement",
    "gialappashow": "divertissement",
    "splendida cornice": "divertissement",
    # Pays-Bas
    "kopen zonder kijken": "divertissement",
    "slimste mens": "divertissement",
    "lubach": "divertissement",
    "eva": "divertissement",
    "the voice of holland": "divertissement",
    "wie is de mol": "divertissement",
    "miljoenenjacht": "divertissement",
    "postcode loterij miljoenen jacht": "divertissement",
    "even tot hier": "divertissement",
    "married at first sight": "divertissement",
    "heel holland bakt": "divertissement",
    "heel holland bakt elke dag": "divertissement",
    "verraders": "divertissement",
    "de verraders": "divertissement",
    "dit was het nieuws": "divertissement",
    "ranking the stars": "divertissement",
    "only joling": "divertissement",
    "project dans": "divertissement",
    "kees van der spek ontmaskert": "info",  # journalisme d'investigation
    "survive your family": "divertissement",

    # ── FICTION ────────────────────────────────────────────────
    # Allemagne
    "tatort": "fiction",
    "polizeiruf 110": "fiction",
    "die rosenheim-cops": "fiction",
    "der bergdoktor": "fiction",
    "in aller freundschaft": "fiction",
    "sturm der liebe": "fiction",
    "soko wismar": "fiction",
    "watzmann ermittelt": "fiction",
    "friesland": "fiction",
    "wilsberg": "fiction",
    "frühling": "fiction",
    "fruhling": "fiction",
    "kein einfacher mord": "fiction",
    "doc caro": "fiction",
    "doc caro - jedes leben zählt": "fiction",
    "die notärztin": "fiction",
    "die notarztin": "fiction",
    "gute zeiten, schlechte zeiten": "fiction",
    "gute zeiten schlechte zeiten": "fiction",
    "gzsz": "fiction",
    "alles was zählt": "fiction",
    "alles was zahlt": "fiction",
    # Espagne
    "la promesa": "fiction",
    "sueños de libertad": "fiction",
    "hermanos": "fiction",
    "la que se avecina": "fiction",
    "una nueva vida": "fiction",
    "barrio esperanza": "fiction",
    "en tierra lejana": "fiction",
    # Italie
    "i cesaroni": "fiction",
    "i cesaroni – il ritorno": "fiction",
    "la buona stella": "fiction",
    "un posto al sole": "fiction",
    "il paradiso delle signore": "fiction",
    "doc - nelle tue mani": "fiction",
    "doc – nelle tue mani": "fiction",
    "roberta valente, notaio in sorrento": "fiction",
    "roberta valente": "fiction",
    "racconto di una notte": "fiction",
    "montalbano": "fiction",
    "il commissario montalbano": "fiction",
    "don matteo": "fiction",
    "l'amica geniale": "fiction",
    "uno sbirro in appennino": "fiction",
    "mordufer": "fiction",
    # Films cinéma (Italie récents)
    "blacklight": "fiction",
    "ender's game": "fiction",
    "ender’s game": "fiction",
    "the hateful eight": "fiction",
    "v per vendetta": "fiction",
    "the birth of a nation": "fiction",
    # Séries US/UK traduites
    "ncis": "fiction",
    "n.c.i.s.": "fiction",
    "ncis: los angeles": "fiction",
    "grey's anatomy": "fiction",
    "grey’s anatomy": "fiction",
    "chicago fire": "fiction",
    "chicago med": "fiction",
    "chicago p.d.": "fiction",
    "the rookie": "fiction",
    "fbi": "fiction",
    "f.b.i.": "fiction",
    "law & order": "fiction",
    "hawaii five-0": "fiction",
    "macgyver": "fiction",
    "9-1-1": "fiction",
    "line of duty": "fiction",
    "doctor who": "fiction",
    # Pays-Bas
    "flikken maastricht": "fiction",
    "dag & nacht": "fiction",
    "bondgenoten": "fiction",
    "goede tijden, slechte tijden": "fiction",
    "goede tijden slechte tijden": "fiction",

    # ── SPORT ──────────────────────────────────────────────────
    "coppa italia": "sport",
    "champions league": "sport",
    "uefa champions league": "sport",
    "bundesliga": "sport",
    "ligue des champions": "sport",
    "premier league": "sport",
    "la liga": "sport",
    "serie a": "sport",
    "eredivisie": "sport",
    "studio sport": "sport",
    "studio voetbal": "sport",
    "sport mediaset": "sport",
    "sportschau": "sport",
    "inter-como": "sport",
    "skispringen": "sport",
    "tour de france": "sport",
    "roland garros": "sport",
    "wimbledon": "sport",
}


# ─── Heuristiques par mots-clés (fallback) ────────────────────────

# Chaque tuple est (regex, catégorie). On matche dans l'ordre, premier match gagne.
# Les patterns sont testés en minuscule sur le titre du programme.
HEURISTIC_RULES: list[tuple[str, Category]] = [
    # --- SPORT en premier (très spécifique) ---
    (r"\b(?:football|foot|soccer)\b", "sport"),
    (r"\bvoetbal\b", "sport"),  # NL
    (r"\bfutbol\b|\bfútbol\b", "sport"),  # ES
    (r"\bcalcio\b", "sport"),  # IT
    (r"\bfußball\b|\bfussball\b", "sport"),  # DE
    (r"\b(?:ligue\s+des\s+champions|champions\s+league|coppa|cup|liga|bundesliga|serie\s+a|eredivisie)\b", "sport"),
    (r"\b(?:vs\.?|contro|gegen)\s+\w+", "sport"),  # matchs "X vs Y"
    (r"\btennis\b|\bbasket\b|\brugby\b|\bhockey\b|\bcyclisme\b|\bgolf\b|\bf1\b|\bmoto\s?gp\b", "sport"),
    (r"\b(?:olympique|olympic|jeux\s+olympiques|olimpiadi|olympia)\b", "sport"),
    (r"\bformula\s+1\b", "sport"),
    (r"\bwielrennen\b", "sport"),  # cyclisme NL

    # --- INFO (JT, magazines d'actualité) ---
    (r"^(?:tg|tg\s?1|tg\s?2|tg\s?3|tg\s?5|tgr|tg\s?la7)\b", "info"),
    (r"\btelegiornale\b", "info"),
    (r"\b(?:news|nieuws|noticias|nachrichten|journal|notizie|jornal|notícias)\b", "info"),
    (r"^(?:journaal|journal)\b", "info"),
    (r"\btelediario\b|\bteled\.\b", "info"),
    (r"\btagesschau\b|\btagesthemen\b", "info"),
    (r"\bheute(?:\s+journal)?\b", "info"),
    (r"\binformativos?\b", "info"),
    (r"\breport(?:age)?\b", "info"),  # prudent, peut capturer des docs
    (r"\bmagazin\b|\bmagazine\b(?!\s+tv)", "info"),

    # --- DIVERTISSEMENT ---
    (r"\b(?:show|spettacolo|shows?)\b", "divertissement"),
    (r"\b(?:gran(?:de)?\s+fratello|big\s+brother|casa\s+dos\s+segredos|secret\s+story)\b", "divertissement"),
    (r"\b(?:master\s?chef|top\s+chef|cauchemar\s+en\s+cuisine|kitchen\s+(?:nightmares|impossible))\b", "divertissement"),
    (r"\b(?:got\s+talent|the\s+voice|la\s+voz|super\s?talent)\b", "divertissement"),
    (r"\b(?:dancing\s+with\s+the\s+stars|strictly\s+come\s+dancing|ballando\s+con\s+le\s+stelle|danse\s+avec\s+les\s+stars|let'?s\s+dance)\b", "divertissement"),
    (r"\b(?:survivor|supervivientes|isola\s+dei\s+famosi|koh.lanta)\b", "divertissement"),
    (r"\b(?:bachelor(?:ette)?|married\s+at\s+first\s+sight|mari[éeè]s\s+au\s+premier|first\s+dates|love\s+island|temptation|tentaciones)\b", "divertissement"),
    (r"\b(?:bake\s+off|heel\s+holland\s+bakt|le\s+meilleur\s+p[âa]tissier|das\s+gro(?:ß|ss)e\s+backen)\b", "divertissement"),
    (r"\b(?:wer\s+wird\s+millionär|chi\s+vuol\s+essere\s+milionario|who\s+wants\s+to\s+be\s+a\s+millionaire|qui\s+veut\s+gagner|ruota\s+della\s+fortuna|wheel\s+of\s+fortune|affari\s+tuoi|deal\s+or\s+no\s+deal)\b", "divertissement"),
    (r"\bquiz\b|\bgame\s?show\b|\bconcurso\b", "divertissement"),
    (r"\btalk[\s-]?show\b", "divertissement"),
    (r"\bsitcom\b|\breality\b", "divertissement"),
    (r"\bcomedy\b|\bcom\u00e9die\b|\bkomödie\b", "divertissement"),

    # --- FICTION (séries et films) ---
    (r"\btatort\b|\bpolizeiruf\b", "fiction"),
    (r"\bkommissar\b|\bcommissaire\b|\bcommissario\b|\bcomisario\b", "fiction"),
    (r"\bserie\b(?!\s+a)", "fiction"),  # "serie" mais pas "serie A" (sport)
    (r"\bsoap\b|\bnovela\b|\bfiction\b", "fiction"),
    (r"\bfilm\b", "fiction"),  # films
    (r"\bpr[ée]miere\b|\bblockbuster\b", "fiction"),
]

HEURISTIC_COMPILED = [(re.compile(pattern, re.IGNORECASE), cat) for pattern, cat in HEURISTIC_RULES]


def categorize(program: str) -> Category:
    """
    Retourne la catégorie d'un programme TV.

    Ordre de priorité :
    1. Correspondance exacte dans PROGRAM_CATEGORIES (insensible à la casse)
    2. Correspondance partielle (substring) dans PROGRAM_CATEGORIES
    3. Heuristiques par mots-clés
    4. Fallback 'autre'
    """
    if not program:
        return "autre"

    lower = program.strip().lower()

    # Nettoyer les variantes fréquentes : enlever ce qui vient après " - " ou " : "
    # Ex: "The Floor – Ne Rimarrà Solo Uno" → on teste aussi "the floor"
    # Ex: "NCIS: Los Angeles" → on teste aussi "ncis: los angeles" ET "ncis"
    candidates = [lower]
    for sep in [" - ", " – ", " : ", ":", " -"]:
        if sep in lower:
            candidates.append(lower.split(sep, 1)[0].strip())

    # 1. Match exact
    for candidate in candidates:
        if candidate in PROGRAM_CATEGORIES:
            return PROGRAM_CATEGORIES[candidate]

    # 2. Match partiel : le titre contient une clé du dict
    # On privilégie la clé la plus longue pour éviter faux positifs
    matches = [
        (key, cat) for key, cat in PROGRAM_CATEGORIES.items()
        if key in lower and len(key) >= 5  # éviter les clés trop courtes
    ]
    if matches:
        matches.sort(key=lambda x: len(x[0]), reverse=True)
        return matches[0][1]

    # 3. Heuristiques
    for pattern, cat in HEURISTIC_COMPILED:
        if pattern.search(lower):
            return cat

    # 4. Fallback
    return "autre"


def category_badge(category: Category) -> dict:
    """Retourne {emoji, label} pour afficher la catégorie."""
    return CATEGORY_META.get(category, CATEGORY_META["autre"])
