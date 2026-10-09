from math import sqrt

from discord.ext import commands
from table2ascii import table2ascii as t2a

from tarot_commands.state import compute_scores, load_history


def leaderboard_text():
    PLAYERS = compute_scores()

    sorted_players = dict(sorted(PLAYERS.items(), key=lambda item: item[1])[::-1])

    body = []
    for i, (k, v) in enumerate(sorted_players.items()):
        body.append([i + 1, k, int(v)])
    output = t2a(header=["Rank", "Name", "Points"], body=body, first_col_heading=True)
    return f"```\n{output}\n```"


def leaderboard2_text():
    HISTORY = load_history()
    PLAYERS = compute_scores(HISTORY)

    player_ratios = {p: 0 for p in PLAYERS}
    player_WL = {p: {"W": 0, "L": 0} for p in PLAYERS}
    player_means = {p: 0 for p in PLAYERS}
    player_standard_deviations = {p: 0 for p in PLAYERS}

    for player, v in PLAYERS.items():
        for hist in HISTORY:
            if player in hist["scores"]:
                if hist["scores"][player] >= 0:  # won the game
                    player_WL[player]["W"] += 1
                else:  # lost the game
                    player_WL[player]["L"] += 1
                player_standard_deviations[player] += hist["scores"][player] ** 2

        n_games = player_WL[player]["W"] + player_WL[player]["L"]
        player_means[player] = v / n_games if n_games > 0 else 0

        player_ratios[player] = int(player_means[player])

        player_standard_deviations[player] -= n_games * player_means[player] ** 2
        std = sqrt(player_standard_deviations[player] / (n_games - 1)) if n_games > 1 else 0.0
        player_standard_deviations[player] = int(std)

    sorted_players_ratios = dict(sorted(player_ratios.items(), key=lambda item: item[1])[::-1])
    body = []
    for i, (player, ratio) in enumerate(sorted_players_ratios.items()):
        body.append(
            [
                i + 1,
                player,
                ratio,
                str(int(player_WL[player]["W"])) + "/" + str(int(player_WL[player]["L"])),
                player_standard_deviations[player],
            ]
        )

    output = t2a(
        header=["Rank", "Name", "Points/Games", "W/L", "Standard deviation"],
        body=body,
        first_col_heading=True,
    )
    return f"```\n{output}\n```"


@commands.command()
async def leaderboard(ctx):
    """
    Montre le leaderboard.
    """
    text = leaderboard_text()
    await ctx.send(text)


@commands.command()
async def leaderboard2(ctx):
    """
    Montre le leaderboard à ratios.
    """
    text = leaderboard2_text()
    await ctx.send(text)
