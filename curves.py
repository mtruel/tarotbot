import matplotlib.pyplot as plt
import numpy as np
import json
from matplotlib import colormaps
from discord.ext import commands
import discord


def render_curves():
    with open('history.json', 'r') as f:
        HISTORY = json.load(f)

    with open('players.json', 'r') as f:
        PLAYERS = json.load(f)

    n_players = len(PLAYERS)
    n_games = len(HISTORY)
    sorted_players = dict(sorted(PLAYERS.items(), key=lambda item: item[1])[::-1])
    player_to_idx = {p: i for (i, p) in enumerate(sorted_players.keys())}

    scores = np.zeros((n_games + 1, n_players))  # placeholder first scores at 0
    played_games = {i: [] for i in range(n_players)}

    for t, hist in enumerate(HISTORY):
        delta = np.zeros(n_players)
        idxs = [player_to_idx[p] for p in hist['scores'].keys()]
        delta[idxs] = list(hist['scores'].values())
        scores[t + 1] = scores[t] + delta
        for i in idxs:
            played_games[i].append(t + 1)

    cm = colormaps['gist_ncar'].resampled(3 * n_players)
    fig = plt.figure(figsize=(21, 12), dpi=150)
    ends = []
    for p, i in player_to_idx.items():
        color = cm(1 - (i + 1)/(n_players + 1))
        plt.plot(
            scores[:, i],
            label=p,
            color=color,
            marker='o',
            markersize=3,
            markeredgewidth=0,
            markevery=played_games[i],
        )
        ends.append((float(scores[-1, i]), p, color))

    fig.canvas.draw()
    ax = plt.gca()
    bbox = ax.get_window_extent()
    min_gap = (8 * fig.dpi / 72) * (ax.get_ylim()[1] - ax.get_ylim()[0]) / bbox.height
    order = np.argsort([y for y, _, _ in ends])
    label_y = np.array([y for y, _, _ in ends], dtype=float)
    placed = label_y[order].copy()
    for j in range(1, len(placed)):
        if placed[j] - placed[j - 1] < min_gap:
            placed[j] = placed[j - 1] + min_gap
    label_y[order] = placed

    for (_, p, color), text_y in zip(ends, label_y):
        plt.text(
            n_games,
            text_y,
            '  ' + p,
            va='center',
            ha='left',
            fontsize=8,
            color=color,
            clip_on=False,
        )

    plt.legend(loc='center left')
    plt.title('Le jeu tourne')
    plt.xlabel('nombre de parties')
    plt.ylabel('score')
    plt.grid(True, alpha=0.4)
    plt.gca().set_axisbelow(True)
    plt.savefig("curves.png", format="png", bbox_inches="tight")


@commands.command()
async def curves(ctx):
    """
    Renders and shows the entire play history as curves
    """
    render_curves()

    with open('curves.png', 'rb') as f:
        picture = discord.File(f)

    await ctx.send(file=picture)


if __name__ == "__main__":
    render_curves()
