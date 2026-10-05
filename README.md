# TarotBot

Bot Discord pour compter les points de Tarot entre amis, sur un serveur du homelab.

- Préfixe des commandes : `t/`
- Scores persistés dans des fichiers JSON, dans `data/` (`players.json`, `history.json`)
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

Avec `uv` (recommandé) :

```bash
uv sync
# exécution :
uv run bot.py
```

### Configuration du token

Le token Discord est lu depuis la variable d’environnement `DISCORD_TOKEN`, chargée par le fichier `.env` à la racine du dépôt (fichier **hors Git**, cf. [`.gitignore`](.gitignore)). Un modèle est fourni dans [`.env.example`](.env.example) :

```bash
cp .env.example .env
# puis éditer .env :
# DISCORD_TOKEN=<TOKEN_DISCORD>
```

Le token doit être **régénéré** dans le portail Discord s’il a pu fuiter.

> Repli : si `DISCORD_TOKEN` n’est pas défini, le bot retombe sur `data/config.json` (`{"token": "<TOKEN_DISCORD>"}`) pour ne pas casser une installation existante. Cette solution est dépréciée au profit du `.env`.

En l’absence de `players.json` ou `history.json`, le bot crée automatiquement un fichier vide au démarrage.

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

### En direct (sans Docker)

```bash
uv run bot.py
```

Ou via le script fourni [`run_bot.sh`](run_bot.sh) :

```bash
sh run_bot.sh
```

> Lancé depuis la racine du dépôt, le bot utilise les JSON de `data/` via les liens symboliques `players.json`, `players_backup.json` et `history.json` (et lit le token via le `.env`) : les mêmes données que celles du conteneur.

> `run_bot.sh` n’a pas de shebang valide (la première ligne est `#!` seule) : le lancer avec `sh`, pas `./run_bot.sh`.

### En session détachée (`screen`)

Pour garder le bot actif après fermeture du terminal SSH :

```bash
screen -S tarotbot
# dans la session :
uv run bot.py       # ou: sh run_bot.sh
# détacher : CTRL+A puis D
# ré-attacher plus tard :
screen -r tarotbot
```

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
| `t/undo IAMSURE` | Annule la dernière partie (classement + historique) |
| `t/new_season IAMSURE` | Archive la saison courante dans un dossier daté et repart à zéro |
| `t/poignees [n]` | Rappel des seuils de poignée selon le nombre de joueurs (défaut `5`) |
| `t/contrats` | Rappel des points à atteindre selon le nombre de bouts |
| `t/scores_descendante <n>` | Rappel des scores de descendante pour `n` joueurs |
| `t/curves` | Génère `curves.png` et l’envoie dans le salon |

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

# Annuler la dernière saisie / démarrer une nouvelle saison
t/undo IAMSURE
t/new_season IAMSURE

# Rappels de règles
t/contrats
t/poignees 5
t/scores_descendante 4
```

### Saisie en texte libre — `t/auto`

Le parseur ([`game.autoparse`](tarot_commands/game.py)) accepte une phrase, puis affiche un récapitulatif à valider avec le bouton **Calcul**.

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

---

## Données

Tous les fichiers d’état vivent dans `data/` depuis la conteneurisation, et sont **exclus de Git** par [`.gitignore`](.gitignore). À la racine du dépôt, `players.json`, `players_backup.json` et `history.json` sont des liens symboliques vers `data/`, pour que le bot lancé à la main trouve les mêmes fichiers que dans le conteneur (`data/` est monté sur `/data`) :

| Fichier | Contenu |
|---|---|
| `players.json` | Scores cumulés par joueur (`{"Alice": 123, ...}`) |
| `players_backup.json` | Sauvegarde avant la dernière mise à jour (utilisée par `t/undo`) |
| `history.json` | Liste des parties : `{"time": "JJ/MM/AAAA, HH:MM:SS", "scores": {...}}` |
| `curves.png` | Courbe générée par `t/curves` (à la racine du dossier) |

Formats JSON indicatifs :

```json
// players.json
{ "Alice": 120, "Bob": -35 }

