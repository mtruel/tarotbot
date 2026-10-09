from discord.ext import commands

from tarot_commands.game import player_index, resolve_player
from tarot_commands.state import known_players, save_player_names


@commands.command()
async def add_player(ctx, player_name):
    """Rajoute le joueur [player_name] a la liste des joueurs de la saison."""
    players = known_players()
    existing = resolve_player(player_name, players, player_index(players))
    if existing:
        await ctx.send(f"{existing} is already listed!")
    else:
        players.append(player_name)
        save_player_names(players)
        await ctx.send(f"Successfully added {player_name}.")


@commands.command()
async def add_players(ctx, *, msg):
    """Rajoute les joueurs donnes (separes par espaces) a la liste des joueurs."""
    players = known_players()
    names = player_index(players)
    names_already_listed = []
    names_added = []

    for player_name in msg.split():
        existing = resolve_player(player_name, players, names)
        if existing:
            names_already_listed.append(existing)
        else:
            players.append(player_name)
            names[player_name.casefold()] = player_name
            names_added.append(player_name)

    save_player_names(players)
    if names_already_listed:
        await ctx.send(f"Players {names_already_listed} are already listed!")
    await ctx.send(f"Successfully added {names_added}.")
