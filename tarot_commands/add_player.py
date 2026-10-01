from discord.ext import commands  # type: ignore
import json

from tarot_commands.game import player_index, resolve_player


@commands.command()
async def add_player(ctx, player_name):
    """
    Rajoute le joueur [player_name] au leaderboard.
    """
    with open('players.json', 'r') as f:
        PLAYERS = json.load(f)

    existing = resolve_player(player_name, PLAYERS, player_index(PLAYERS))
    if existing:
        await ctx.send('{} is already listed!'.format(existing))

    else:
        PLAYERS[player_name] = 0

        with open('players.json', 'w') as f:
            json.dump(PLAYERS, f, indent=4)

        await ctx.send('Successfully added {}.'.format(player_name))


@commands.command()
async def add_players(ctx, *, msg):
    """
    Rajoute les joueurs donnés (séparés par espaces) au leaderboard.
    """
    with open('players.json', 'r') as f:
        PLAYERS = json.load(f)
    names = player_index(PLAYERS)
    names_already_listed = []
    names_added = []

    for player_name in msg.split(' '):
        existing = resolve_player(player_name, PLAYERS, names)
        if existing:
            names_already_listed.append(existing)

        else:
            PLAYERS[player_name] = 0
            names[player_name.casefold()] = player_name
            names_added.append(player_name)

    with open('players.json', 'w') as f:
        json.dump(PLAYERS, f, indent=4)

    if names_already_listed:
        await ctx.send(f'Players {names_already_listed} are already listed!')
    await ctx.send(f'Successfully added {names_added}.')
