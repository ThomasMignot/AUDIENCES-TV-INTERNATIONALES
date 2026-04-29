"""
Dictionnaire des adaptations officielles VO → VF.
Politique CONSERVATRICE : on n'affiche une traduction que pour les formats
qui ont réellement une version française diffusée sur une chaîne française,
OU pour des séries dont le titre français est usuel et reconnu en France.

Règle d'or : en cas de doute, on retourne None (pas de traduction affichée).
"""
from __future__ import annotations

# Matching exact (insensible à la casse) — formats les plus fréquents
EXACT_TRANSLATIONS: dict[str, str] = {
    # ─── Jeux / quiz ──────────────────────────────────────────────
    "wer wird millionär?": "Qui veut gagner des millions ?",
    "wer wird millionär": "Qui veut gagner des millions ?",
    "¿quién quiere ser millonario?": "Qui veut gagner des millions ?",
    "who wants to be a millionaire": "Qui veut gagner des millions ?",
    "chi vuol essere milionario": "Qui veut gagner des millions ?",
    "la ruota della fortuna": "La Roue de la fortune",
    "la ruota dei campioni": "La Roue de la fortune",
    "wheel of fortune": "La Roue de la fortune",
    "the wall": "The Wall",
    "the floor": "The Floor",
    "the floor – ne rimarrà solo uno": "The Floor",
    "the floor - ne rimarrà solo uno": "The Floor",
    "affari tuoi": "À prendre ou à laisser",
    "deal or no deal": "À prendre ou à laisser",
    "miljoenenjacht": "À prendre ou à laisser",
    "postcode loterij miljoenen jacht": "À prendre ou à laisser",

    # ─── Crochets musicaux / casting ─────────────────────────────
    "the voice": "The Voice",
    "the voice of germany": "The Voice",
    "the voice of holland": "The Voice",
    "the voice senior": "The Voice Senior",
    "la voz": "The Voice",
    "la voz senior": "The Voice Senior",
    "la voz kids": "The Voice Kids",

    "deutschland sucht den superstar": "Nouvelle Star",  # NEW (DSDS)
    "dsds": "Nouvelle Star",
    "operación triunfo": "Star Academy",
    "operacion triunfo": "Star Academy",
    "ot": "Star Academy",

    # ─── Compétitions de talent ──────────────────────────────────
    "got talent": "La France a un incroyable talent",
    "britain's got talent": "La France a un incroyable talent",
    "britain’s got talent": "La France a un incroyable talent",
    "america's got talent": "La France a un incroyable talent",
    "america’s got talent": "La France a un incroyable talent",
    "das supertalent": "La France a un incroyable talent",
    "italia's got talent": "La France a un incroyable talent",
    "italia’s got talent": "La France a un incroyable talent",
    "got talent españa": "La France a un incroyable talent",
    "got talent espana": "La France a un incroyable talent",

    # ─── Danse / divertissement musical ──────────────────────────
    "dancing with the stars": "Danse avec les stars",
    "strictly come dancing": "Danse avec les stars",
    "bailando con las estrellas": "Danse avec les stars",
    "ballando con le stelle": "Danse avec les stars",
    "let's dance": "Danse avec les stars",
    "let’s dance": "Danse avec les stars",

    # ─── Cuisine ─────────────────────────────────────────────────
    "masterchef": "MasterChef",
    "masterchef australia": "MasterChef",
    "masterchef uk": "MasterChef",
    "masterchef junior": "MasterChef Junior",
    "masterchef celebrity": "MasterChef Célébrités",
    "top chef": "Top Chef",
    "hell's kitchen": "Hell's Kitchen",
    "hell’s kitchen": "Hell's Kitchen",
    "the great british bake off": "Le Meilleur Pâtissier",
    "bake off": "Le Meilleur Pâtissier",
    "bake off italia": "Le Meilleur Pâtissier",
    "heel holland bakt": "Le Meilleur Pâtissier",
    "heel holland bakt elke dag": "Le Meilleur Pâtissier",
    "das große backen": "Le Meilleur Pâtissier",
    "das grosse backen": "Le Meilleur Pâtissier",
    "das große promibacken": "Le Meilleur Pâtissier des chefs",
    "das grosse promibacken": "Le Meilleur Pâtissier des chefs",
    "kitchen impossible": "Cauchemar en cuisine",
    "kitchen nightmares": "Cauchemar en cuisine",
    "cauchemar en cuisine": "Cauchemar en cuisine",
    "rosins restaurants": "Cauchemar en cuisine",
    "4 ristoranti": "4 mariages pour une lune de miel (format)",
    "4 hochzeiten und eine traumreise": "4 mariages pour une lune de miel",

    # ─── Survie / aventure ───────────────────────────────────────
    "survivor": "Koh-Lanta",
    "supervivientes": "Koh-Lanta",
    "supervivientes:conexion honduras": "Koh-Lanta",
    "isola dei famosi": "Koh-Lanta",
    "l'isola dei famosi": "Koh-Lanta",
    "l’isola dei famosi": "Koh-Lanta",
    "expeditie robinson": "Koh-Lanta",
    "ich bin ein star - holt mich hier raus": "Je suis une célébrité, sortez-moi de là !",
    "dschungelcamp": "Je suis une célébrité, sortez-moi de là !",

    # ─── Big Brother / huis clos ─────────────────────────────────
    "big brother": "Secret Story",
    "grande fratello": "Secret Story",
    "grande fratello vip": "Secret Story",
    "gran hermano": "Secret Story",
    "gran hermano vip": "Secret Story",
    "promi big brother": "Secret Story",

    # ─── Dating / séduction ──────────────────────────────────────
    "the bachelor": "Le Bachelor",
    "the bachelorette": "Le Bachelor",
    "der bachelor": "Le Bachelor",
    "die bachelorette": "Le Bachelor",
    "la isla de las tentaciones": "L'Île de la tentation",
    "la isla de las tentaciones:express": "L'Île de la tentation",
    "la isla de las tentaciones express": "L'Île de la tentation",
    "temptation island": "L'Île de la tentation",
    "love island": "Love Island",
    "married at first sight": "Mariés au premier regard",
    "casados a primera vista": "Mariés au premier regard",
    "first dates": "First Dates",
    "primo appuntamento": "First Dates",

    # ─── Vie à la campagne ──────────────────────────────────────
    "bauer sucht frau": "L'amour est dans le pré",
    "boer zoekt vrouw": "L'amour est dans le pré",
    "l'amore è nell'aria": "L'amour est dans le pré",

    # ─── Mode / Mannequinat ─────────────────────────────────────
    "germany's next topmodel": "Top Model",
    "germany’s next topmodel": "Top Model",
    "germanys next topmodel": "Top Model",
    "gntm": "Top Model",
    "america's next top model": "Top Model",
    "america’s next top model": "Top Model",

    # ─── Talents enquête ─────────────────────────────────────────
    "wie is de mol": "Le Mole",
    "die höhle der löwen": "Qui veut être mon associé ?",
    "die hohle der lowen": "Qui veut être mon associé ?",
    "shark tank": "Qui veut être mon associé ?",

    # ─── Variétés / divertissement allemand ─────────────────────
    "wer weiß denn sowas": "Wer weiß denn sowas",  # pas d'équivalent FR direct
    "wer weiß denn sowas?": "Wer weiß denn sowas",
    "wer weiß denn sowas xxl": "Wer weiß denn sowas",
    "verstehen sie spaß": "Surprise sur prise (concept)",
    "verstehen sie spass": "Surprise sur prise (concept)",

    # ─── Séries US diffusées en France ───────────────────────────
    "ncis": "NCIS : Enquêtes spéciales",
    "n.c.i.s.": "NCIS : Enquêtes spéciales",
    "n.c.i.s. – unità anticrimine": "NCIS : Enquêtes spéciales",
    "ncis: los angeles": "NCIS : Los Angeles",
    "ncis los angeles": "NCIS : Los Angeles",
    "ncis: hawaii": "NCIS : Hawaï",
    "grey's anatomy": "Grey's Anatomy",
    "grey’s anatomy": "Grey's Anatomy",
    "9-1-1": "9-1-1",
    "9-1-1: lone star": "9-1-1 : Lone Star",
    "the good doctor": "Good Doctor",
    "chicago fire": "Chicago Fire",
    "chicago med": "Chicago Med",
    "chicago p.d.": "Chicago Police Department",
    "chicago pd": "Chicago Police Department",
    "law & order": "New York, police judiciaire",
    "law & order – i due volti della giustizia": "New York, police judiciaire",
    "law & order: svu": "New York, unité spéciale",
    "fbi": "FBI",
    "f.b.i.": "FBI",
    "blue bloods": "Blue Bloods",
    "young sheldon": "Young Sheldon",
    "the big bang theory": "The Big Bang Theory",
    "modern family": "Modern Family",
    "the rookie": "The Rookie : Le flic de Los Angeles",
    "hawaii five-0": "Hawaii 5-0",
    "macgyver": "MacGyver",
    "the walking dead": "The Walking Dead",
    "yellowstone": "Yellowstone",
    "criminal minds": "Esprits criminels",
    "navy cis": "NCIS : Enquêtes spéciales",  # nom allemand de NCIS
    "manifest": "Manifest",
    "the simpsons": "Les Simpson",
    "die simpsons": "Les Simpson",
    "family guy": "Les Griffin",

    # ─── Séries UK diffusées en France ───────────────────────────
    "doctor who": "Doctor Who",
    "downton abbey": "Downton Abbey",
    "sherlock": "Sherlock",
    "peaky blinders": "Peaky Blinders",
    "call the midwife": "Call the Midwife : Les Nouvelles Sages-femmes",
    "line of duty": "Line of Duty",
    "broadchurch": "Broadchurch",
    "inspector barnaby": "Inspecteur Barnaby",
    "inspektor barnaby": "Inspecteur Barnaby",

    # ─── Fictions allemandes connues en France ──────────────────
    "der bergdoktor": "Le Médecin de la montagne",
    "die rosenheim-cops": "Les Rois de l'enquête",  # diffusé sur 6ter
    "soko leipzig": "SOKO Leipzig",
    "soko münchen": "SOKO Munich",
    "soko köln": "SOKO Cologne",

    # ─── Fictions italiennes diffusées en France ────────────────
    "il commissario montalbano": "Inspecteur Montalbano",  # NEW (RTBF, France 3)
    "montalbano": "Inspecteur Montalbano",
    "il giovane montalbano": "Le Jeune Inspecteur Montalbano",
    "don matteo": "Don Matteo",
    "doc - nelle tue mani": "Doc",
    "doc – nelle tue mani": "Doc",
    "imma tataranni": "Imma Tataranni",
    "i bastardi di pizzofalcone": "Les Bâtards de Pizzofalcone",
    "l'amica geniale": "L'amie prodigieuse",
    "l’amica geniale": "L'amie prodigieuse",
    "il commissario ricciardi": "Le Commissaire Ricciardi",

    # ─── Soap turques diffusées en Italie ───────────────────────
    "forbidden fruit": "Forbidden Fruit",  # diffusé tel quel en France
    "endless love": "Endless Love",
    "terra amara": "Terra Amara",

    # ─── Films cinéma (titres FR usuels) ─────────────────────────
    "kung fu panda 4": "Kung Fu Panda 4",
    "men in black": "Men in Black",
    "godzilla x kong: the new empire": "Godzilla x Kong : Le Nouvel Empire",
    "a haunting in venice": "Mystère à Venise",
    "jungle cruise": "Jungle Cruise",
    "die mumie kehrt zurück": "Le Retour de la momie",
    "die mumie kehrt zuruck": "Le Retour de la momie",
    "la la land": "La La Land",
    "the hateful eight": "Les Huit Salopards",
    "v per vendetta": "V pour Vendetta",
    "ender's game": "La Stratégie Ender",
    "ender’s game": "La Stratégie Ender",
    "the birth of a nation": "The Birth of a Nation",
    "blacklight": "Blacklight",
    "ticket ins paradies": "Ticket pour le paradis",

    # ─── Mini-séries ─────────────────────────────────────────────
    "chernobyl": "Chernobyl",
    "tschernobyl": "Chernobyl",

    # ─── Comedy / variétés ───────────────────────────────────────
    "saturday night live": "Saturday Night Live",
}


