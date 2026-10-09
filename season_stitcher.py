import os

import curves
from tarot_commands import leaderboard
from tarot_commands.paths import data_dir
from tarot_commands.state import (
    known_players,
    load_history,
    load_player_names,
    save_history,
    save_player_names,
)

# TAROTBOT_DATA_DIR permet de choisir un dossier d'archives explicite.
ARCHIVES_DIR = os.environ.get("TAROTBOT_DATA_DIR") or data_dir()


def fuse_history_and_players(folder_list):
    history, player_names = [], []
    for folder in folder_list:
        season = os.path.join(ARCHIVES_DIR, folder)
        history.extend(load_history(os.path.join(season, "history.json")))
        players_path = os.path.join(season, "players.json")
        if os.path.isfile(players_path):
            player_names.extend(load_player_names(players_path))

    save_player_names(known_players(history, player_names))
    save_history(history)


def main():
    all_folders = os.listdir(ARCHIVES_DIR)
    season_folders = sorted(
        [
            s
            for s in all_folders
            if "saison" in s.lower() and os.path.isdir(os.path.join(ARCHIVES_DIR, s))
        ]
    )
    print(f"Fusion des saisons depuis {ARCHIVES_DIR}/ : {season_folders}")
    fuse_history_and_players(season_folders)
    curves.render_curves()
    print(leaderboard.leaderboard_text())
    print("\n\n\n\n")
    print(leaderboard.leaderboard2_text())


if __name__ == "__main__":
    main()
