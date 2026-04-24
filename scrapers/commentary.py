"""
Module de génération de commentaires éditoriaux par pays.

Utilise Google Gemini 2.5 Flash-Lite (gratuit, 1000 req/jour, 15 req/min)
pour rédiger 5-6 phrases d'analyse fouillée par pays à partir des données
du jour + archive 7 derniers jours + contexte concurrentiel.

Choix du modèle : Flash-Lite plutôt que Flash parce que Flash consomme tout
le budget maxOutputTokens en "thinking interne" avant de produire le texte
visible, résultant en réponses tronquées. Flash-Lite écrit directement et
donne des analyses complètes de bonne qualité.

Style : analytique type Le Monde Médias / Les Jours — avec comparaisons
historiques, observations structurelles, tensions concurrentielles.

Politique :
- Jamais d'invention : le modèle ne peut parler QUE de ce qu'on lui fournit
- Gestion des 429 et 503 : retry avec backoff exponentiel (2 tentatives)
- Rate-limit manuel : 5s entre chaque appel pour rester sous les quotas
- En cas d'erreur : on retourne None, le script continue sans synthèse
- Coût : ~0 € (tier gratuit Gemini), 5 requêtes/jour en utilisation normale
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

log = logging.getLogger("commentary")

# API Gemini — endpoint officiel
# On utilise Flash-Lite (pas Flash) parce que Flash consomme tout le budget
# maxOutputTokens en "thinking interne" avant de produire la réponse visible,
# résultant en textes tronqués systématiquement. Flash-Lite n'a pas ce problème,
# écrit plus directement, et a même un quota supérieur (1000 RPD vs 250).
# Qualité suffisante pour une analyse éditoriale de 5-6 phrases.
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Rate limiting manuel : Flash-Lite autorise 15 req/min (= 4s minimum
# théorique entre chaque appel). En pratique les 5 appels par run sont
# très espacés des éventuels autres projets partageant le quota. 1.5s
# est un compromis rapide/sûr qui laisse 5x de marge sous la limite.
RATE_LIMIT_DELAY = 1.5

# Retry en cas de 429/503 : délais en secondes avant chaque nouvelle tentative
RETRY_DELAYS = [5.0, 12.0]  # total 17s d'attente max en cas de gros souci

# Répertoire des archives pour le contexte historique
ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "docs" / "data" / "archive"


SYSTEM_PROMPT = """Tu es journaliste spécialisé dans l'analyse des audiences TV internationales pour une newsletter professionnelle de veille (public : cadres dirigeants de l'audiovisuel, journalistes médias, chercheurs).

Ton style éditorial s'inspire du Monde Médias, des Jours, ou d'Acrimed : analytique, nuancé, contextualisé. Tu évites absolument :
- les superlatifs faciles ("énorme carton", "flop magistral", "cartonne")
- le style boulevard ou presse people
- les formules marketing ("incontournable", "phénomène")
- les conclusions vagues ("à suivre", "prochaine étape cruciale")

Tu privilégies :
- les observations structurelles (dynamique de case horaire, stratégie de contre-programmation, segmentation des publics)
- les comparaisons historiques précises avec les chiffres que je te fournis
- les tensions concurrentielles identifiables (TF1 vs M6, chaînes généralistes vs TNT)
- le vocabulaire professionnel du secteur (PDM, prime, case, access, lead-in)

Contraintes strictes et non négociables :
- Écris 5 à 6 phrases, en français, principalement au présent
- N'invente AUCUN chiffre, AUCUN programme, AUCUNE tendance que je ne t'ai pas fournis dans le contexte
- Si tu compares à la semaine précédente ou à la moyenne, base-toi UNIQUEMENT sur l'historique fourni
- Mentionne au moins un chiffre précis (téléspectateurs ou PDM)
- Ne commence PAS par "Le top 5 montre", "Les audiences du jour révèlent", "Cette soirée"
- Ne finis PAS par une conclusion générale type "À surveiller dans les prochains jours"
- Pas de point d'exclamation, pas d'emoji
- Évite les adverbes vagues ("particulièrement", "notamment", "largement")"""


USER_PROMPT_TEMPLATE = """**Audiences TV du {country_name} — {date_fr}**

