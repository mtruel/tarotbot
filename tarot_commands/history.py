from datetime import datetime

from tarot_commands.state import load_history, save_history


def update_history(scores, details):
    history = load_history()
    next_entry = {'time': datetime.now().strftime("%d/%m/%Y, %H:%M:%S")}
    next_entry.update(details)
    next_entry['scores'] = scores
    history.append(next_entry)
    save_history(history)
