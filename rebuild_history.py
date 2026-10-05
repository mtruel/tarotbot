#!/usr/bin/env python3
"""Reconstruit history.json a partir des messages du salon Discord #tarot.

Les horodatages de l'historique sont l'heure de Paris au moment ou le bot a
enregistre la donne. Ils correspondent au message de tableau de scores qui
suit le clic sur Calcul. Le message de commande (t/auto, t/game,
t/descendante) donne l'id a conserver, et le message de confirmation du bot
donne le contrat, les primes et les miseres.

Les choix faits dans les menus de t/game sont des reponses ephemeres : Discord
ne les garde pas dans le salon. Pour ces donnes, seuls l'id du message et les
points d'attaque (l'argument de t/game) peuvent etre retrouves.

A lancer dans le conteneur, dont le repertoire de travail est /data :

    docker compose run --rm --no-deps \\
        -v ./rebuild_history.py:/tmp/rebuild_history.py:ro \\
        tarotbot python /tmp/rebuild_history.py --dry-run

    docker compose run --rm --no-deps \\
        -v ./rebuild_history.py:/tmp/rebuild_history.py:ro \\
        tarotbot python /tmp/rebuild_history.py
"""

import argparse
import ast
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv optionnel : on peut aussi passer DISCORD_TOKEN
    load_dotenv = None

PARIS = ZoneInfo('Europe/Paris')
HISTORY_TIME = '%d/%m/%Y, %H:%M:%S'
WINDOW_SECONDS = 30
API = 'https://discord.com/api/v10'
ENCHERE_NAMES = {1: 'Petite', 2: 'Garde', 4: 'GardeSans', 6: 'GardeContre'}

SCORE_ROW = re.compile(r'║\s*(.*?)\s*║\s*([+-]?\d+)\s*║')
LIST_FIELD = re.compile(r'{label}:\s*(\[[^\]]*\])')
ENCHERE_FIELD = re.compile(r'Enchère:\s*(.+?)\s*\((\d+)\)')
SCALAR_FIELD = re.compile(r'^{label}:\s*(-?\d+|None)\b', re.M)
DESC_LINE = re.compile(r'^(.+):\s*(\d+)\s*,?\s*$', re.M)
GAME_CMD = re.compile(r'^t/game\s+(-?\d+)\b')
DESC_CMD = re.compile(r'^t/(?:descendante|desc)\b', re.I)


def api_get(token, url):
    request = urllib.request.Request(url, headers={
        'Authorization': f'Bot {token}',
        'User-Agent': 'tarotbot (rebuild-history)',
    })
    for _ in range(8):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            body = error.read().decode()
            retry = 1.0
            try:
                retry = float(json.loads(body).get('retry_after', 1))
            except json.JSONDecodeError:
                pass
            time.sleep(retry + 0.2)
    raise RuntimeError(f'rate limit persistent sur {url}')


def find_tarot_channel(token):
    guilds = api_get(token, f'{API}/users/@me/guilds')
    found = []
    for guild in guilds:
        channels = api_get(token, f"{API}/guilds/{guild['id']}/channels")
        for channel in channels:
            if channel.get('type') == 0 and channel.get('name', '').lower() == 'tarot':
                found.append((guild['name'], channel['id'], channel['name']))
    if len(found) != 1:
        names = ', '.join(f'{guild}/{name} ({cid})' for guild, cid, name in found) or 'aucun'
        raise RuntimeError(f'salon #tarot introuvable ou ambigu : {names}')
    return found[0]


def fetch_messages(token, channel_id):
    messages = []
    before = None
    while True:
        url = f'{API}/channels/{channel_id}/messages?limit=100'
        if before:
            url += f'&before={before}'
        batch = api_get(token, url)
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]['id']
        print(f'  {len(messages)} messages...', file=sys.stderr)
        if len(batch) < 100:
            break
        time.sleep(0.35)
    messages.sort(key=lambda message: int(message['id']))
    return messages


def parse_list(content, label):
    match = re.search(LIST_FIELD.pattern.format(label=re.escape(label)), content)
    if not match:
        return None
    return ast.literal_eval(match.group(1))


def parse_scalar(content, label):
    match = re.search(SCALAR_FIELD.pattern.format(label=re.escape(label)), content, re.M)
    if not match or match.group(1) == 'None':
        return None
    return int(match.group(1))


def parse_descendante_body(content):
    body = content.split('Descendante:', 1)[1]
    joueurs = []
    points = []
    for match in DESC_LINE.finditer(body):
        joueurs.append(match.group(1).strip())
        points.append(int(match.group(2)))
    return joueurs, points


