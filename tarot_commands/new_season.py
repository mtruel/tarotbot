from discord.ext import commands  # type: ignore
import os
from datetime import datetime
import shutil
from tarot_commands.state import save_history, save_player_names

from tarot_commands.paths import data_dir
from tarot_commands.help import error_message


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
        await ctx.send(error_message(
            'new_season',
            'Pour archiver la saison et repartir à zéro : `t/new_season IAMSURE`',
        ))
        return

    if os.path.isdir(folder):
        await ctx.send(error_message(
            'new_season',
            f'Une saison est déjà archivée aujourd’hui ({now}). Rien n’a été déplacé.',
        ))
        return

    os.makedirs(folder, exist_ok=True)
    # realpath : deplacer la cible d'un eventuel lien symbolique, pas le lien.
    # Compatibilite avec une saison encore au format historique.
    for name in ('players.json', 'history.json', 'players_backup.json'):
        if os.path.isfile(name):
            shutil.move(os.path.realpath(name), folder + name)

    save_player_names([])
    save_history([])

    await ctx.send('New season started!')
