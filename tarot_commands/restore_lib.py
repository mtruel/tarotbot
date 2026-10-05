"""Logique de restauration des donnees, partagee par la commande Discord
(t/restore) et le script run_restore.sh.

Module stdlib uniquement : il ne doit surtout pas importer discord, pour rester
executable sur l'hote (hors conteneur) dans run_restore.sh.

Deux sources possibles :
- une archive zip (t/export, t/export backup, anciennes archives Drive) ;
- un snapshot restic (commande t/export backup / backup.sh), lu via backup_lib.

Principes :
- on restaure history.json et la liste des joueurs players.json a la RACINE de l'archive ;
- les dossiers de saisons et les fichiers imbriques (dont un eventuel
  config.json avec le token) sont ignores ;
- aucune ecriture tant que la validation n'a pas reussi ;
- avant de basculer, un snapshot horodate des donnees actuelles est conserve ;
- les anciennes listes avec scores sont converties ; players_backup.json est ignore.
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

from tarot_commands.state import (
    check_legacy_scores, known_players, normalize_player_names, save_json, validate_history,
)

# Nombre de dossiers _pre_restore_* conserves (les plus recents).
MAX_PRE_RESTORE = 10

# Refs restic designant « le dernier snapshot ».
RESTIC_SOURCES = {'backup', 'restic', 'latest'}


class RestoreError(Exception):
    """Archive invalide : rien n'a ete ecrit."""


def _check_consistency(players, history):
    """Valide les totaux d'une ancienne archive, inscrits a zero inclus."""
    try:
        check_legacy_scores(players, history)
    except ValueError as exc:
        raise RestoreError(str(exc)) from exc


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
    """Valide history et la liste des joueurs facultative avant toute ecriture."""
    if 'history.json' not in root_files:
        raise RestoreError(
            'Archive invalide : history.json est absent de la racine.'
        )

    data = {}
    for name in STATE_FILES:
        if name not in root_files:
            continue
        try:
            data[name] = json.loads(root_files[name].decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RestoreError(
                f'Archive invalide : {name} n\'est pas du JSON valide.'
            ) from exc

    try:
        history = validate_history(data['history.json'])
        raw_players = data.get('players.json', [])
        player_names = normalize_player_names(raw_players)
        if isinstance(raw_players, dict):
            _check_consistency(raw_players, history)
        data['players.json'] = known_players(history, player_names)
    except ValueError as exc:
        raise RestoreError(f'Archive invalide : {exc}') from exc
    return data


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
        # Ecriture atomique partagee avec le bot (fsync, mode conserve).
        save_json(os.path.join(dest_dir, name), content)

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