def details_from_confirm(content, message_id):
    if 'Descendante:' in content:
        joueurs, points = parse_descendante_body(content)
        return {
            'message_id': message_id,
            'type': 'descendante',
            'joueurs': joueurs,
            'points': points,
            'miseres': parse_list(content, 'Misères') or [],
        }

    enchere = ENCHERE_FIELD.search(content)
    multiplicateur = int(enchere.group(2)) if enchere else None
    partenaire = parse_list(content, 'Partenaire')
    preneur = parse_list(content, 'Preneur')
    return {
        'message_id': message_id,
        'type': 'partie',
        'enchere': ENCHERE_NAMES.get(multiplicateur, enchere.group(1).strip() if enchere else None),
        'multiplicateur': multiplicateur,
        'preneur': preneur[0] if preneur else None,
        'partenaire': partenaire[0] if partenaire else None,
        'defenseurs': parse_list(content, 'Défense'),
        'bouts': parse_scalar(content, 'Bouts'),
        'points_attaque': parse_scalar(content, 'Score'),
        'primes_attaque': parse_list(content, 'Primes Att') or [],
        'primes_defense': parse_list(content, 'Primes Déf') or [],
        'miseres': parse_list(content, 'Misères') or [],
    }


def details_from_command(content, message_id):
    game = GAME_CMD.match(content)
    if game:
        return {
            'message_id': message_id,
            'type': 'partie',
            'enchere': None,
            'multiplicateur': None,
            'preneur': None,
            'partenaire': None,
            'defenseurs': None,
            'bouts': None,
            'points_attaque': int(game.group(1)),
            'primes_attaque': None,
            'primes_defense': None,
            'miseres': None,
        }
    if DESC_CMD.match(content):
        points = [int(piece) for piece in content.split()[1:] if piece.isdigit()]
        return {
            'message_id': message_id,
            'type': 'descendante',
            'joueurs': None,
            'points': points,
            'miseres': [],
        }
    return None


def is_score_table(content):
    return '╔' in content and 'Score' in content and 'Nom' in content


def parse_score_table(content):
    scores = {}
    for name, value in SCORE_ROW.findall(content):
        name = name.strip()
        if name and name != 'Nom':
            scores[name] = int(value)
    return scores


def is_command(content):
    return content.startswith(('t/auto', 't/descendante')) or GAME_CMD.match(content) is not None


def is_confirm(content):
    return content.startswith('**Is this parse correct?') or 'Descendante:' in content


def collect_games(messages):
    """Associe chaque tableau de scores a la commande qui le precede."""
    games = []
    command = None
    confirm = None
    for message in messages:
        content = message.get('content') or ''
        if not message['author'].get('bot') and is_command(content):
            command = message
            confirm = None
            continue
        if message['author'].get('bot') and command is not None and is_confirm(content):
            confirm = message
            continue
        if message['author'].get('bot') and is_score_table(content):
            scores = parse_score_table(content)
            if scores:
                games.append({
                    'scores': scores,
                    'time': datetime.fromisoformat(message['timestamp']),
                    'command': command,
                    'confirm': confirm,
                })
            command = None
            confirm = None
    return games


def game_details(game):
    command = game['command']
    message_id = int(command['id']) if command else None
    confirm = game['confirm']
    if confirm and confirm.get('content'):
        details = details_from_confirm(confirm['content'], message_id)
        complete = bool(details.get('preneur') or details.get('joueurs'))
        return details, 'complet' if complete else 'partiel'
    if command:
        details = details_from_command(command.get('content') or '', message_id)
        if details:
            return details, 'partiel'
    return None, 'sans-commande'


def scores_equal(entry, game):
    history_scores = {name: int(value) for name, value in entry['scores'].items()}
    return history_scores == game['scores']


def entry_time(entry):
    return datetime.strptime(entry['time'], HISTORY_TIME).replace(tzinfo=PARIS)


def match_history(history, games):
    candidates = []
    for index, entry in enumerate(history):
        when = entry_time(entry)
        for game_index, game in enumerate(games):
            if not scores_equal(entry, game):
                continue
            delta = abs((when - game['time']).total_seconds())
            if delta <= WINDOW_SECONDS:
                candidates.append((delta, index, game_index))
    candidates.sort()
    used_entries = set()
    used_games = set()
    assigned = {}
    for delta, index, game_index in candidates:
        if index in used_entries or game_index in used_games:
            continue
        used_entries.add(index)
        used_games.add(game_index)
        assigned[index] = (games[game_index], delta)
    return assigned


def enrich(history, games):
    assigned = match_history(history, games)
    enriched = []
    report = {
        'complet': 0, 'partiel': 0, 'sans-commande': 0, 'non-apparie': 0,
        'deltas': [], 'partiels': [],
    }
    for index, entry in enumerate(history):
        if index not in assigned:
            enriched.append(entry)
            report['non-apparie'] += 1
            continue
        game, delta = assigned[index]
        details, kind = game_details(game)
        report['deltas'].append(delta)
        report[kind] += 1
        if kind != 'complet':
            command = game['command']
            report['partiels'].append({
                'time': entry['time'],
                'commande': (command or {}).get('content'),
                'confirmation': bool(game['confirm']),
                'details': details,
            })
        if not details:
            enriched.append(entry)
            continue
        rebuilt = {'time': entry['time']}
        rebuilt.update(details)
        rebuilt['scores'] = entry['scores']
        enriched.append(rebuilt)
    return enriched, report


