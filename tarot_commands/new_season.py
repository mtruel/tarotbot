from discord.ext import commands  # type: ignore
import os
from datetime import datetime
import shutil
import json

from tarot_commands.paths import data_dir


@commands.command()
async def new_season(ctx, s='no'):
    """
    Commence une nouvelle saison (IRREVERSIBLE SANS ACCÈS AU SERVEUR)
    """
    now = datetime.today().strftime('%Y-%m-%d')
    # Les archives sont rangees avec les fichiers d'etat (data/ en local,
    # /data dans le conteneur, ou le dossier de travail est le volume).
    folder = os.path.join(data_dir(), now) + '/'
    if s != 'IAMSURE':
        await ctx.send('Are you sure though?')
        return

    if os.path.isdir(folder):
        ctx.send('Folder already exists, aborted!')
        return

    os.makedirs(folder, exist_ok=True)
    shutil.move('players.json', folder + 'players.json')
    shutil.move('history.json', folder + 'history.json')
    shutil.move('players_backup.json', folder + 'players_backup.json')

    if not os.path.isfile('players.json'):
        with open('players.json', 'w') as f:
            json.dump({}, f, indent=4)
        print('No players.json file, writing a blank one.')

    if not os.path.isfile('history.json'):
        with open('history.json', 'w') as f:
            json.dump([], f, indent=4)
        print('No history.json file, writing a blank one.')

    await ctx.send('New season started!')
