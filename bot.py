import traceback

import discord
from discord.ext import commands
import json
from tarot_commands.ping import ping
from tarot_commands.add_player import add_player, add_players
from tarot_commands.leaderboard import leaderboard, leaderboard2
from tarot_commands.game import game, descendante, auto
from tarot_commands.rules import poignees, contrats, scores_descendante
from tarot_commands.undo import undo
from tarot_commands.new_season import new_season
from tarot_commands.help import explain_command_error, help, more_info
from curves import curves
import os

with open('config.json', 'r') as f:
    config = json.load(f)

if not os.path.isfile('players.json'):
    with open('players.json', 'w') as f:
        json.dump({}, f, indent=4)
    print('No players.json file, writing a blank one.')

if not os.path.isfile('history.json'):
    with open('history.json', 'w') as f:
        json.dump([], f, indent=4)
    print('No history.json file, writing a blank one.')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(intents=intents, command_prefix='t/', help_command=None)

bot.add_command(ping)
bot.add_command(add_player)
bot.add_command(leaderboard)
bot.add_command(leaderboard2)
bot.add_command(undo)
bot.add_command(game)
bot.add_command(descendante)
bot.add_command(poignees)
bot.add_command(contrats)
bot.add_command(scores_descendante)
bot.add_command(curves)
bot.add_command(auto)
bot.add_command(add_players)
bot.add_command(new_season)
bot.add_command(help)


@bot.event
async def on_command_error(ctx, error):
    message = explain_command_error(ctx, error)
    if message is None:
        traced = error.original if isinstance(error, commands.CommandInvokeError) else error
        traceback.print_exception(type(traced), traced, traced.__traceback__)
        name = ctx.command.name if ctx.command else 'help'
        message = (
            f'Erreur interne sur t/{name}, rien n’a été enregistré.\n'
            f'{more_info(name)}'
        )
    await ctx.send(message)


bot.run(config['token'])