Top {n} du prime time :
{today_rows}

{context_block}

{history_block}

Rédige maintenant une analyse de 5 à 6 phrases dans le style indiqué. Identifie si possible : (1) une tension concurrentielle, (2) une comparaison précise avec l'historique fourni, (3) une observation structurelle (stratégie de case, public cible, format). N'invente aucun chiffre."""


COUNTRY_CONTEXT = {
    "FR": """Contexte du marché français : 6 grandes chaînes gratuites en prime (TF1, France 2, France 3, France 5, M6, Arte) ; la TNT (W9, TMC, TFX, CSTAR, C8, Gulli, RMC, 6ter) fragmente l'audience depuis 2005. TF1 et M6 sont privées (Bouygues / RTL Group), les France Télévisions sont publiques. Cases-repères : 21h10 prime, access 19h-21h (Quotidien TMC vs Cyril Hanouna W9). Référents pro : Médiamétrie (panel Médiamat), PDA 4+ et FRDA-50 (Femmes Responsables Des Achats de moins de 50 ans, cible publicitaire-clé).""",
    "DE": """Contexte du marché allemand : les chaînes publiques Das Erste (ARD) et ZDF dominent historiquement sur les 50+, face aux privés RTL, Sat.1 et ProSieben (ProSiebenSat.1 Media). Les marqueurs clés sont le Tatort (polar dominical d'ARD, référence culturelle), les formats ProSieben ciblant les 14-49, et Wer wird Millionär (RTL). Prime time : 20h15. Mesure : AGF / GfK.""",
    "ES": """Contexte du marché espagnol : duopole historique Telecinco (Mediaset España) / Antena 3 (Atresmedia), avec La 1 (TVE publique) qui remonte depuis 2023. El Hormiguero (Antena 3, 21h45) est l'access le plus puissant. Supervivientes, La Isla de las Tentaciones, Pasapalabra structurent les grilles. Prime : 22h (dîner tardif). Mesure : Kantar Media.""",
    "IT": """Contexte du marché italien : duopole Rai (publique, 3 chaînes) / Mediaset (privé, 3 chaînes). Rai 1 leader historique, Canale 5 pour le divertissement et les fictions turques (Forbidden Fruit, etc.). La7 en niche politique/info. Prime : 21h20. Mesure : Auditel.""",
    "NL": """Contexte du marché néerlandais : NPO 1 (publique) vs RTL 4 (privée, Talpa Network). Marché très segmenté, audiences individuelles faibles (population 17M). Formats forts : Heel Holland Bakt (bake-off), Wie is de Mol, Married at First Sight. Mesure : SKO.""",
}


def format_date_fr(iso_date: str) -> str:
    """2026-04-22 → 22 avril 2026"""
    months = ["", "janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    try:
        y, m, d = iso_date.split("-")
        return f"{int(d)} {months[int(m)]} {y}"
    except (ValueError, IndexError):
        return iso_date


def format_viewers(n: int) -> str:
    """2741000 → '2,74 M' · 827000 → '827k'"""
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f} M".replace(".", ",")
    return f"{n//1000} k"


def format_today_rows(entries: list[dict]) -> str:
    """Formate les entrées du jour pour le prompt, avec catégorie et PDM."""
    lines = []
    for e in entries:
        cat = e.get("category", "autre")
        cat_part = f" [{cat}]" if cat and cat != "autre" else ""
        share = e.get("share", 0)
        share_part = f" · {share:.1f}% PDM" if share and share > 0 else ""
        viewers_part = format_viewers(e.get("viewers", 0))
        lines.append(
            f"  {e['rank']}. {e['channel']} — « {e['program']} »{cat_part} : "
            f"{viewers_part} téléspectateurs{share_part}"
        )
    return "\n".join(lines)


