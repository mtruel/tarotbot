"""Etat de la saison : noms dans players.json, points uniquement dans history.json.

Module stdlib partage par le bot, les scripts et la restauration. Les anciens
players.json (dictionnaires de scores) restent lisibles pour les archives.
"""

import json
import math
import os
import shutil
import tempfile
from datetime import datetime


def normalize_player_names(data):
    """Accepte une liste de noms ou les cles d'un ancien dictionnaire."""
    if isinstance(data, dict):
        data = list(data)
    if not isinstance(data, list) or any(
        not isinstance(name, str) or not name.strip() for name in data
    ):
        raise ValueError('players.json doit contenir une liste de noms non vides.')
    return list(dict.fromkeys(data))


def validate_history(history):
    """Refuse un historique mal forme avant toute migration/restauration."""
    if not isinstance(history, list):
        raise ValueError('history.json doit contenir une liste de parties.')
    for game in history:
        if not isinstance(game, dict) or not isinstance(game.get('scores'), dict):
            raise ValueError('Chaque partie doit contenir un objet scores.')
        for name, score in game['scores'].items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Chaque score doit appartenir a un joueur nomme.')
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score)):
                raise ValueError(f'Score invalide pour {name}.')
    return history


def _read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    """Ecriture atomique d'un JSON (partagee avec la restauration)."""
    # Resoudre les liens de la racine du depot : remplacer leur cible et non
    # le lien lui-meme. Le temporaire est sur le meme systeme de fichiers.
    target = os.path.realpath(path)
    # mkstemp cree en 0600 : reprendre le mode de la cible (0644 par defaut).
    try:
        mode = os.stat(target).st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(target) + '.',
                               suffix='.tmp', dir=os.path.dirname(target))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_history(path='history.json'):
    return validate_history(_read_json(path))


def save_history(history, path='history.json'):
    save_json(path, validate_history(history))


def load_player_names(path='players.json'):
    return normalize_player_names(_read_json(path))


def save_player_names(names, path='players.json'):
    save_json(path, normalize_player_names(names))


def known_players(history=None, player_names=None):
    """Union ordonnee de la liste des joueurs et des noms presents dans l'historique."""
    if history is None:
        history = load_history()
    if player_names is None:
        player_names = load_player_names()
    names = dict.fromkeys(normalize_player_names(player_names))
    for game in history:
        names.update(dict.fromkeys(game['scores']))
    return list(names)


def compute_scores(history=None, player_names=None):
    """Recalcule les totaux, y compris les joueurs inscrits avec zero partie."""
    if history is None:
        history = load_history()
    totals = dict.fromkeys(known_players(history, player_names), 0)
    for game in history:
        for name, score in game['scores'].items():
            totals[name] += score
    return totals


def check_legacy_scores(players, history):
    """Controle l'ancien format sans penaliser les inscrits a zero partie."""
    expected = compute_scores(history, player_names=list(players))
    if players.keys() != expected.keys() or any(
        isinstance(score, bool) or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not math.isclose(score, expected[name], rel_tol=0, abs_tol=1e-8)
        for name, score in players.items()
    ):
        raise ValueError(
            'Incoherence : players.json ne correspond pas a la somme des '
            'scores de history.json. Aucune conversion effectuee.'
        )


def migrate_state():
    """Initialise les fichiers ou migre la liste des joueurs, apres validation et copie."""
    history_exists = os.path.isfile('history.json')
    history = load_history() if history_exists else []
    players_exists = os.path.isfile('players.json')
    raw = _read_json('players.json') if players_exists else []
    player_names = known_players(history, normalize_player_names(raw))
    legacy = isinstance(raw, dict)
    if legacy:
        check_legacy_scores(raw, history)
        # Garder l'ancien etat localement avant de supprimer les totaux.
        parent = os.path.dirname(os.path.realpath('players.json'))
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = os.path.join(parent, f'_pre_migration_{stamp}')
        os.makedirs(backup)
        for name in ('players.json', 'history.json', 'players_backup.json'):
            if os.path.isfile(name):
                shutil.copy2(name, os.path.join(backup, name))
        print(f'Migration players.json : sauvegarde dans {backup}')
    if not history_exists:
        save_history(history)
    if not players_exists or legacy or player_names != raw:
        save_player_names(player_names)
        print(f'players.json : liste de {len(player_names)} joueurs, points depuis history.json.')
