"""
Module de génération de commentaires éditoriaux par pays.

Utilise Google Gemini 1.5 Flash (gratuit, 1500 req/jour) pour rédiger
3-4 phrases d'analyse par pays à partir des données du jour + archive 7 derniers jours.

Politique :
- Style "Médiapart" : analytique, avec nuances
- Jamais d'invention : le modèle ne peut parler QUE de ce qu'on lui fournit
- En cas d'erreur API : on retourne None, le scraper continue sans synthèse
- Coût : ~0 € (tier gratuit Gemini)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

log = logging.getLogger("commentary")

# API Gemini — endpoint officiel
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Répertoire des archives pour le contexte historique
ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "docs" / "data" / "archive"


SYSTEM_PROMPT = """Tu es un analyste spécialisé en audiences TV internationales. Tu écris pour une newsletter professionnelle de veille.

Ton style : analytique et nuancé, comme Médiapart ou Le Monde Médias. Tu évites le superlatif facile, les formules marketing, le style "boulevard". Tu privilégies les observations structurelles (concurrence entre chaînes, tendances, segments de public).

Contraintes strictes :
- Écris 3 à 4 phrases, en français, au présent
- Parle UNIQUEMENT des données que je te fournis. N'invente AUCUN chiffre, AUCUN programme, AUCUNE tendance que je ne t'ai pas donnée
- Si tu compares à "la moyenne" ou "la semaine précédente", base-toi uniquement sur l'historique fourni
- Ne commence PAS par "Le top 5 montre..." ou "Les audiences du jour..."
- Ne finis PAS par des conclusions générales type "À surveiller dans les prochains jours"
- Reste factuel mais pas plat : tu peux noter une tension concurrentielle, une performance notable, un écart atypique"""


USER_PROMPT_TEMPLATE = """Audiences TV de {country_name} du {date_fr}.

Top {n} du prime time :
{today_rows}

Historique des 7 derniers jours pour comparaison :
{history}

Rédige 3-4 phrases d'analyse dans le style indiqué."""


def format_date_fr(iso_date: str) -> str:
    """2026-04-22 → 22 avril 2026"""
    months = ["", "janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    y, m, d = iso_date.split("-")
    return f"{int(d)} {months[int(m)]} {y}"


def format_viewers(n: int) -> str:
    """ 2741000 → '2,74 M' · 827000 → '827k' """
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f} M".replace(".", ",")
    return f"{n//1000} k"


def format_today_rows(entries: list[dict]) -> str:
    """Formate les entrées du jour pour le prompt."""
    lines = []
    for e in entries:
        cat = e.get("category", "autre")
        cat_part = f" [{cat}]" if cat != "autre" else ""
        share_part = f" · {e['share']:.1f}% PDM" if e.get("share", 0) > 0 else ""
        lines.append(
            f"  {e['rank']}. {e['channel']} — {e['program']}{cat_part} : "
            f"{format_viewers(e['viewers'])} téléspectateurs{share_part}"
        )
    return "\n".join(lines)


def load_history(country_code: str, current_date: str, n_days: int = 7) -> list[dict]:
    """
    Charge l'historique des N derniers jours pour un pays donné.
    Retourne une liste triée chronologiquement.
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
    """Formate l'historique pour le prompt (compact)."""
    if not history:
        return "Aucun historique disponible."
    lines = []
    for day in history:
        date_fr = format_date_fr(day["date"])
        top3 = day["entries"][:3]
        row = f"  {date_fr} — "
        row += " | ".join(
            f"{e['channel']} {e['program'][:30]} ({format_viewers(e['viewers'])})"
            for e in top3
        )
        lines.append(row)
    return "\n".join(lines)


def generate_commentary(country_code: str, country_data: dict) -> Optional[str]:
    """
    Génère un commentaire éditorial de 3-4 phrases pour un pays.
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

    user_prompt = USER_PROMPT_TEMPLATE.format(
        country_name=country_name,
        date_fr=format_date_fr(current_date),
        n=len(entries),
        today_rows=format_today_rows(entries),
        history=format_history(history),
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
            "temperature": 0.5,
            "maxOutputTokens": 300,
        },
    }

    try:
        r = requests.post(
            f"{GEMINI_API_URL}?key={api_key}",
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        ).strip()
        if not text:
            log.warning(f"{country_code} : réponse Gemini vide")
            return None
        log.info(f"{country_code} : commentaire généré ({len(text)} chars)")
        return text
    except requests.RequestException as e:
        log.warning(f"{country_code} : erreur API Gemini — {e}")
        return None
    except (KeyError, IndexError, ValueError) as e:
        log.warning(f"{country_code} : réponse Gemini mal formée — {e}")
        return None


def enrich_latest_with_commentaries(latest_path: Path) -> None:
    """
    Charge latest.json, génère un commentaire pour chaque pays, puis réécrit le fichier.
    À appeler APRÈS tous les scrapers (une seule fois par run).
    """
    if not latest_path.exists():
        log.error(f"latest.json introuvable : {latest_path}")
        return

    data = json.loads(latest_path.read_text(encoding="utf-8"))
    countries = data.get("countries", {})

    for code, country_data in countries.items():
        if country_data.get("status") == "failed":
            continue
        # Ne regénère que s'il n'y a pas déjà un commentaire (idempotent)
        existing = country_data.get("commentary")
        if existing:
            log.info(f"{code} : commentaire déjà présent, on garde")
            continue
        commentary = generate_commentary(code, country_data)
        if commentary:
            country_data["commentary"] = commentary

    latest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"latest.json enrichi avec les commentaires")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    latest = ROOT / "docs" / "data" / "latest.json"
    enrich_latest_with_commentaries(latest)
