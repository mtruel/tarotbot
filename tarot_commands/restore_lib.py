"""Logique de restauration des donnees, partagee par la commande Discord
(t/restore) et le script run_restore.sh.

Module stdlib uniquement : il ne doit surtout pas importer discord, pour rester
executable sur l'hote (hors conteneur) dans run_restore.sh.

Deux sources possibles :
- une archive zip (t/export, t/export backup, anciennes archives Drive) ;
- un snapshot restic (commande t/export backup / backup.sh), lu via backup_lib.

Principes :
- on ne restaure que les trois fichiers d'etat a la RACINE de l'archive ;
- les dossiers de saisons et les fichiers imbriques (dont un eventuel
  config.json avec le token) sont ignores ;
- aucune ecriture tant que la validation n'a pas reussi ;
- avant de basculer, un snapshot horodate des donnees actuelles est conserve ;
- players_backup.json est toujours recalcule (jamais repris de la source), pour
  qu'un undo ne remette pas les scores d'une saison disparue.
"""

import json
import os
import shutil
import zipfile
from datetime import datetime

from tarot_commands.backup_lib import (
    IGNORED_FILES,
    STATE_FILES,
    BackupError,
    dump as _restic_dump,
    resolve_snapshot,
)

# Nombre de dossiers _pre_restore_* conserves (les plus recents).
MAX_PRE_RESTORE = 10

# Refs restic designant « le dernier snapshot ».
RESTIC_SOURCES = {'backup', 'restic', 'latest'}


class RestoreError(Exception):
    """Archive invalide : rien n'a ete ecrit."""


def _check_consistency(players, history):
    """Verifie que players.json est bien la somme des scores de history.json."""
    total = {}
    for game in history:
        for name, score in game.get('scores', {}).items():
            total[name] = total.get(name, 0) + score
    if players != total:
        raise RestoreError(
            'Incoherence : players.json ne correspond pas a la somme des '
            'scores de history.json. Rien n\'a ete restaure.'
        )


def _root_prefix(names):
    """Determine le prefixe des fichiers d'etat dans l'archive.

    Accepte les zips plats (t/export : `players.json`) et ceux qui ont un
    unique dossier racine (backup/backup.sh : `2026-10-05_110326/players.json`).
    Ne descend jamais plus loin, donc les players.json des saisons archivees
    (prefixe + `Saison1_.../players.json`) restent ignores.
    """
    if any(name in STATE_FILES for name in names):
        return ''
    tops = {name.split('/', 1)[0] for name in names if '/' in name}
    if len(tops) == 1:
        top = tops.pop()
        if any(name == f'{top}/{state}' for name in names for state in STATE_FILES):
            return f'{top}/'
    return ''


def read_archive(path):
    """Lit et valide une archive, sans rien ecrire.

    Retourne un dict {nom: contenu} pour les fichiers d'etat presents a la
    racine de l'archive. Leve RestoreError si l'archive est inutilisable.
    """
    if not os.path.isfile(path):
        raise RestoreError(f'Archive introuvable : {path}')

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise RestoreError('Le fichier n\'est pas une archive zip valide.')

    with zf:
        names = [n for n in zf.namelist() if not n.endswith('/')]
        prefix = _root_prefix(names)
        root_files = {}
        for name in names:
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix):]
            # Seuls les fichiers directement sous le prefixe nous interessent :
            # un eventuel sous-dossier (saison) est ignore.
            if '/' in relative:
                continue
            if os.path.basename(relative) in IGNORED_FILES:
                continue
            if relative in STATE_FILES:
                root_files[relative] = zf.read(name)

    # Les verifications (fichiers presents, JSON, coherence) vivent dans _validate.
    return _validate(root_files)


