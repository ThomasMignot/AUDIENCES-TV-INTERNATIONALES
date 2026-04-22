# TV Audiences Dashboard

Dashboard automatisé des audiences TV prime time de 14 pays, mis à jour chaque matin.

## Vue d'ensemble

Le système fonctionne en trois couches :

1. **Scrapers Python** (dossier `scrapers/`) — un module par pays, qui va chercher les audiences de la veille sur la source primaire de chaque pays, et les écrit dans un format JSON standardisé.

2. **Dashboard statique** (dossier `docs/`) — une page HTML/JS qui lit les données et les affiche avec recherche, export CSV, champions trans-pays, calendrier historique et mode presse. Hébergée gratuitement via GitHub Pages.

3. **Automatisation GitHub Actions** (dossier `.github/workflows/`) — un job cron qui tourne chaque matin à 9h (heure de Paris), exécute tous les scrapers, et pousse les données mises à jour. Gratuit dans la limite de 2000 minutes/mois (ce projet utilise ~5 min/jour = 150 min/mois).

## Structure du projet

```
tv-audiences/
├── README.md                    # ce fichier
├── scrapers/
│   ├── common.py                # utilitaires partagés (normalisation, etc.)
│   ├── translations.py          # dictionnaire VO → VF des formats TV
│   ├── de_dwdl.py               # scraper Allemagne (DWDL.de)
│   ├── es_vertele.py            # [à venir] scraper Espagne
│   ├── it_davidemaggio.py       # [à venir] scraper Italie
│   └── ...                      # un fichier par pays
├── data/
│   ├── latest.json              # données les plus récentes (affichées par défaut)
│   └── archive/
│       ├── 2026-04-21.json      # historique jour par jour
│       ├── 2026-04-22.json
│       └── ...
├── docs/
│   └── index.html               # dashboard (servi par GitHub Pages)
└── .github/
    └── workflows/
        └── daily-scrape.yml     # automatisation quotidienne
```

## État actuel du MVP

- ✅ Dashboard v1 complet avec toutes les fonctionnalités
- ✅ Scraper Allemagne (DWDL.de) — preuve de concept
- ✅ Configuration GitHub Actions
- ⏳ 13 autres pays à implémenter (une conversation par lot)

## Déploiement

Voir `DEPLOYMENT.md` pour les étapes pas-à-pas.

## Ajout d'un nouveau pays

Voir `ADD_COUNTRY.md` pour le pattern à suivre.