def load_history(country_code: str, current_date: str, n_days: int = 7) -> list[dict]:
    """
    Charge l'historique des N derniers jours pour un pays donné.
    Retourne une liste triée chronologiquement (plus ancien → plus récent).
    """
    try:
        current = date.fromisoformat(current_date)
    except ValueError:
        return []

    history = []
    for i in range(1, n_days + 1):
        d = current - timedelta(days=i)
        archive_path = ARCHIVE_DIR / f"{d.isoformat()}.json"
        if not archive_path.exists():
            continue
        try:
            data = json.loads(archive_path.read_text(encoding="utf-8"))
            country_data = data.get("countries", {}).get(country_code)
            if country_data and country_data.get("status") != "failed":
                history.append({
                    "date": d.isoformat(),
                    "entries": country_data.get("entries", []),
                })
        except (json.JSONDecodeError, ValueError):
            continue

    return sorted(history, key=lambda x: x["date"])


def format_history(history: list[dict]) -> str:
    """Formate l'historique pour le prompt, compact mais informatif."""
    if not history:
        return "Historique des 7 derniers jours : non disponible (premiers jours du dashboard)."

    lines = ["Historique — top 3 de chaque soir, 7 derniers jours :"]
    for day in history:
        date_fr = format_date_fr(day["date"])
        top3 = day["entries"][:3]
        if not top3:
            continue
        row = f"  {date_fr} : "
        row += " | ".join(
            f"{e['channel']} « {e['program'][:40]} » ({format_viewers(e.get('viewers', 0))}, "
            f"{e.get('share', 0):.1f}%)"
            for e in top3
        )
        lines.append(row)

    # Calcul d'un indicateur de tendance : chaîne dominante sur la période
    channel_wins = {}
    for day in history:
        if day["entries"]:
            leader = day["entries"][0]["channel"]
            channel_wins[leader] = channel_wins.get(leader, 0) + 1
    if channel_wins:
        dominant = max(channel_wins.items(), key=lambda x: x[1])
        lines.append(
            f"\nLeader du prime sur la semaine : {dominant[0]} "
            f"({dominant[1]}/{len(history)} soirées)."
        )

    return "\n".join(lines)


def build_context_block(country_code: str) -> str:
    """Retourne le bloc de contexte marché pour ce pays."""
    ctx = COUNTRY_CONTEXT.get(country_code)
    if not ctx:
        return ""
    return f"{ctx}\n"


