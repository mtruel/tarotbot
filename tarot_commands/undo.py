from discord.ext import commands

from tarot_commands.help import error_message
from tarot_commands.state import load_history, save_history


@commands.command()
async def undo(ctx, s='no'):
    """Retire la derniere partie de l'historique (IRREVERSIBLE)."""
    if s != 'IAMSURE':
        await ctx.send(error_message(
            'undo',
            'Pour annuler la dernière partie : `t/undo IAMSURE`',
        ))
        return

    history = load_history()
    if not history:
        await ctx.send(error_message(
            'undo', 'Aucune partie à annuler : l’historique est vide.',
        ))
        return

    save_history(history[:-1])
    await ctx.send('Undo successful!')
