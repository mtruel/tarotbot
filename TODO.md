# TODO — TarotBot

Tâches d’industrialisation du bot (voir [`README.md`](README.md) pour le fonctionnement actuel).

- [ ] **Dockerfile pour le run** — image ARM64 pour le Pi, `config.json` monté ou injecté via variable d’environnement, `docker compose` avec `restart: unless-stopped`, sans embarquer le token dans l’image.
- [ ] **Migration conda → uv** — remplacer l’environnement conda d’origine par `uv` : générer `pyproject.toml` + `uv.lock` depuis [`requirements.txt`](requirements.txt), documenter `uv sync` / `uv run bot.py`, et retirer toute référence conda.
- [ ] **Backup des données** — sauvegarder `players.json`, `players_backup.json` et `history.json` automatiquement (snapshot horodaté ou envoi vers le stockage du homelab), avec rotation et restauration documentée.
- [ ] **Secret dans un fichier `.env`** — ne plus lire le token depuis `config.json` : le déplacer dans un `.env` (gitignoré), fournir un `.env.example`, charger la variable côté bot (`python-dotenv` ou variable d’environnement), et **régénérer le token** qui a fuité dans l’archive.
- [ ] **Ajouter des tests** — couvrir le calcul des scores (`calcul_scores`, `calcul_score_descendante`, `affecte_miseres`), le parseur `t/auto` (`autoparse`) et les mises à jour JSON (`update_leaderboard`, `update_history`), sans dépendance à Discord ; ajouter `pytest` et une commande pour lancer la suite.
- [ ] **Dissocier les données des saisons et du jeu** — séparer l’état des saisons (dates, rosters, classements par saison) des données de jeu proprement dites (`history.json`, scores, parties), pour pouvoir changer de saison sans réécrire l’historique global ni risquer de mélanger les classements de saisons différentes.
- [ ] **Réparer la commande help** — `tarot_commands/h.py` n’est pas importé dans `bot.py` et sa liste est obsolète (`t/undo_leaderboard`/`t/undo_history` n’existent plus ; `t/auto`, `t/descendante`, `t/curves`, `t/add_players`, `t/new_season`, `t/leaderboard2`, `t/scores_descendante` manquants). Le brancher et le mettre à jour, ou le supprimer.