// history.json
[
  { "time": "28/09/2026, 16:40:00", "scores": { "Alice": 80, "Bob": -40 } }
]
```

---

## Saisons

- `t/new_season IAMSURE` déplace `players.json`, `history.json` et `players_backup.json` dans un dossier daté `data/AAAA-MM-JJ/`, puis repart sur des fichiers vides.
- Les dossiers de saison archivés du dépôt sont dans `data/` : `Saison1_2026-01-06/`, `Saison2_2026-03-02/`, `BackupSaison3_2026-03-05AvantTournoiTarot/`, `TournoiTarot05_03_26/`, `2026-05-04/`, `2026-07-24/`, ainsi que `testseason/`.
- [`season_stitcher.py`](season_stitcher.py) recombine plusieurs saisons (dont le nom contient `saison`) :

```bash
uv run season_stitcher.py
```

Le script concatène les `history.json`, additionne les `players.json` de chaque saison (lus depuis `data/`, surchargeable via `TAROTBOT_DATA_DIR`), puis régénère `curves.png` et affiche les deux classements en console. **Il écrit dans `players.json` / `history.json`** : faire une copie de sauvegarde avant.

---

## Structure du projet

```text
tarobot-imb/
├── bot.py                     # point d'entrée : charge config, crée le client, enregistre les commandes
├── pyproject.toml             # dépendances (uv)
├── uv.lock                    # versions figées
├── Dockerfile                 # build multi-stage (uv -> venv)
├── docker-compose.yml         # run : restart, TZ, logs, montage de data/
├── .dockerignore
├── data/                      # état du bot (hors Git), monté sur /data
│   ├── players.json           # scores cumulés
│   ├── players_backup.json    # sauvegarde avant la dernière mise à jour
│   ├── history.json           # historique des parties
│   └── <AAAA-MM-JJ>/          # saisons archivées (players/history/backup)
├── .env                       # token Discord (hors Git)
├── .env.example               # modèle de .env
├── config.json -> data/…      # liens symboliques vers data/ pour le run local
├── run_bot.sh                 # lancement simple
├── curves.py                  # t/curves (matplotlib -> curves.png)
├── season_stitcher.py         # fusion de saisons (hors commande Discord)
├── tarot_commands/
│   ├── ping.py                # t/ping
│   ├── add_player.py          # t/add_player, t/add_players
│   ├── leaderboard.py         # t/leaderboard, t/leaderboard2, mise à jour des scores
│   ├── game.py                # t/game, t/descendante, t/auto + calcul des scores
│   ├── rules.py               # constantes (poignées, contrats, primes) + t/poignees/contrats/scores_descendante
│   ├── undo.py                # t/undo
│   ├── new_season.py          # t/new_season
│   ├── history.py             # écriture de history.json
│   └── help.py                # t/help
```

---

## Notes et limites

- Le bot ne fonctionne qu’en **commandes à préfixe** `t/` (pas de slash commands). L’aide par défaut de discord.py est désactivée : `t/help` liste les commandes, `t/help <commande>` envoie le détail.
- L’état est stocké en **globales de module** et les écritures JSON ne sont pas protégées par verrou : une seule instance à la fois, une saisie à la fois. Ne pas faire tourner le conteneur et un `uv run bot.py` en local en même temps, ils écriraient dans les mêmes fichiers de `data/`.
- `t/undo` et `t/new_season` sont **irréversibles** sans accès aux fichiers sur le serveur ; le garde-fou est l’argument `IAMSURE`.
- `tarot_commands/rules.py` contient aussi `DESCENDANTE_SCORES`, utilisé uniquement pour l’affichage `t/scores_descendante` (le calcul réel se fait dans `game.calcul_score_descendante`).