def nearest_misses(history, games, limit=8):
    misses = []
    for entry in history:
        when = entry_time(entry)
        best = None
        for game in games:
            if not scores_equal(entry, game):
                continue
            delta = (when - game['time']).total_seconds()
            if best is None or abs(delta) < abs(best):
                best = delta
        if best is not None and abs(best) > WINDOW_SECONDS:
            misses.append((abs(best), best, entry['time']))
    misses.sort()
    return misses[:limit]


def self_check():
    sample = (
        "**Is this parse correct?:**\n"
        "Preneur:    ['Melvin'],\n"
        "Partenaire: ['Jonathan'],\n"
        "Score:      25,\n"
        "Bouts:      1,\n"
        "Enchère:    garde (2),\n"
        "Défense:    ['Driss', 'Mathias', 'Brieuc'],\n"
        "Primes Att: [],\n"
        "Primes Déf: ['Petit au bout'],\n"
        "Misères:    ['Brieuc']"
    )
    details = details_from_confirm(sample, 1555185485775773797)
    assert details['enchere'] == 'Garde', details
    assert details['multiplicateur'] == 2
    assert details['preneur'] == 'Melvin'
    assert details['partenaire'] == 'Jonathan'
    assert details['points_attaque'] == 25
    assert details['bouts'] == 1
    assert details['defenseurs'] == ['Driss', 'Mathias', 'Brieuc']
    assert details['primes_defense'] == ['Petit au bout']
    assert details['miseres'] == ['Brieuc']

    table = (
        "```\n"
        "╔══════════╦═══════╗\n"
        "║   Nom    ║ Score ║\n"
        "╟──────────╫───────╢\n"
        "║ Jonathan ║ -112  ║\n"
        "║  Melvin  ║ -214  ║\n"
        "║  Brieuc  ║ +142  ║\n"
        "╚══════════╩═══════╝\n"
        "```"
    )
    assert parse_score_table(table) == {'Jonathan': -112, 'Melvin': -214, 'Brieuc': 142}


def main():
    self_check()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='affiche le bilan sans ecrire')
    args = parser.parse_args()

    root = Path.cwd()
    history_path = root / 'history.json'
    config_path = root / 'config.json'
    if not history_path.is_file():
        raise SystemExit(f'{history_path} doit etre dans le repertoire courant ({root})')

    if load_dotenv is not None:
        load_dotenv(root / '.env')
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        if not config_path.is_file():
            raise SystemExit(
                'Aucun token Discord : definir DISCORD_TOKEN (fichier .env) '
                f'ou fournir {config_path}'
            )
        token = json.loads(config_path.read_text())['token']
    guild, channel_id, channel_name = find_tarot_channel(token)
    print(f'Salon #{channel_name} sur {guild} ({channel_id})')
    print('Lecture des messages...')
    messages = fetch_messages(token, channel_id)
    games = collect_games(messages)
    print(f'{len(messages)} messages, {len(games)} tableaux de scores')

    original = history_path.read_bytes()
    history = json.loads(original)
    enriched, report = enrich(history, games)
    latest = history_path.read_bytes()
    if latest != original:
        print('history.json a change pendant la lecture Discord, second passage.')
        original = latest
        history = json.loads(original)
        enriched, report = enrich(history, games)
        if history_path.read_bytes() != original:
            raise SystemExit('history.json change encore : rien ecrit, relancer le script.')

    deltas = report['deltas']
    print(
        f"parties dans l'historique : {len(history)}\n"
        f"  appariees, detail complet : {report['complet']}\n"
        f"  appariees, detail partiel (menus) : {report['partiel']}\n"
        f"  tableau trouve sans commande : {report['sans-commande']}\n"
        f"  non appariees : {report['non-apparie']}"
    )
    if deltas:
        print(f"  ecart horaire median : {sorted(deltas)[len(deltas) // 2]:.1f}s, max {max(deltas):.1f}s")
    for partial in report['partiels']:
        print(
            f"  partiel {partial['time']} confirmation={partial['confirmation']}\n"
            f"    commande: {partial['commande']}\n"
            f"    details: {partial['details']}"
        )
    misses = nearest_misses(history, games)
    if misses:
        print('Scores identiques hors fenetre (abs, signe, heure historique) :')
        for item in misses:
            print(f'  {item[0]:.0f}s  {item[1]:+.0f}s  {item[2]}')

    if args.dry_run:
        print('Dry-run : history.json inchange.')
        return

    stamp = datetime.now(PARIS).strftime('%Y%m%d-%H%M%S')
    backup = history_path.with_name(f'history.backup-{stamp}.json')
    shutil.copy2(history_path, backup)
    history_path.write_text(json.dumps(enriched, indent=4, ensure_ascii=True) + '\n')
    print(f'Sauvegarde : {backup.name}')
    print(f'Ecrit : {history_path.name} ({len(enriched)} parties)')


if __name__ == '__main__':
    main()
