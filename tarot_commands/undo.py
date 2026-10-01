import os
from discord.ext import commands
import json

from tarot_commands.help import error_message


@commands.command()
async def undo(ctx, s='no'):
    """
    Retire la dernière partie du leaderboard et de l'historique (IRREVERSIBLE).
    """
    if s != 'IAMSURE':
        await ctx.send(error_message(
            'undo',
            'Pour annuler la dernière partie : `t/undo IAMSURE`',
        ))
        return

    if not os.path.isfile('players_backup.json'):
        await ctx.send(error_message(
            'undo',
            'Pas de sauvegarde à restaurer : aucune partie à annuler, '
            'ou players_backup.json est absent.',
        ))
        return

    with open('players_backup.json', 'r') as f:
        players = json.load(f)

    with open('players.json', 'w') as f:
        json.dump(players, f, indent=4)

    with open('history.json', 'r') as f:
        history = json.load(f)

    history = history[:-1]

    with open('history.json', 'w') as f:
        json.dump(history, f, indent=4)

    # Le backup doit decrire l'etat d'avant la donne desormais derniere.
    # Sinon un second undo retire l'historique sans retirer les points.
    backup = dict(players)
    if history:
        for name, score in history[-1]['scores'].items():
            backup[name] = backup.get(name, 0) - score

    with open('players_backup.json', 'w') as f:
        json.dump(backup, f, indent=4)

    await ctx.send('Undo successful!')
