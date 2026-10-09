# TarotBot

Bot Discord pour compter les points de Tarot entre amis, sur un serveur du homelab.

- Préfixe des commandes : `t/`
- Points enregistrés uniquement dans `data/history.json` ; `data/players.json` contient les noms des joueurs de la saison
- Plusieurs parties par saison, mise en forme d’un classement, courbes d’évolution, et saisie semi-automatique en texte libre
- Image Docker ARM64 (build `uv` multi-stage) + `docker compose` pour le run sur le Pi

> Documentation homelab : voir [`AGENTS.md`](../AGENTS.md).

## Origine et attribution

Ce bot est un projet d’origine externe, récupéré puis adapté pour le homelab.

- **Auteur** : Éloi Tanguy ([`eloitanguy`](https://github.com/eloitanguy), `tanguy.eloi@gmail.com`)
- **Dépôt upstream** : https://github.com/eloitanguy/tarotbot — *A Discord bot for Tarot scorekeeping*
- **Licence** : aucune licence n’est déclarée dans le dépôt upstream (droits réservés par défaut). Pour tout usage public ou redistribution, contacter l’auteur.


---

## Prérequis

- Python 3.12 (les `.pyc` fournis étaient en `cpython-312` ; le code tourne aussi sur les versions 3.x récentes)
- Un bot Discord et son token ([Discord Developer Portal](https://discord.com/developers/applications))
- [`uv`](https://docs.astral.sh/uv/) pour l’installation locale, ou Docker + `docker compose` pour le déploiement

Dépendances (déclarées dans [`pyproject.toml`](pyproject.toml), versions figées dans [`uv.lock`](uv.lock)) :

| Paquet | Rôle |
|---|---|
| `discord.py~=2.1.0` | API Discord (Slash non utilisé, commandes à préfixe) |
| `table2ascii` | Rendus des tableaux de scores / classements |
| `numpy`, `matplotlib` | Courbes (`t/curves`) |
| `unidecode` | Normalisation sans accents pour le parseur `t/auto` |

---

## Installation

Le bot doit être lancé via Docker (voir [Lancement](#lancement)). `uv` est utilisé pendant le build pour installer les dépendances.

### Configuration du token

Le token Discord est lu depuis la variable d’environnement `DISCORD_TOKEN`, chargée par le fichier `.env` à la racine du dépôt (fichier **hors Git**, cf. [`.gitignore`](.gitignore)). Un modèle est fourni dans [`.env.example`](.env.example) :

```bash
cp .env.example .env
# puis éditer .env :
# DISCORD_TOKEN=<TOKEN_DISCORD>
```

Le token doit être **régénéré** dans le portail Discord s’il a pu fuiter.

> Repli : si `DISCORD_TOKEN` n’est pas défini, le bot retombe sur `data/config.json` (`{"token": "<TOKEN_DISCORD>"}`) pour ne pas casser une installation existante. Cette solution est dépréciée au profit du `.env`.

En l’absence de `players.json` ou `history.json`, le bot crée une liste vide au démarrage. L’ancien `players.json` (dictionnaire de scores) est converti automatiquement en liste de noms après vérification des totaux et copie des fichiers dans `data/_pre_migration_<horodatage>/`. En cas d’écart avec l’historique, la migration s’arrête sans écraser les données.

### Intents Discord

Le bot active `message_content`. Dans le portail Discord, l’intent **Message Content** doit être activé, sinon toutes les commandes `t/...` sont ignorées.

---

## Lancement

### Avec Docker (recommandé en production)

Le build multi-stage ([`Dockerfile`](Dockerfile)) construit le venv avec `uv`, puis l’image finale ne contient que Python et ce venv :

```bash
docker compose up -d --build
docker compose logs -f tarotbot
# arrêt :
docker compose down
```

Points à connaître :

- Les données sont montées depuis `./data` (bind mount `./data:/data`) ; c’est le répertoire de travail du conteneur, car le bot lit/écrit ses JSON en chemins relatifs.
- Le conteneur tourne en UID/GID 1000 (`tarot`), donc `data/` doit appartenir à cet utilisateur sur l’hôte.
- `restart: unless-stopped`, `init: true`, `stop_grace_period: 10s`, `mem_limit: 512m`, logs JSON plafonnés à 3 × 10 Mo, et `TZ=Europe/Paris` pour que `datetime.now()` de `history.py` / `new_season.py` reste à l’heure locale.
- Aucun secret n’est embarqué dans l’image : le token est fourni au conteneur via la variable `DISCORD_TOKEN` lue depuis le `.env` (cf. [Configuration du token](#configuration-du-token)).
- Le fichier `.env` à la racine est chargé par `docker compose` (`env_file` optionnel) ; il est exclu du contexte de build par [`.dockerignore`](.dockerignore).

### Exécution et données

Ne pas démarrer le bot en direct (`python bot.py`, `uv run bot.py` ou `screen`). Docker le garde actif après fermeture de la session SSH. Les données se consultent directement dans `data/` ; le conteneur les voit sous `/data`.

Si `players.json` ou `history.json` est incohérent au démarrage (ancien format dont les totaux ne correspondent pas à l’historique), le bot s’arrête avec un message explicite sans rien écrire : corriger les fichiers dans `data/` puis relancer.

---

## Commandes

Toutes les commandes enregistrées dans [`bot.py`](bot.py) :

| Commande | Description |
|---|---|
| `t/help [commande]` | Liste les commandes, ou le détail d’une commande (`t/help auto`) |
| `t/ping` | Vérifie que le bot répond (`pong!`) |
| `t/add_player <nom>` | Ajoute un joueur au classement (1 joueur) |
| `t/add_players <nom1> <nom2> ...` | Ajoute plusieurs joueurs d’un coup |
| `t/leaderboard` | Classement par total de points |
| `t/leaderboard2` | Classement par points/partie, avec W/L et écart-type |
| `t/game <points>` | Saisie d’une partie via menus (enchère, bouts, primes, misères) |
| `t/auto <message>` | Saisie d’une partie en texte libre (voir syntaxe ci-dessous) |
| `t/descendante <p1> <p2> ...` | Saisie d’une descendante (points par joueur, puis noms via menus) |
| `t/edit <id> <auto…>` | Écrase une partie déjà enregistrée (ou en réponse à un message lié) |
| `t/delete <id>` | Supprime une partie (récap + `oui supprime` / `non` ; ou en réponse) |
| `t/new_season IAMSURE` | Archive la saison courante dans un dossier daté et repart à zéro |
| `t/poignees [n]` | Rappel des seuils de poignée selon le nombre de joueurs (défaut `5`) |
| `t/contrats` | Rappel des points à atteindre selon le nombre de bouts |
| `t/scores_descendante <n>` | Rappel des scores de descendante pour `n` joueurs |
| `t/curves` | Génère `curves.png` et l’envoie dans le salon |
| `t/export` | Envoie un zip des données (liste des joueurs, historique, saisons archivées ; sans les copies `_pre_*` ni `history.backup-*`) en pièce jointe |
| `t/export backup` | Snapshot local + zip du dépôt ; copie Drive (ajout seul) ensuite (message quand c’est fini) |
| `t/restore IAMSURE [backup]` | Restaure depuis un zip joint ou le dernier snapshot restic (admins, confirmation requise) |

### Nombre de joueurs

- `t/game` : 3, 4 ou 5 joueurs. Le **partenaire** n’est possible qu’à 5 joueurs.
- `t/descendante` : 3, 4 ou 5 joueurs.
- Les points de l’attaque vont de **0 à 91** (entiers) ; l’interface refuse le reste.

---

## Exemples

```text
t/add_players Alice Bob Carol

# Partie classique : l'attaque marque 45 points
t/game 45

# Descendante : 3 joueurs, points respectifs 20, 20, 51
t/descendante 20 20 51

# Voir le classement
t/leaderboard
t/leaderboard2

# Courbes de progression
t/curves

# Démarrer une nouvelle saison
t/new_season IAMSURE

# Corriger / supprimer une partie (id sous le tableau, ou réponse au message)
t/edit 1557730091864301699 Alice garde 50 2 vs Bob Carol
t/delete 1557730091864301699

# Rappels de règles
t/contrats
t/poignees 5
t/scores_descendante 4
```

### Saisie en texte libre — `t/auto`

Le parseur ([`game.autoparse`](tarot_commands/game.py)) accepte une phrase, puis affiche un récapitulatif à valider avec le bouton **Calcul**.

Édition du message `t/auto` : tant que **Calcul** n’a pas été cliqué, modifier le message met à jour le récapitulatif si le parse change. Une fois la partie enregistrée, une édition du même message est ignorée (avertissement dans le salon) — utiliser `t/edit <id> …` (ou une réponse au message / tableau) avec le bouton **Écraser**, ou `t/delete <id>` puis ressaisir. Tant que **Écraser** n’a pas été cliqué, modifier le message `t/edit` met à jour le récapitulatif (la cible d’origine est conservée). Plusieurs `t/auto` peuvent être ouverts en parallèle. L’id de partie s’affiche sous chaque tableau de scores.

Syntaxe imposée :

- **Attaque `vs` Défense**, le premier mot doit être un joueur existant (le preneur) :
  `Alice garde 45 2 vs Bob Carol`
- **Partenaire** (5 joueurs) : mot-clé `avec` (ou `with`)
- **Primes** : `prime attaque ...` / `prime défense ...` ; `prime` seul = attaque
- **Misères** : mot-clé `misere` / `miseres`
- **Descendante** : commencer par `desc` ou `descendante`, puis `nom score` répétés

```text
t/auto Alice garde 45 2 vs Bob Carol
t/auto Alice garde sans 50 1 vs Bob avec Carol prime attaque petit au bout
t/auto descendante Alice 20 Bob 20 Carol 51
```

Exemples de primes reconnues : `petite`, `garde`, `garde sans`, `garde contre`, `simple/double/triple poignée`, `petit au bout`, `chelem annoncé/non annoncé/chuté`, `misère`.

---

## Calcul des scores

Défini dans [`tarot_commands/rules.py`](tarot_commands/rules.py) et [`tarot_commands/game.py`](tarot_commands/game.py).

- Points à faire selon les bouts : `0 → 56`, `1 → 51`, `2 → 41`, `3 → 36` (`CONTRAT_PAR_BOUT`)
- Enchère : Petite ×1, Garde ×2, Garde Sans ×4, Garde Contre ×6
- Primes (poignées 20/30/40, petit au bout 10, chelem 400/200/−200)
- L’attaque touche `score × nombre de défenseurs`, réparti 2/3 preneur – 1/3 partenaire
- Misère : le joueur misériste reçoit +10 par joueur, chaque autre joueur −10

Une partie est validée par le bouton **Calcul** de l’interface. Les menus (sélecteurs) ont un timeout de 5 min ; le bouton de calcul, 3 min.

Discord limite un menu à 25 choix : au-delà, les menus de joueurs proposent les 25 joueurs ayant joué le plus récemment (puis les inscrits sans partie). `t/auto` reconnaît toujours tous les joueurs.

---

## Données

Tous les fichiers d’état vivent dans `data/` et sont **exclus de Git** par [`.gitignore`](.gitignore). `data/` est monté sur `/data` dans le conteneur, qui en fait son répertoire de travail.

- `players.json` : liste des noms inscrits pour la saison, sans points (`["Alice", "Bob"]`).
- `history.json` : liste des parties avec date, détails et scores (`{"time": "JJ/MM/AAAA, HH:MM:SS", "scores": {...}}`). **Seule source des points** : les classements et courbes additionnent ces scores à la demande.
- `curves.png` : courbe régénérée par `t/curves`.

Les joueurs inscrits sans partie apparaissent avec 0 point. Les noms présents uniquement dans l’historique sont aussi reconnus. `t/delete <id>` (ou en réponse) retire une partie après confirmation `oui supprime` (`non` pour annuler) ; les totaux sont recalculés, sans modifier la liste des joueurs. `players_backup.json` n’est plus utilisé ; les anciennes archives peuvent encore le contenir.

Formats JSON indicatifs :

```json
// players.json
["Alice", "Bob"]

// history.json
[
  { "time": "28/09/2026, 16:40:00", "scores": { "Alice": 80, "Bob": -40 } }
]
```

---

## Saisons

- `t/new_season IAMSURE` déplace `players.json` et `history.json` dans un dossier daté `data/AAAA-MM-JJ/`, puis repart avec une liste des joueurs et un historique vides. Un éventuel `players_backup.json` résiduel est archivé par compatibilité.
- Les dossiers de saison archivés du dépôt sont dans `data/` : `Saison1_2026-01-06/`, `Saison2_2026-03-02/`, `BackupSaison3_2026-03-05AvantTournoiTarot/`, `TournoiTarot05_03_26/`, `2026-05-04/`, `2026-07-24/`, ainsi que `testseason/`.
- [`season_stitcher.py`](season_stitcher.py) recombine plusieurs saisons (dont le nom contient `saison`) :

```bash
# Arrêter le bot avant de réécrire l’état courant :
docker compose stop tarotbot
docker compose run --rm -v "$PWD/season_stitcher.py:/app/season_stitcher.py:ro" \
  --entrypoint python tarotbot /app/season_stitcher.py
docker compose up -d
```

Le script concatène les `history.json` et réunit les noms des `players.json` de chaque saison (anciens dictionnaires et nouvelles listes acceptés), puis recalcule les points depuis l’historique, régénère `curves.png` et affiche les deux classements. Les archives sont lues depuis `data/` (`/data` dans Docker), surchargeable via `TAROTBOT_DATA_DIR`. **Il écrit dans `players.json` / `history.json`** : faire une copie de sauvegarde avant.

---

## Sauvegarde automatique (restic local → copie Google Drive)

Un snapshot **restic** de tout `data/` (hors secrets, artefacts et dépôt lui-même) est créé chaque jour à **3 h** dans un dépôt **local** (`/data/restic`, monté avec le volume `./data`). restic **chiffre** et **déduplique**. Ce dépôt local est ensuite **copié** vers Google Drive avec `restic copy`, et un zip de la dernière version (`tarotbot-latest.zip`) est déposé à côté.

### Fonctionnement

- `backup/backup.sh` exécute `python -m tarot_commands.backup_lib` : init du dépôt local si besoin, snapshot de `/data` (exclut `config.json`, `.env`, `token.json`, `curves.png`, `restic/`, `restore/`), rotation locale, **`restic copy`** vers `rclone:gdrive:<BACKUP_DEST_PATH>/restic`, rotation Drive, puis dépôt de `tarotbot-latest.zip`.
- Google Drive héberge un **second dépôt restic autonome**, alimenté uniquement par `restic copy` : **ajout seul**. Il n'y a donc jamais de suppression ni de réécriture côté Drive, et un dépôt local vide ou recréé ne peut pas écraser l'historique Drive. Chaque dépôt a sa propre rétention.
- La **rotation grand-père / père / fils** vit dans [`tarot_commands/backup_lib.py`](tarot_commands/backup_lib.py) : tous les snapshots sur **30 jours**, puis **le plus récent de chaque semaine** **pendant ~6 mois**, puis **le plus récent de chaque mois civil** (**sans limite**) au-delà.
- `t/export backup` : snapshot + zip du dépôt **local**, réponse Discord, puis **`restic copy`** vers Drive en arrière-plan.
- `backup/entrypoint.sh` démarre [`supercronic`](https://github.com/aptible/supercronic) en tâche de fond, puis le bot au premier plan.
- `backup/crontab` : `0 3 * * * /usr/local/bin/backup.sh`.
- `rclone`, `restic` et `supercronic` sont installés dans l’image ([`Dockerfile`](Dockerfile)) ; le token Google est fourni par variables d’environnement.

### Configuration

Le remote rclone est piloté par variables d’environnement, lues depuis le `.env` (cf. [Configuration du token](#configuration-du-token)) :

```bash
# Remote rclone : RCLONE_CONFIG_<REMOTE>_<OPTION> (ici le remote s'appelle gdrive)
RCLONE_CONFIG_GDRIVE_TYPE=drive
RCLONE_CONFIG_GDRIVE_SCOPE=drive
RCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID=<ID_DU_DOSSIER_DRIVE>
RCLONE_CONFIG_GDRIVE_TOKEN={"access_token":"…","token_type":"Bearer","refresh_token":"…","expiry":"…"}

# Mot de passe du dépôt restic (optionnel : un défaut est en dur dans le code).
# RESTIC_PASSWORD=<MOT_DE_PASSE_RESTIC>
```

Le token OAuth se génère **depuis un poste avec navigateur** (le Pi est *headless*) :

```bash
rclone authorize "drive"
```

Copier le JSON affiché dans `RCLONE_CONFIG_GDRIVE_TOKEN` (sans guillemets englobants dans le `.env`). `ROOT_FOLDER_ID` cible le dossier Drive de destination ; `BACKUP_DEST_PATH` (optionnel, défaut `TarotBot`) choisit un sous-dossier. Le dépôt restic **local** vit dans `/data/restic` (surchargeable par `RESTIC_REPOSITORY`) ; le dépôt **Drive** est `rclone:gdrive:<BACKUP_DEST_PATH>/restic`. Le zip de la dernière version est déposé en `<BACKUP_DEST_PATH>/tarotbot-latest.zip` (écrasé à chaque sauvegarde).

> `RESTIC_PASSWORD` n'est pas obligatoire : par défaut, le mot de passe `DEFAULT_PASSWORD` est défini dans [`tarot_commands/backup_lib.py`](tarot_commands/backup_lib.py). Pour utiliser un autre secret, le définir via `RESTIC_PASSWORD` (ou `RESTIC_PASSWORD_FILE` / `RESTIC_PASSWORD_COMMAND`) dans `.env`. Pour **le changer après coup**, utiliser `restic key passwd` (dépôt local) et `restic -r rclone:gdrive:TarotBot/restic key passwd` (Drive) : inutile de recréer les dépôts.

La politique de rotation peut être ajustée (optionnel) via `BACKUP_KEEP_RECENT_DAYS` (défaut `30`) et `BACKUP_KEEP_WEEKLY_DAYS` (défaut `183`). Le `prune` lourd sur Drive n'a lieu qu'un jour par semaine (`BACKUP_REMOTE_PRUNE_WEEKDAY`, défaut `6` = dimanche), pour limiter les appels à l'API Google ; les snapshots à retirer sont eux calculés à chaque sauvegarde.

### Déclencher / surveiller

```bash
# Lancer une sauvegarde immédiate, sans attendre 3 h :
./run_backup.sh          # conteneur jetable, ou :
docker compose exec tarotbot /usr/local/bin/backup.sh
# Suivre les logs (supercronic et le bot écrivent sur stdout) :
docker compose logs -f tarotbot
```

[`run_backup.sh`](run_backup.sh) enveloppe la première commande (`docker compose run --rm --entrypoint /usr/local/bin/backup.sh tarotbot`) depuis la racine du dépôt.

### Restauration

Trois façons, selon la situation. Les sources possibles :

- une **photo de `data/`** en zip : `t/export`, `tarotbot-latest.zip` sur le Drive, ou une ancienne archive ;
- un **snapshot restic** (parmi tout l’historique, y compris les versions passées) ;
- l’**archive complète du dépôt restic** (`t/export backup`) : elle contient *tout* l’historique, mais se relit avec `restic` (voir plus bas), pas comme un simple zip.

**1. Depuis Discord — `t/restore` (réservé aux administrateurs)**

```
t/restore IAMSURE          ← avec une archive .zip en pièce jointe
t/restore IAMSURE backup   ← depuis le dernier snapshot restic
```

Le bot valide la source, répond que l'opération est **destructive**, joint une **backup des données actuelles**, puis demande de taper exactement `ecraser_saison_en_cours` (ou `non` pour annuler ; budget 60 s ; une faute de frappe est signalée puis l'attente reprend). Après confirmation : `Restauration effectuée`.

**2. En ligne de commande — `run_restore.sh`** (quand le bot ne démarre plus)

```bash
./run_restore.sh ecraser_saison_en_cours /chemin/vers/backup.zip
./run_restore.sh ecraser_saison_en_cours backup          # dernier snapshot restic
./run_restore.sh ecraser_saison_en_cours <id-snapshot>   # snapshot restic précis
```

Le mot de confirmation doit être **exact**. Le script arrête le bot, restaure, puis le redémarre. Il partage la validation de `t/restore` (via [`tarot_commands/restore_lib.py`](tarot_commands/restore_lib.py)).

**3. Manuellement, depuis le dépôt restic (local ou Drive)**

```bash
docker compose exec -e RESTIC_PASSWORD=TAROTBOT_PASSWORD tarotbot \
  restic -r /data/restic snapshots
docker compose exec -e RESTIC_PASSWORD=TAROTBOT_PASSWORD tarotbot \
  restic -r /data/restic restore latest --target /tmp/restore
# copier players.json / history.json depuis
# /tmp/restore/ vers ./data, puis :
docker compose up -d
```

Si le dépôt **local** est perdu, Drive en contient une copie autonome, lisible directement :

```bash
docker compose exec -e RESTIC_PASSWORD=TAROTBOT_PASSWORD tarotbot \
  restic -r rclone:gdrive:TarotBot/restic snapshots
```

### `t/export` et `t/export backup`

- **`t/export`** : envoie une **photo de `data/`** (jeu + saisons archivées) en zip plat, sans secret ni dépôt restic. Sert à emporter l’état courant ou à le passer à `t/restore`.
- **`t/export backup`** : snapshot + zip du dépôt **local** (`data/restic`), puis copie Drive en arrière-plan (second message). Pour relire l’archive :

```bash
unzip tarotbot-restic-repo-*.zip -d /tmp/restore-repo
docker compose run --rm -v /tmp/restore-repo:/repo:ro \
    -e RESTIC_PASSWORD=TAROTBOT_PASSWORD --entrypoint sh tarotbot -c \
    'restic -r /repo snapshots && restic -r /repo restore latest --target /tmp/restore'
```

> Un dump lisible sans zipper le dépôt : `restic -r /data/restic snapshots` / `t/restore IAMSURE backup`.

### Ce que fait une restauration

- Restaure uniquement `history.json` et `players.json` (zip **plat**, zip **à dossier racine** ou snapshot restic). `history.json` est obligatoire ; si la liste des joueurs manque, elle est reconstruite depuis les noms de l’historique.
- **Valide avant d’écrire** : structure de l’historique, noms et scores numériques finis. Un ancien `players.json` contenant des totaux doit correspondre à la somme des scores (les inscrits à 0 sans partie sont acceptés), puis il est converti en liste de noms. En cas d’incohérence, rien n’est écrit.
- Ignore `players_backup.json` : les points et les annulations dépendent uniquement de `history.json`.
- **Snapshot** les données précédentes dans `data/_pre_restore_<horodatage>/` avant de basculer (écriture atomique), et ne garde que les 10 plus récents.
- N'écrase **pas** les dossiers de saisons archivées, et n'importe **jamais** un `config.json` provenant d'une ancienne archive (secret).

> Les écritures de la liste des joueurs et de l’historique sont atomiques : fichier temporaire dans le même dossier, puis remplacement. Une sauvegarde ne lit donc pas un JSON partiellement écrit. La capture des deux fichiers n’est pas une transaction, mais les points ne sont plus dupliqués.
>
> `rebuild_history.py` garde une copie ponctuelle `history.backup-*.json` avant d’enrichir l’historique depuis Discord. Le bot ne lit jamais cette copie ; elle reste un filet de sécurité pour cet outil manuel.

---

## Structure du projet

```text
tarobot-imb/
├── bot.py                     # point d'entrée : charge config, crée le client, enregistre les commandes
├── pyproject.toml             # dépendances (uv)
├── uv.lock                    # versions figées
├── Dockerfile                 # build multi-stage (uv -> venv) + rclone/restic/supercronic
├── docker-compose.yml         # run : restart, TZ, logs, montage de data/
├── .dockerignore
├── backup/                    # sauvegarde automatique + copie vers Google Drive
│   ├── backup.sh              # point d'entrée : python -m tarot_commands.backup_lib
│   ├── entrypoint.sh          # supercronic en fond, bot au premier plan
│   └── crontab                # planification (tous les jours à 3 h)
├── data/                      # état du bot (hors Git), monté sur /data
│   ├── restic/                # dépôt restic local (snapshots + rotation)
│   ├── players.json           # noms des joueurs de la saison
│   ├── history.json           # historique des parties
│   └── <AAAA-MM-JJ>/          # saisons archivées (noms + historique)
├── .env                       # token Discord + identifiants rclone/restic (hors Git)
├── .env.example               # modèle de .env
├── run_backup.sh              # déclenche une sauvegarde immédiate (conteneur jetable)
├── run_restore.sh             # restaure depuis un zip ou un snapshot restic (hors Discord)
├── curves.py                  # t/curves (matplotlib -> curves.png)
├── season_stitcher.py         # fusion de saisons (hors commande Discord)
├── tarot_commands/
│   ├── ping.py                # t/ping
│   ├── add_player.py          # t/add_player, t/add_players
│   ├── leaderboard.py         # t/leaderboard, t/leaderboard2 (points depuis history)
│   ├── state.py               # liste des joueurs, calcul des totaux, migration et écritures atomiques
│   ├── game.py                # t/game, t/descendante, t/auto + calcul des scores
│   ├── rules.py               # constantes (poignées, contrats, primes) + t/poignees/contrats/scores_descendante
│   ├── edit.py                # t/edit (écraser une partie)
│   ├── delete.py              # t/delete (supprimer une partie)
│   ├── undo.py                # t/undo (redirige vers delete / edit)
│   ├── new_season.py          # t/new_season
│   ├── history.py             # écriture / remplacement / suppression de history.json
│   ├── export.py              # t/export, t/export backup (dépôt restic complet)
│   ├── export_lib.py          # construction des zips de données (sans discord)
│   ├── restore.py             # t/restore (restauration avec confirmation)
│   ├── restore_lib.py         # validation + bascule partagées (sans discord)
│   ├── backup_lib.py          # restic local + copie Drive + zip (sans discord)
│   └── help.py                # t/help
```

---

## Tests de l’état et des commandes

Les tests utilisent des dossiers temporaires, des réponses Discord simulées et aucune connexion réseau : les données réelles de `/data` ne sont pas modifiées.

```bash
docker compose build
docker compose run --rm -v "$PWD/tests:/tests:ro" \
  -v "$PWD/season_stitcher.py:/app/season_stitcher.py:ro" \
  --entrypoint python tarotbot -m unittest discover -s /tests -v
```

Ils couvrent les totaux, la liste des joueurs, la migration, les écritures atomiques (droits conservés, liens symboliques suivis), la suppression de parties, l’ajout des joueurs, le parsing et les menus, les saisons, les exports et la restauration des anciens et nouveaux formats.

## Notes et limites

- Le bot ne fonctionne qu’en **commandes à préfixe** `t/` (pas de slash commands). L’aide par défaut de discord.py est désactivée : `t/help` liste les commandes, `t/help <commande>` envoie le détail.
- L’état est stocké en **globales de module** et les écritures JSON ne sont pas protégées par verrou : une seule instance à la fois, une saisie à la fois. Ne pas faire tourner le conteneur et un `uv run bot.py` en local en même temps, ils écriraient dans les mêmes fichiers de `data/`.
- `t/delete` (confirmation `oui supprime` / `non`), `t/edit` (bouton **Écraser**) et `t/new_season` (`IAMSURE`) sont **irréversibles** sans accès aux fichiers sur le serveur.
- `tarot_commands/rules.py` contient aussi `DESCENDANTE_SCORES`, utilisé uniquement pour l’affichage `t/scores_descendante` (le calcul réel se fait dans `game.calcul_score_descendante`).