# Matching "contient" — pour les variantes (épisodes, éditions, spécials)
CONTAINS_TRANSLATIONS: list[tuple[str, str]] = [
    ("wer wird millionär", "Qui veut gagner des millions ?"),
    ("chi vuol essere milionario", "Qui veut gagner des millions ?"),
    ("¿quién quiere ser millonario", "Qui veut gagner des millions ?"),
    ("masterchef", "MasterChef"),
    ("the voice", "The Voice"),
    ("la voz", "The Voice"),
    ("dancing with the stars", "Danse avec les stars"),
    ("ballando con le stelle", "Danse avec les stars"),
    ("strictly come dancing", "Danse avec les stars"),
    ("let's dance", "Danse avec les stars"),
    ("let’s dance", "Danse avec les stars"),
    ("got talent", "La France a un incroyable talent"),
    ("supertalent", "La France a un incroyable talent"),
    ("la isla de las tentaciones", "L'Île de la tentation"),
    ("temptation island", "L'Île de la tentation"),
    ("supervivientes", "Koh-Lanta"),
    ("isola dei famosi", "Koh-Lanta"),
    ("expeditie robinson", "Koh-Lanta"),
    ("big brother", "Secret Story"),
    ("grande fratello", "Secret Story"),
    ("gran hermano", "Secret Story"),
    ("bachelor", "Le Bachelor"),
    ("bachelorette", "Le Bachelor"),
    ("married at first sight", "Mariés au premier regard"),
    ("casados a primera vista", "Mariés au premier regard"),
    ("primo appuntamento", "First Dates"),
    ("ncis", "NCIS : Enquêtes spéciales"),
    ("grey's anatomy", "Grey's Anatomy"),
    ("grey’s anatomy", "Grey's Anatomy"),
    ("chicago fire", "Chicago Fire"),
    ("chicago med", "Chicago Med"),
    ("chicago p.d", "Chicago Police Department"),
    ("chicago pd", "Chicago Police Department"),
    ("the rookie", "The Rookie : Le flic de Los Angeles"),
    ("law & order", "New York, police judiciaire"),
    ("the great british bake off", "Le Meilleur Pâtissier"),
    ("bake off", "Le Meilleur Pâtissier"),
    ("heel holland bakt", "Le Meilleur Pâtissier"),
    ("kitchen nightmares", "Cauchemar en cuisine"),
    ("kitchen impossible", "Cauchemar en cuisine"),
    ("bauer sucht frau", "L'amour est dans le pré"),
    ("boer zoekt vrouw", "L'amour est dans le pré"),
    ("germany's next topmodel", "Top Model"),
    ("germany’s next topmodel", "Top Model"),
    ("deutschland sucht den superstar", "Nouvelle Star"),
    ("operación triunfo", "Star Academy"),
    ("operacion triunfo", "Star Academy"),
    ("commissario montalbano", "Inspecteur Montalbano"),
    ("inspector barnaby", "Inspecteur Barnaby"),
    ("inspektor barnaby", "Inspecteur Barnaby"),
    ("doc - nelle tue mani", "Doc"),
    ("doc – nelle tue mani", "Doc"),
    ("dschungelcamp", "Je suis une célébrité, sortez-moi de là !"),
    ("ich bin ein star", "Je suis une célébrité, sortez-moi de là !"),
    ("die simpsons", "Les Simpson"),
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
