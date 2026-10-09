"""Ancien t/undo : ne fait plus rien, redirige vers t/delete / t/edit."""

from discord.ext import commands


@commands.command()
async def undo(ctx, *args):
    """Remplacé par t/delete et t/edit."""
    await ctx.send(
        "`t/undo` n’existe plus.\n"
        "Pour supprimer une partie : `t/delete <id>` "
        "(ou en réponse au message / tableau), puis confirme avec `oui supprime` "
        "(ou `non` pour annuler).\n"
        "Pour corriger une partie : `t/edit <id> …` "
        "(bouton **Écraser**).\n"
        "`t/help delete` · `t/help edit`"
    )
