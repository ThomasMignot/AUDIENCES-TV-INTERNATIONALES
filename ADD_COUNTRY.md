# Ajouter un nouveau pays

Ce guide décrit le pattern à suivre pour implémenter un nouveau scraper. Le scraper Allemagne (`scrapers/de_dwdl.py`) sert de modèle de référence.

## Anatomie d'un scraper

Chaque scraper doit fournir une fonction `run(target_date)` qui retourne un `CountryReport` (défini dans `common.py`). Il suit ce squelette :

```python
from common import (
    AudienceEntry, CountryReport,
    color_for, parse_share_percent, parse_viewers_millions,
    save_report, yesterday,
)
from translations import translate

COUNTRY_CODE = "XX"
COUNTRY_NAME = "Nom complet"
FLAG = "🏳"
SOURCE_NAME = "Nom du site · Rubrique"
SOURCE_URL = "https://..."

def find_article_url_for_date(target: date) -> str | None:
    """Trouve l'URL de l'article d'audiences du jour cible."""
    # ... requests.get + BeautifulSoup ...

def parse_article(url: str) -> list[AudienceEntry]:
    """Extrait les 5 premières entrées prime time de l'article."""
    # ... requests.get + parsing ...

def run(target_date=None):
    # orchestration standardisée (cf. de_dwdl.py)
    ...

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    report = run()
    save_report(report)
```

## Les 3 difficultés récurrentes

### 1. Identifier le bon article

Chaque site a sa convention :
- **DWDL (DE)** : slug contient "tvquoten" + jour de la semaine en allemand
- **VerTele (ES)** : articles datés avec URL `/audiencias/DD-MM-YYYY/`
- **Davide Maggio (IT)** : rubrique `/ascolti-tv` avec date dans le titre

Il faut inspecter le site et trouver le pattern. La stratégie générale : récupérer la page de rubrique qui liste les articles récents, puis filtrer par date.

### 2. Extraire les chiffres

Là encore, chaque site a son style :
- **DWDL** : prose rédigée (""3,42 Millionen (17,8 Prozent)"")
- **VerTele** : tableaux HTML structurés (plus facile)
- **Davide Maggio** : tableaux aussi mais avec notation italienne

Il faut choisir entre :
- **Parsing de prose** avec regex (cf. DWDL) : flexible mais fragile
- **Parsing de tableau** avec sélecteurs CSS (cf. VerTele) : robuste mais casse si le site change sa structure
- **Flux RSS/JSON-LD** si disponible : idéal mais rare

### 3. Normaliser

Chaque pays a ses unités :
- Allemagne : Millionen / Prozent
- Espagne : "millones" parfois abrégé "M", % avec virgule décimale
- UK : souvent en milliers avec "K" ou en millions avec "m"
- USA : ratings Nielsen (% de ménages) ET total viewers en millions

Les helpers `parse_viewers_millions()` et `parse_share_percent()` dans `common.py` gèrent les variantes courantes. Si un format exotique apparaît, ajouter une fonction dédiée.

## Checklist pour un nouveau scraper

- [ ] Inspecter le site source (quelle rubrique, comment sont rangés les articles, à quelle heure publient-ils ?)
- [ ] Copier `de_dwdl.py` en `xx_nomdusite.py`
- [ ] Adapter les constantes de tête (`COUNTRY_CODE`, etc.)
- [ ] Adapter `find_article_url_for_date()` au pattern du site
- [ ] Adapter `parse_article()` selon le format des données
- [ ] Ajouter les couleurs des chaînes locales dans `CHANNEL_COLORS` (common.py)
- [ ] Tester en local : `python scrapers/xx_nomdusite.py`
- [ ] Ajouter l'appel dans `.github/workflows/daily-scrape.yml`
- [ ] Commit, push, vérifier le prochain run automatique

## Ordre d'implémentation suggéré

Par difficulté croissante, en se basant sur la structure des sites :

**Faciles (tableaux HTML bien structurés)** :
1. Espagne — VerTele (tableau clair, formulation standard)
2. Italie — Davide Maggio (tableau structuré)
3. Portugal — Atelevisão (petits tableaux récurrents)

**Moyens (prose rédigée)** :
4. Allemagne — DWDL ✅ déjà fait
5. Pays-Bas — Broadcastmagazine
6. Australie — TV Tonight
7. Belgique FR — Télépro

**Difficiles (multi-sources, formats hétérogènes)** :
8. USA — Deadline + Programming Insider (pas toujours le même top 5)
9. UK — actuellement compte Twitter, à remplacer par un site (BARB data via un relais presse)
10. Brésil — Alta Definição (formulation spécifique)

**À surveiller au cas par cas** :
- Canada — sources fragmentées
- Danemark / Suède — publication parfois seulement hebdo
- Belgique FR / FL — chevauchement possible avec d'autres pays

## Gestion des pays sans source primaire simple

Pour certains pays (UK, Canada), il n'y a pas de site presse qui publie systématiquement le top 5 chaque matin. Deux stratégies :

**A. Scraper plusieurs sources et fusionner** — récupérer chez chaque source, dédupliquer par programme, garder les valeurs de la source la plus "officielle".

**B. Accepter un décalage** — pour les pays dont les audiences tombent à J+1 au lieu de J+0, afficher les audiences d'il y a 2 jours au lieu de la veille, avec un badge "J-2" explicite.

La décision se prend pays par pays selon ce qu'on trouve à l'audit.