def _validate(root_files):
    """Valide les fichiers d'etat (JSON + coherence) et retourne {nom: objet}.

    Leve RestoreError si l'archive est inutilisable. Aucune ecriture. Le
    players_backup.json de la source est ignore : il est toujours recalcule.
    """
    if 'players.json' not in root_files:
        raise RestoreError(
            'Archive invalide : players.json est absent de la racine.'
        )
    if 'history.json' not in root_files:
        raise RestoreError(
            'Archive invalide : history.json est absent de la racine.'
        )

    data = {}
    for name, raw in root_files.items():
        if name == 'players_backup.json':
            continue
        try:
            data[name] = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise RestoreError(
                f'Archive invalide : {name} n\'est pas du JSON valide.'
            )

    _check_consistency(data['players.json'], data['history.json'])
    data['players_backup.json'] = _expected_backup(
        data['players.json'], data['history.json']
    )
    return data


def _expected_backup(players, history):
    """Etat attendu de players_backup.json : players moins la derniere partie.

    Meme logique que ``t/undo`` : le backup doit decrire l'etat d'avant la
    donnee desormais derniere, pour qu'un undo coherent soit possible.
    """
    backup = dict(players)
    if history:
        for name, score in history[-1].get('scores', {}).items():
            backup[name] = backup.get(name, 0) - score
    return backup


def _normalize_ref(ref):
    """Traduit ``backup`` / ``restic`` / ``latest`` en « dernier snapshot »."""
    if ref is None or ref.strip().lower() in RESTIC_SOURCES:
        return 'latest'
    return ref


def read_snapshot(ref='latest'):
    """Lit et valide un snapshot restic, sans rien ecrire.

    ``ref`` peut etre ``latest``, ``backup``, un id court ou complet. Leve
    RestoreError si le depot ou le snapshot est introuvable, ou si les donnees
    sont invalides.
    """
    ref = _normalize_ref(ref)
    try:
        snap = resolve_snapshot(ref)
    except BackupError as exc:
        raise RestoreError(str(exc))

    if snap is None:
        raise RestoreError(f'Snapshot restic introuvable : {ref}')

    label = snap.get('short_id') or snap.get('id') or ref
    root_files = {}
    for name in STATE_FILES:
        try:
            raw = _restic_dump(snap['id'], name)
        except BackupError as exc:
            raise RestoreError(str(exc))
        if raw is None:
            continue
        root_files[name] = raw

    if not root_files:
        raise RestoreError(
            f'Snapshot {label} invalide : aucun fichier d\'etat a la racine.'
        )
    return _validate(root_files)


def _cleanup_pre_restore(dest_dir):
    """Ne conserve que les ``MAX_PRE_RESTORE`` dossiers _pre_restore_* recents."""
    try:
        entries = [
            name for name in os.listdir(dest_dir)
            if name.startswith('_pre_restore_')
            and os.path.isdir(os.path.join(dest_dir, name))
        ]
    except FileNotFoundError:
        return
    for name in sorted(entries, reverse=True)[MAX_PRE_RESTORE:]:
        shutil.rmtree(os.path.join(dest_dir, name), ignore_errors=True)


def apply_restore(data, dest_dir):
    """Sauvegarde l'etat courant puis ecrit les fichiers restaures.

    Retourne le chemin du dossier de snapshot cree.
    """
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    snapshot = os.path.join(dest_dir, f'_pre_restore_{stamp}')
    os.makedirs(snapshot, exist_ok=True)
    for name in STATE_FILES:
        current = os.path.join(dest_dir, name)
        if os.path.isfile(current):
            shutil.copy2(current, os.path.join(snapshot, name))

    for name, content in data.items():
        target = os.path.join(dest_dir, name)
        # Ecriture atomique : fichier temporaire puis remplacement.
        tmp = target + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=4)
        os.replace(tmp, target)

    _cleanup_pre_restore(dest_dir)
    return snapshot


def restore_archive(path, dest_dir):
    """Valide puis restaure une archive zip. Retourne le dossier de snapshot.

    Leve RestoreError (sans ecriture) si l'archive est invalide.
    """
    data = read_archive(path)
    return apply_restore(data, dest_dir)


def restore_snapshot(ref, dest_dir):
    """Valide puis restaure un snapshot restic. Retourne le dossier de snapshot.

    Leve RestoreError (sans ecriture) si le snapshot est invalide/absent.
    """
    data = read_snapshot(ref)
    return apply_restore(data, dest_dir)
