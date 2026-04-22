"""
Dictionnaire des adaptations officielles VO → VF.
Politique CONSERVATRICE : on n'affiche une traduction que pour les formats
qui ont réellement une version française diffusée sur une chaîne française.

Règle d'or : en cas de doute, on retourne None (pas de traduction affichée).
"""
from __future__ import annotations

# Matching exact (insensible à la casse) — formats les plus fréquents
EXACT_TRANSLATIONS: dict[str, str] = {
    # ─── Jeux / quiz ──────────────────────────────────────────────
    "wer wird millionär?": "Qui veut gagner des millions ?",
    "wer wird millionär": "Qui veut gagner des millions ?",
    "¿quién quiere ser millonario?": "Qui veut gagner des millions ?",

    # ─── Télé-réalité / divertissement ────────────────────────────
    "dancing with the stars": "Danse avec les stars",
    "strictly come dancing": "Danse avec les stars",  # version UK du même format
    "bailando con las estrellas": "Danse avec les stars",
    "ballando con le stelle": "Danse avec les stars",
    "let's dance": "Danse avec les stars",  # version allemande

    "the voice": "The Voice",
    "the voice of germany": "The Voice",
    "the voice of holland": "The Voice",
    "la voz": "The Voice",

    "masterchef": "MasterChef",
    "masterchef australia": "MasterChef",
    "masterchef uk": "MasterChef",

    "got talent": "La France a un incroyable talent",
    "britain's got talent": "La France a un incroyable talent",
    "das supertalent": "La France a un incroyable talent",

    "top chef": "Top Chef",

    # ─── Formats survival / aventure ─────────────────────────────
    "survivor": "Koh-Lanta",
    "supervivientes": "Koh-Lanta",  # version espagnole de Survivor
    "isola dei famosi": "Koh-Lanta",  # version italienne

    # ─── Séries US diffusées en France ───────────────────────────
    "ncis": "NCIS : Enquêtes spéciales",
    "ncis: los angeles": "NCIS : Los Angeles",
    "grey's anatomy": "Grey's Anatomy",
    "9-1-1": "9-1-1",
    "9-1-1: lone star": "9-1-1 : Lone Star",
    "the good doctor": "Good Doctor",
    "chicago fire": "Chicago Fire",
    "chicago med": "Chicago Med",
    "chicago p.d.": "Chicago Police Department",
    "law & order": "New York, police judiciaire",
    "law & order: svu": "New York, unité spéciale",
    "fbi": "FBI",
    "blue bloods": "Blue Bloods",
    "young sheldon": "Young Sheldon",
    "the big bang theory": "The Big Bang Theory",
    "modern family": "Modern Family",

    # ─── Séries UK diffusées en France ───────────────────────────
    "doctor who": "Doctor Who",
    "downton abbey": "Downton Abbey",
    "sherlock": "Sherlock",
    "peaky blinders": "Peaky Blinders",
    "call the midwife": "Call the Midwife",
    "line of duty": "Line of Duty",  # diffusé sur Polar+

    # ─── Dating / relations ──────────────────────────────────────
    "first dates": "First Dates",  # diffusé en France sous le même nom
    "married at first sight": "Mariés au premier regard",
    "love island": "Love Island",

    # ─── Décoration / maison ─────────────────────────────────────
    "the great british bake off": "Le Meilleur Pâtissier",
    "bake off": "Le Meilleur Pâtissier",
}


# Matching "contient" — pour les cas où le titre contient un suffixe variable
# (ex: "Wer wird Millionär? - Das Prominentenspecial" contient "wer wird millionär")
CONTAINS_TRANSLATIONS: list[tuple[str, str]] = [
    ("wer wird millionär", "Qui veut gagner des millions ?"),
    ("masterchef", "MasterChef"),  # capte les variantes "MasterChef Junior", etc.
    ("the voice", "The Voice"),
    ("dancing with the stars", "Danse avec les stars"),
    ("got talent", "La France a un incroyable talent"),
    ("ncis", "NCIS : Enquêtes spéciales"),  # attention : ne capte pas NCIS:LA seul
    ("grey's anatomy", "Grey's Anatomy"),
    ("chicago fire", "Chicago Fire"),
    ("chicago med", "Chicago Med"),
]


def translate(title: str) -> str | None:
    """
    Retourne la traduction française officielle du titre, ou None si inconnue.
    Politique conservatrice : mieux vaut ne rien afficher qu'une traduction incertaine.
    """
    if not title:
        return None
    lower = title.strip().lower()

    # 1. Match exact
    if lower in EXACT_TRANSLATIONS:
        return EXACT_TRANSLATIONS[lower]

    # 2. Match "contient" — on prend le plus long match pour privilégier la spécificité
    matches = [(needle, translation) for needle, translation in CONTAINS_TRANSLATIONS if needle in lower]
    if matches:
        matches.sort(key=lambda x: len(x[0]), reverse=True)
        return matches[0][1]

    return None
