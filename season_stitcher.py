import curves
import json
import os
from tarot_commands import leaderboard
from tarot_commands.paths import data_dir

# Les archives de saisons vivent avec les fichiers d'etat (data/ en local,
# /data dans le conteneur). TAROTBOT_DATA_DIR force un dossier precis.
ARCHIVES_DIR = os.environ.get('TAROTBOT_DATA_DIR') or data_dir()


def fuse_history_and_players(folder_list):
    history, players = [], {}

    for folder in folder_list:

        # concatenante histories, assuming they are given chronologically
        with open(os.path.join(ARCHIVES_DIR, folder, 'history.json'), 'r') as f:
            history.extend(json.load(f))

        # final score of each player is the sum of their season scores
        with open(os.path.join(ARCHIVES_DIR, folder, 'players.json'), 'r') as f:
            players_dict = json.load(f)
            for (player, score) in players_dict.items():
                if player in players:
                    players[player] += score
                else:
                    players[player] = score

    with open('players.json', 'w') as f:
        json.dump(players, f, indent=4)
    with open('history.json', 'w') as f:
        json.dump(history, f, indent=4)


all_folders = os.listdir(ARCHIVES_DIR)
# les dossiers s'appellent Saison1_…, BackupSaison3_… : filtre insensible à la casse
season_folders = sorted([s for s in all_folders if 'saison' in s.lower()])
print(f'Fusion des saisons depuis {ARCHIVES_DIR}/ : {season_folders}')
fuse_history_and_players(season_folders)
curves.render_curves()
print(leaderboard.leaderboard_text())
print('\n\n\n\n')
print(leaderboard.leaderboard2_text())