def _call_gemini_with_retry(api_key: str, payload: dict,
                             country_code: str) -> Optional[str]:
    """
    Appelle l'API Gemini avec retry exponentiel sur 429 (rate limit).
    Retourne le texte généré, ou None si tous les retries échouent.
    """
    url = f"{GEMINI_API_URL}?key={api_key}"

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.post(url, json=payload, timeout=60)

            # Cas succès
            if r.status_code == 200:
                data = r.json()
                candidate = data.get("candidates", [{}])[0]
                text = (
                    candidate
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                ).strip()

                # Détection de troncature : si Gemini a coupé net, on logue
                # un avertissement pour qu'on sache qu'il faut ajuster maxOutputTokens
                finish_reason = candidate.get("finishReason", "")
                if finish_reason == "MAX_TOKENS":
                    log.warning(
                        f"{country_code} : réponse tronquée par MAX_TOKENS — "
                        f"envisager d'augmenter maxOutputTokens "
                        f"(texte actuel : {len(text)} chars, {len(text.split())} mots)"
                    )

                if text:
                    return text
                log.warning(f"{country_code} : réponse Gemini vide "
                           f"(finishReason={finish_reason})")
                return None

            # 429 → on attend et on réessaie
            if r.status_code == 429 and attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                log.warning(
                    f"{country_code} : 429 rate limit, retry #{attempt+1} dans {delay}s"
                )
                time.sleep(delay)
                continue

            # Autres erreurs HTTP
            r.raise_for_status()

        except requests.RequestException as e:
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                log.warning(
                    f"{country_code} : erreur réseau ({e}), retry #{attempt+1} dans {delay}s"
                )
                time.sleep(delay)
                continue
            log.warning(f"{country_code} : erreur API Gemini définitive — {e}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            log.warning(f"{country_code} : réponse Gemini mal formée — {e}")
            return None

    log.warning(f"{country_code} : tous les retries ont échoué")
    return None


def generate_commentary(country_code: str, country_data: dict) -> Optional[str]:
    """
    Génère un commentaire éditorial de 5-6 phrases pour un pays.
    Retourne None si erreur API ou si pas de clé configurée.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY non configuré — pas de commentaire généré")
        return None

    entries = country_data.get("entries", [])
    if not entries:
        log.warning(f"{country_code} : pas d'entrées, commentaire impossible")
        return None

    country_name = country_data.get("country_name", country_code)
    current_date = country_data.get("date", "")
    history = load_history(country_code, current_date, n_days=7)

    context_block = build_context_block(country_code)
    history_block = format_history(history)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        country_name=country_name,
        date_fr=format_date_fr(current_date),
        n=len(entries),
        today_rows=format_today_rows(entries),
        context_block=context_block,
        history_block=history_block,
    )

    payload = {
        "contents": [{
            "role": "user",
            "parts": [{"text": user_prompt}],
        }],
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}],
        },
        "generationConfig": {
            "temperature": 0.6,  # légèrement plus créatif qu'avant, sans dériver
            # 1000 tokens suffisent pour 5-6 phrases denses en français
            # (on a vu 733 chars / 115 mots tenir en largement moins).
            "maxOutputTokens": 1000,
            "topP": 0.9,
            # Désactive explicitement le "thinking interne" qui consommait
            # tout le budget avant de produire la réponse visible sur certains
            # modèles Gemini 2.5. Flash-Lite ne thinking pas par défaut mais
            # on le force pour blinder.
            "thinkingConfig": {
                "thinkingBudget": 0,
            },
        },
    }

    text = _call_gemini_with_retry(api_key, payload, country_code)
    if text:
        log.info(f"{country_code} : commentaire généré ({len(text)} chars, "
                 f"~{len(text.split())} mots)")
    return text


def _timed_generate(country_code: str, country_data: dict) -> Optional[str]:
    """Wrapper qui chronomètre l'appel pour diagnostiquer la lenteur."""
    t0 = time.monotonic()
    result = generate_commentary(country_code, country_data)
    elapsed = time.monotonic() - t0
    log.info(f"{country_code} : durée totale de génération = {elapsed:.1f}s")
    return result


def enrich_latest_with_commentaries(latest_path: Path, force: bool = False) -> None:
    """
    Charge latest.json, génère un commentaire pour chaque pays, puis réécrit le fichier.
    À appeler APRÈS tous les scrapers (une seule fois par run).

    Args:
        force: si True, regénère les commentaires même s'ils existent déjà
               (utile quand on change le prompt ou le modèle)
    """
    if not latest_path.exists():
        log.error(f"latest.json introuvable : {latest_path}")
        return

    data = json.loads(latest_path.read_text(encoding="utf-8"))
    countries = data.get("countries", {})

    log.info(f"Enrichissement de {len(countries)} pays (modèle: {GEMINI_MODEL}, "
             f"force={force})")
    t_start = time.monotonic()

    successes = 0
    failures = 0
    skipped = 0

    for i, (code, country_data) in enumerate(countries.items()):
        if country_data.get("status") == "failed":
            skipped += 1
            continue

        # Idempotence : on garde le commentaire existant sauf si force=True
        if not force and country_data.get("commentary"):
            log.info(f"{code} : commentaire déjà présent, on garde")
            skipped += 1
            continue

        # Rate-limiting manuel entre les pays (sauf le premier)
        if i > 0:
            time.sleep(RATE_LIMIT_DELAY)

        commentary = _timed_generate(code, country_data)
        if commentary:
            country_data["commentary"] = commentary
            successes += 1
        else:
            failures += 1

    # On réécrit le fichier même si certaines générations ont échoué
    # (les commentaires réussis seront sauvegardés)
    latest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total_elapsed = time.monotonic() - t_start
    log.info(
        f"Terminé en {total_elapsed:.1f}s : {successes} générés · "
        f"{failures} échecs · {skipped} conservés/skippés"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    # Par défaut, on regénère tout parce qu'on a changé de prompt/modèle.
    # Pour ne regénérer que les pays sans commentaire, passer --idempotent.
    force = "--idempotent" not in sys.argv
    latest = ROOT / "docs" / "data" / "latest.json"
    enrich_latest_with_commentaries(latest, force=force)
