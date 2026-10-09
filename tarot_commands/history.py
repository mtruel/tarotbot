"""Historique des parties : ecriture dans history.json et commande t/history.

Les helpers d'ecriture (update_history, replace_history_entry, ...) sont ici.
Le format, le parsing et le rendu de t/history sont purs, dans history_view.
"""

from __future__ import annotations

from datetime import datetime

from discord.ext import commands

from tarot_commands.help import error_message
from tarot_commands.history_view import (
    clip_line,
    empty_message,
    format_entry_summary,
    parse_history_args,
    player_subtotal,
    render_history,
    select_history,
)
from tarot_commands.sessions import find_history_by_message_id, find_history_index_by_message_id
from tarot_commands.state import known_players, load_history, save_history

DISCORD_MAX_LEN = 2000


def update_history(scores, details):
    history = load_history()
    next_entry = {"time": datetime.now().strftime("%d/%m/%Y, %H:%M:%S")}
    next_entry.update(details)
    next_entry["scores"] = scores
    next_entry.setdefault("related_message_ids", [])
    history.append(next_entry)
    save_history(history)


def replace_history_entry(target_message_id, scores, details):
    """Remplace une partie en place. Conserve message_id, time, related_message_ids.

    Returns
    -------
    dict or None
        L'entrée mise à jour, ou None si aucune partie ne correspond.
    """
    history = load_history()
    index = find_history_index_by_message_id(history, target_message_id)
    if index is None:
        return None
    old = history[index]
    new_entry = dict(details)
    new_entry["message_id"] = old.get("message_id")
    new_entry["time"] = old.get("time")
    new_entry["related_message_ids"] = list(old.get("related_message_ids") or [])
    new_entry["scores"] = scores
    history[index] = new_entry
    save_history(history)
    return new_entry


def append_related_message_id(canonical_or_any_id, score_message_id):
    """Ajoute l'id d'un message tableau à related_message_ids. Retourne True si ok."""
    history = load_history()
    entry = find_history_by_message_id(history, canonical_or_any_id)
    if entry is None:
        return False
    related = entry.setdefault("related_message_ids", [])
    if score_message_id not in related:
        related.append(score_message_id)
        save_history(history)
    return True


def delete_history_entry(target_message_id):
    """Retire une partie de l'historique. Retourne l'entrée ou None si introuvable."""
    history = load_history()
    index = find_history_index_by_message_id(history, target_message_id)
    if index is None:
        return None
    removed = history.pop(index)
    save_history(history)
    return removed


# ---------------------------------------------------------------------------
# Commande t/history
# ---------------------------------------------------------------------------


def _truncated_header(header, total, hidden):
    return f"{header} - tronqué : {total} parties, {hidden} masquées"


def history_text(value="", history=None, now=None, max_len=DISCORD_MAX_LEN) -> str:
    """Texte complet de t/history, toujours <= max_len. Leve ValueError si argument invalide."""
    if history is None:
        history = load_history()
    if not history:
        return "Aucune partie dans l'historique."

    players = known_players(history)
    query = parse_history_args(value, players, now)

    if query.mode == "detail":
        detail_id = query.detail_id
        if detail_id is None:
            raise ValueError("Indique l'id d'une partie.")
        entry = find_history_by_message_id(history, detail_id)
        if entry is None:
            raise ValueError(f"Aucune partie liée à l'id `{detail_id}`.")
        canonical = entry.get("message_id", detail_id)
        return f"Partie `{canonical}`\n{format_entry_summary(entry)}"[:max_len]

    entries, header = select_history(query, history)
    if not entries:
        return f"{header}\n{empty_message(query)}"[:max_len]

    # En-tete et sous-total bornes : un nom de joueur enorme ne doit pas tout manger.
    side_len = max_len // 6
    header = clip_line(header, side_len)
    footer = (
        f"\n{clip_line(player_subtotal(entries, query.player), side_len)}" if query.player else ""
    )
    # Reserve la place de l'en-tete le plus long possible (cas tronque).
    worst_header = _truncated_header(header, len(entries), len(entries))
    budget = max_len - len(worst_header) - 1 - len(footer)
    body, hidden = render_history(entries, max_len=budget)
    if hidden:
        header = _truncated_header(header, len(entries), hidden)
    return f"{header}\n{body}{footer}"


@commands.command(name="history")
async def history(ctx, *, value=""):
    """Affiche l'historique récent, une ligne par partie."""
    try:
        text = history_text(value)
    except ValueError as exc:
        text = error_message("history", str(exc))
    await ctx.send(text)
