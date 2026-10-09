from datetime import datetime

from tarot_commands.sessions import find_history_by_message_id, find_history_index_by_message_id
from tarot_commands.state import load_history, save_history


def update_history(scores, details):
    history = load_history()
    next_entry = {'time': datetime.now().strftime("%d/%m/%Y, %H:%M:%S")}
    next_entry.update(details)
    next_entry['scores'] = scores
    next_entry.setdefault('related_message_ids', [])
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
    new_entry['message_id'] = old.get('message_id')
    new_entry['time'] = old.get('time')
    new_entry['related_message_ids'] = list(old.get('related_message_ids') or [])
    new_entry['scores'] = scores
    history[index] = new_entry
    save_history(history)
    return new_entry


def append_related_message_id(canonical_or_any_id, score_message_id):
    """Ajoute l'id d'un message tableau à related_message_ids. Retourne True si ok."""
    history = load_history()
    entry = find_history_by_message_id(history, canonical_or_any_id)
    if entry is None:
        return False
    related = entry.setdefault('related_message_ids', [])
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
