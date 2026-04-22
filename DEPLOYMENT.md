# Guide de déploiement pas-à-pas

**Temps estimé : 15 minutes.** Aucune compétence technique préalable requise, suis juste les étapes.

## 1. Créer un compte GitHub

1. Va sur https://github.com et clique sur "Sign up"
2. Choisis un nom d'utilisateur (note-le, tu en auras besoin), ton email, un mot de passe
3. Vérifie ton email et active le compte

## 2. Créer le repository

1. Une fois connecté, clique sur le "+" en haut à droite → "New repository"
2. **Repository name** : `tv-audiences` (ou ce que tu veux)
3. **Description** : "Dashboard audiences TV internationales"
4. Laisse en **Public** (nécessaire pour GitHub Pages gratuit)
5. Coche "Add a README file"
6. Clique sur "Create repository"

## 3. Uploader les fichiers du projet

Tu as deux options.

### Option A — Interface web (recommandée pour débuter)

1. Sur la page du repo fraîchement créé, clique sur "Add file" → "Upload files"
2. Glisse-dépose tout le contenu du dossier `tv-audiences/` que je t'ai préparé
3. Message de commit : "Initial setup"
4. Clique sur "Commit changes"

⚠️ **Important** : GitHub ne permet pas d'uploader des dossiers vides ni la structure complète d'un coup via le glisser-déposer. Tu devras peut-être uploader dossier par dossier. Si c'est pénible, passe à l'option B.

### Option B — Ligne de commande Git (plus rapide si tu es à l'aise)

```bash
cd /chemin/vers/tv-audiences
git init
git add .
git commit -m "Initial setup"
git branch -M main
git remote add origin https://github.com/TON_USERNAME/tv-audiences.git
git push -u origin main
```

## 4. Activer GitHub Pages (pour héberger le dashboard)

1. Sur la page du repo, clique sur "Settings" (onglet tout en haut)
2. Dans le menu de gauche, clique sur "Pages"
3. Sous "Source", sélectionne **"Deploy from a branch"**
4. **Branch** : `main` / **Folder** : `/docs`
5. Clique "Save"

⏱ Attends 1-2 minutes. Ton dashboard sera accessible à l'adresse :
```
https://TON_USERNAME.github.io/tv-audiences/
```

Cette URL est **permanente**, tu peux la mettre en favori sur ton navigateur.

## 5. Activer GitHub Actions (pour l'automatisation quotidienne)

GitHub Actions est activé par défaut. Il y a juste une permission à vérifier :

1. Settings → Actions → General (menu gauche)
2. Section "Workflow permissions" (en bas de page)
3. Coche **"Read and write permissions"**
4. Clique "Save"

Sans ça, le bot GitHub ne pourrait pas pousser les données mises à jour.

## 6. Premier test manuel

Avant d'attendre le premier matin automatique, lance un test à la main :

1. Onglet "Actions" en haut du repo
2. Dans le menu de gauche : "Daily TV audience scrape"
3. Clique le bouton gris **"Run workflow"** à droite → confirme
4. Attends 1-2 minutes que ça tourne
5. Ouvre ton dashboard → les données devraient être à jour

## 7. Fréquence & coûts

- **GitHub Pages** : gratuit illimité pour les repos publics
- **GitHub Actions** : 2000 minutes/mois gratuites. Ce projet consomme ~5 min/jour = **150 min/mois**, soit 7,5 % du quota
- **Storage** : les fichiers JSON font quelques Ko chacun, l'archive sur 10 ans ferait moins de 10 Mo

## Si ça plante

Si un matin le dashboard n'est pas à jour :

1. Va sur Actions → regarde si le dernier run est en rouge
2. Clique dessus → tu verras les logs, avec l'erreur du ou des scrapers qui ont échoué
3. Les autres pays restent affichés normalement, seul celui qui a planté apparaîtra avec un badge ⚠

Le plus souvent, c'est que la structure HTML du site source a changé. Envoie-moi les logs et on met à jour le scraper.

## Personnalisation

- **Changer l'heure du scraping** : ouvre `.github/workflows/daily-scrape.yml`, modifie la ligne `cron: '0 8 * * *'` (format UTC, voir https://crontab.guru pour l'aide)
- **Changer le titre du dashboard** : ouvre `docs/index.html`, modifie la balise `<title>` et `<h1>`
- **Changer les couleurs** : dans `docs/index.html`, modifie les variables CSS au début (`--accent`, etc.)
