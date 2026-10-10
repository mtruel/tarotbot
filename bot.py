import json
import os
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

from curves import curves
from tarot_commands.add_player import add_player, add_players
from tarot_commands.delete import delete
from tarot_commands.edit import EditOverwriteButton, edit, handle_edit_message_edit
from tarot_commands.export import export
from tarot_commands.game import (
    DescendanteCalculButton,
    GameCalculButton,
    auto,
    confirm_message_content,
    descendante,
    game,
    handle_auto_edit,
)
from tarot_commands.help import error_message, explain_command_error, help, more_info
from tarot_commands.history import history
from tarot_commands.leaderboard import leaderboard, leaderboard2
from tarot_commands.new_season import new_season
from tarot_commands.ping import ping
from tarot_commands.restore import restore
from tarot_commands.rules import rules
from tarot_commands.state import migrate_state
from tarot_commands.undo import undo

load_dotenv()


def load_token():
    """Récupère le token Discord depuis l'environnement, sinon config.json.

    La source recommandée est la variable DISCORD_TOKEN (fichier .env, hors
    Git). Le config.json reste accepté en repli pour ne pas casser l'existant.
    """
    token = os.getenv("DISCORD_TOKEN")
    if token:
        return token
    if os.path.isfile("config.json"):
        with open("config.json") as f:
            return json.load(f)["token"]
    raise SystemExit(
        "Aucun token Discord : définir DISCORD_TOKEN (fichier .env) "
        'ou fournir un config.json avec la clé "token".'
    )


token = load_token()

try:
    migrate_state()
except ValueError as exc:
    # Donnees incoherentes : rien n'a ete ecrit. Arret explicite plutot
    # qu'une trace brute a chaque redemarrage du conteneur.
    raise SystemExit(f"Etat invalide dans players.json/history.json : {exc}") from exc

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(intents=intents, command_prefix="t/", help_command=None)

bot.add_command(ping)
bot.add_command(add_player)
bot.add_command(leaderboard)
bot.add_command(leaderboard2)
bot.add_command(history)
bot.add_command(delete)
bot.add_command(edit)
bot.add_command(undo)
bot.add_command(game)
bot.add_command(descendante)
bot.add_command(rules)
bot.add_command(curves)
bot.add_command(auto)
bot.add_command(add_players)
bot.add_command(new_season)
bot.add_command(export)
bot.add_command(restore)
bot.add_command(help)


@bot.event
async def on_command_error(ctx, error):
    message = explain_command_error(ctx, error)
    if message is None:
        traced = error.original if isinstance(error, commands.CommandInvokeError) else error
        traceback.print_exception(type(traced), traced, traced.__traceback__)
        name = ctx.command.name if ctx.command else "help"
        message = f"Erreur interne sur t/{name}, rien n’a été enregistré.\n{more_info(name)}"
    await ctx.send(message)


@bot.event
async def on_message_edit(before, after):
    """Re-parse t/auto ou t/edit si la saisie est encore pending ; avertit si deja enregistree."""
    if after.author.bot:
        return
    if before.content == after.content:
        return

    action, payload = handle_edit_message_edit(after.id, after.content, after.author.id)
    if action != "ignore":
        if action == "updated":
            session = payload
            content = confirm_message_content(session)
            view = EditOverwriteButton(session.request_message_id)
            if session.confirm_message_id and after.channel:
                try:
                    confirm = await after.channel.fetch_message(session.confirm_message_id)
                    await confirm.edit(content=content, view=view)
                except discord.HTTPException:
                    await after.channel.send(content, view=view)
            return
        if action == "error":
            await after.channel.send(error_message("edit", payload))
        return

    action, payload = handle_auto_edit(after.id, after.content, after.author.id)

    if action == "updated":
        session = payload
        content = confirm_message_content(session)
        if session.kind == "descendante" or session.reparse.startswith("Descendante:\n"):
            view = DescendanteCalculButton(session.request_message_id)
        else:
            view = GameCalculButton(session.request_message_id)
        if session.confirm_message_id and after.channel:
            try:
                confirm = await after.channel.fetch_message(session.confirm_message_id)
                await confirm.edit(content=content, view=view)
            except discord.HTTPException:
                await after.channel.send(content, view=view)
        return

    if action == "error":
        await after.channel.send(error_message("auto", payload))
        return

    if action == "warn":
        await after.channel.send(
            f"L’édition de la partie {after.id} n’est pas prise en compte : "
            "elle est déjà enregistrée. Pour corriger : `t/edit <id> …` "
            "(bouton **Écraser**), ou `t/delete <id>` puis ressaisir."
        )


bot.run(token)
