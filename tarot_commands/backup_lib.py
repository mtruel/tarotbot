"""Logique restic partagee : sauvegarde de ``data/`` et lecture des snapshots.

Module stdlib uniquement (``subprocess``, ``os``, ``json``, ``datetime``) : il
n'importe pas discord, afin de rester executable hors conteneur (``run_backup.sh``,
``run_restore.sh``, tests) et d'etre reutilise par ``restore_lib``.

Architecture :
- le depot restic vit en local (defaut ``/data/restic``) : snapshots et rotation
  sont rapides, sans passer par l'API Google Drive ;
- Google Drive heberge un SECOND depot restic, alimente uniquement par
  ``restic copy`` (ajout seul : il ne supprime ni ne reecrit rien). Un depot
  local vide ou recree ne peut donc pas ecraser l'historique Drive ;
- ``t/export backup`` zippe le depot local (pas de re-telechargement Drive).

Politique de retention (surchargeable par variables d'environnement) :
- ``BACKUP_KEEP_RECENT_DAYS`` (defaut 30) : on garde tous les snapshots du jour,
- puis 1 snapshot par semaine (le plus recent de chaque semaine ISO) pendant
  ``BACKUP_KEEP_WEEKLY_DAYS`` (defaut 183, soit ~6 mois),
- puis 1 snapshot par mois civil, sans limite au-dela.
Le seuil de bascule vers le mensuel est donc ``RECENT_DAYS + WEEKLY_DAYS``.
"""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
import zipfile

STATE_FILES = ('players.json', 'history.json', 'players_backup.json')

# Jamais sauvegardes ni restaures : secrets, meme presents dans data/ (repli
# config.json avec le token, .env, etc.). ``curves.png`` est un artefact
# regenere par ``t/curves`` : inutile de le versionner dans les snapshots.
EXCLUDED_FILES = ('config.json', '.env', 'token.json', 'curves.png')

# Dossiers exclus du snapshot restic et des zips de donnees (le depot lui-meme,
# les cibles de restauration manuelle, etc.).
EXCLUDED_DIRS = ('restic', 'restore')

# Alias historique : les restaurations raisonnent en « fichiers ignores ».
IGNORED_FILES = EXCLUDED_FILES

# Depot restic local (dans le volume data/, hors Git).
DEFAULT_REPOSITORY = '/data/restic'

# Mot de passe par defaut du depot restic (surchargeable par RESTIC_PASSWORD /
# RESTIC_PASSWORD_FILE / RESTIC_PASSWORD_COMMAND dans .env).
DEFAULT_PASSWORD = 'TAROTBOT_PASSWORD'


class BackupError(Exception):
    """Echec d'une operation restic (message pret a afficher)."""


def src_dir():
    """Dossier des donnees sauvegardees (defaut ``/data``, volume du conteneur)."""
    return os.environ.get('BACKUP_SRC_DIR', '/data')


def repository():
    """Chemin du depot restic local.

    Priorite a ``RESTIC_REPOSITORY`` ; sinon ``<BACKUP_SRC_DIR>/restic``
    (defaut ``/data/restic``).
    """
    explicit = os.environ.get('RESTIC_REPOSITORY')
    if explicit:
        return explicit
    return os.path.join(src_dir(), 'restic')


def remote_repo():
    """Chemin restic du depot miroir sur Google Drive.

    C'est un depot restic a part entiere (``rclone:<remote>``), pas un simple
    dossier rclone : il se lit/ecrit avec ``restic``.
    """
    dest = os.environ.get('BACKUP_DEST_PATH', 'TarotBot')
    return f'rclone:gdrive:{dest}/restic'


def _keep_recent_days():
    return int(os.environ.get('BACKUP_KEEP_RECENT_DAYS', '30'))


def _keep_weekly_days():
    return int(os.environ.get('BACKUP_KEEP_WEEKLY_DAYS', '183'))


def _remote_prune_weekday():
    """Jour (0 = lundi … 6 = dimanche) du ``prune`` lourd sur Drive."""
    return int(os.environ.get('BACKUP_REMOTE_PRUNE_WEEKDAY', '6'))


def _env(repo=None, source_repo=None):
    """Environnement pour restic : depot + mot de passe garantis.

    ``repo`` : depot cible (defaut : local). ``source_repo`` : depot source
    pour ``restic copy`` (alimente ``RESTIC_FROM_*``). Quand ``repo`` est le
    depot distant et qu'aucune source n'est precisee, la source est le depot
    local.
    """
    env = dict(os.environ)
    env['RESTIC_REPOSITORY'] = repo or repository()

    password = env.get('RESTIC_PASSWORD')
    if not password and not env.get('RESTIC_PASSWORD_FILE') \
            and not env.get('RESTIC_PASSWORD_COMMAND'):
        password = DEFAULT_PASSWORD
        env['RESTIC_PASSWORD'] = password

    source = source_repo
    if source is None and repo and repo != repository():
        source = repository()
    if source:
        env['RESTIC_FROM_REPOSITORY'] = source
        if not env.get('RESTIC_FROM_PASSWORD_FILE') \
                and not env.get('RESTIC_FROM_PASSWORD_COMMAND'):
            env['RESTIC_FROM_PASSWORD'] = password
    return env


def _run(args, repo=None, source_repo=None, input_bytes=None, cwd=None):
    """Lance ``restic`` et retourne stdout (bytes). Leve BackupError en cas d'echec."""
    try:
        result = subprocess.run(
            ('restic',) + tuple(args),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_env(repo, source_repo),
            cwd=cwd,
        )
    except FileNotFoundError:
        raise BackupError('restic introuvable (il doit etre installe dans l\'image).')
    if result.returncode != 0:
        message = (result.stderr or result.stdout or b'').decode('utf-8', 'replace').strip()
        raise BackupError(f'restic {" ".join(args)} a echoue : {message}')
    return result.stdout


def _config_present(repo):
    """True si ``repo`` est un depot restic (fichier ``config`` lisible).

    Une absence de depot (local ou distant) retourne False ; toute autre erreur
    (mot de passe, reseau, quota) est propagee et ne declenche jamais d'``init``.
    """
    try:
        _run(['cat', 'config'], repo=repo)
        return True
    except BackupError as exc:
        message = str(exc).lower()
        if 'does not exist' in message or 'no such file' in message:
            return False
        raise


def ensure_repo():
    """Initialise le depot restic LOCAL s'il n'existe pas encore.

    Retourne True s'il vient d'etre cree. Un nouveau depot local reprend les
    parametres de decoupage du depot Drive (``--copy-chunker-params``) pour ne
    pas dupliquer sur Drive les morceaux deja presents.
    """
    repo = repository()
    if repo.startswith('rclone:'):
        if _config_present(repo):
            return False
        _run(['init'], repo=repo)
        return True

    if os.path.isdir(repo) and os.listdir(repo):
        if _config_present(repo):
            return False
        raise BackupError(
            f'Depot restic local non initialise : {repo} contient deja des '
            'fichiers. Deplace-les avant de relancer.'
        )

    os.makedirs(repo, exist_ok=True)
    remote = remote_repo()
    args = ['init']
    source = None
    if remote != repo and _config_present(remote):
        source = remote
        args += ['--copy-chunker-params', '--from-repo', remote]
    _run(args, repo=repo, source_repo=source)
    return True


def ensure_remote_repo():
    """Initialise le depot restic Drive s'il n'existe pas encore.

    Retourne True s'il vient d'etre cree. Une erreur reseau / quota ne cree
    jamais de depot : elle est propagee.
    """
    remote = remote_repo()
    local = repository()
    if remote == local:
        return False
    if _config_present(remote):
        return False

    args = ['init']
    source = None
    if not local.startswith('rclone:') and _config_present(local):
        source = local
        args += ['--copy-chunker-params', '--from-repo', local]
    _run(args, repo=remote, source_repo=source)
    return True


def snapshots(repo=None):
    """Liste des snapshots (triee du plus ancien au plus recent)."""
    raw = _run(['snapshots', '--json'], repo=repo)
    data = json.loads(raw.decode('utf-8'))
    if isinstance(data, dict):
        data = data.get('snapshots', [])
    return sorted(data, key=lambda snap: snap.get('time', ''))


def resolve_snapshot(ref, repo=None):
    """Resout une reference de snapshot (``latest``, id court ou complet).

    Retourne le dict du snapshot, ou None si introuvable.
    """
    snaps = snapshots(repo)
    if not snaps:
        return None
    if ref in (None, '', 'latest'):
        return snaps[-1]
    for snap in snaps:
        if ref in (snap.get('id'), snap.get('short_id')):
            return snap
    return None


def dump(snapshot_id, path, repo=None):
    """Contenu d'un fichier dans un snapshot (bytes), ou None s'il est absent."""
    try:
        return _run(['dump', snapshot_id, path], repo=repo)
    except BackupError:
        return None


def _parse_backup_json(output):
    """Extrait l'id du snapshot depuis la sortie ``backup --json`` de restic."""
    snapshot_id = None
    for line in output.decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get('message_type') == 'summary' and obj.get('snapshot_id'):
            snapshot_id = obj['snapshot_id']
        elif obj.get('snapshot_id'):
            snapshot_id = obj['snapshot_id']
    return snapshot_id


def backup_dir(dir_path):
    """Sauvegarde ``dir_path`` (data/) hors secrets et hors depot restic.

    Lance restic depuis ``dir_path`` sur ``.`` pour que les chemins dans le
    snapshot soient relatifs (``players.json``, …) et lisibles par restore.
    """
    args = ['backup', '--json', '--host', 'tarotbot']
    for name in EXCLUDED_FILES:
        args += ['--exclude', name]
    for name in EXCLUDED_DIRS:
        args += ['--exclude', name]
    args += ['--exclude', '*.tmp']
    args.append('.')
    snapshot_id = _parse_backup_json(_run(args, cwd=dir_path))
    if not snapshot_id:
        snaps = snapshots()
        snapshot_id = snaps[-1]['id'] if snaps else None
    if not snapshot_id:
        raise BackupError('restic n\'a retourne aucun identifiant de snapshot.')
    return snapshot_id


def _parse_time(value):
    """Parse un horodatage ISO restic (fractions jusqu'a 9 chiffres)."""
    value = value.strip().replace('Z', '+00:00')
    if '.' in value:
        head, rest = value.split('.', 1)
        index = 0
        while index < len(rest) and rest[index].isdigit():
            index += 1
        fraction = rest[:index][:6]
        offset = rest[index:]
        value = f'{head}.{fraction}{offset}' if fraction else head + offset
    return datetime.datetime.fromisoformat(value)


def _latest_by_day(snaps):
    """Un seul snapshot par jour : le plus recent de la journee."""
    days = {}
    for snap in snaps:
        day = _parse_time(snap['time']).date()
        current = days.get(day)
        if current is None or snap['time'] > current['time']:
            days[day] = snap
    return [days[day] for day in sorted(days)]


def _period_key(day, unit):
    if unit == 'week':
        iso = day.isocalendar()
        return (iso[0], iso[1])
    return (day.year, day.month)


def snapshots_to_keep(snaps, now=None):
    """Snapshots a conserver selon la politique de retention.

    ``snaps`` : liste de snapshots restic. ``now`` : datetime aware (test).
    Sur le palier recent : TOUS les snapshots sont gardes. Au-dela : un seul
    par jour, puis le plus recent de chaque semaine / mois.
    """
    if now is None:
        now = datetime.datetime.now().astimezone()
    recent_days = _keep_recent_days()
    weekly_days = recent_days + _keep_weekly_days()

    keep = []
    older = []
    for snap in snaps:
        day = _parse_time(snap['time']).date()
        age = (now.date() - day).days
        if age < 0:
            age = 0
        if age < recent_days:
            keep.append(snap)                       # palier quotidien : tout garder
        else:
            older.append(snap)

    weekly_done = set()
    monthly_done = set()
    # Du plus recent au plus ancien : le premier snapshot vu dans une periode
    # donnee est donc bien le plus recent de cette periode.
    for snap in reversed(_latest_by_day(older)):
        day = _parse_time(snap['time']).date()
        age = (now.date() - day).days
        if age < weekly_days:
            key = _period_key(day, 'week')          # 1 plus recent par semaine
            if key not in weekly_done:
                weekly_done.add(key)
                keep.append(snap)
        else:
            key = _period_key(day, 'month')         # 1 plus recent par mois
            if key not in monthly_done:
                monthly_done.add(key)
                keep.append(snap)

    # Garde-fou : ne jamais tout supprimer.
    if snaps and not keep:
        keep.append(sorted(snaps, key=lambda s: s.get('time', ''))[-1])
    return keep


def _forget_ids(repo, snaps, removed, prune):
    """Retire ``removed`` du depot ``repo`` (``--prune`` optionnel)."""
    if not removed:
        return
    args = ['forget'] + [snap['id'] for snap in removed]
    if prune:
        args.append('--prune')
    _run(args, repo=repo)


def prune(repo=None):
    """Elague le depot LOCAL selon la politique. Retourne (gardes, supprimes)."""
    snaps = snapshots(repo)
    if not snaps:
        return [], []
    keep = snapshots_to_keep(snaps)
    keep_ids = {snap['id'] for snap in keep}
    removed = [snap for snap in snaps if snap['id'] not in keep_ids]
    _forget_ids(repo, snaps, removed, prune=True)
    return keep, removed


def _should_prune_remote(now=None):
    """Le ``prune`` lourd sur Drive n'a lieu qu'un jour par semaine."""
    if now is None:
        now = datetime.datetime.now().astimezone()
    return now.weekday() == _remote_prune_weekday()


def prune_remote(now=None):
    """Retention sur le depot DRIVE (dates des snapshots). (gardes, supprimes).

    Le tri des snapshots a supprimer (``forget``) est fait a chaque sauvegarde ;
    le nettoyage lourd (``--prune``) seulement le jour choisi, pour limiter les
    appels a l'API Google Drive. L'etat du depot local n'entre pas en compte.
    """
    repo = remote_repo()
    if repo == repository() or not _config_present(repo):
        return [], []
    snaps = snapshots(repo)
    if not snaps:
        return [], []
    keep = snapshots_to_keep(snaps, now=now)
    keep_ids = {snap['id'] for snap in keep}
    removed = [snap for snap in snaps if snap['id'] not in keep_ids]
    _forget_ids(repo, snaps, removed, prune=_should_prune_remote(now))
    return keep, removed


def _rclone(args):
    """Lance ``rclone`` et leve BackupError en cas d'echec."""
    try:
        result = subprocess.run(
            ('rclone',) + tuple(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise BackupError('rclone introuvable (il doit etre installe dans l\'image).')
    if result.returncode != 0:
        message = (result.stderr or result.stdout or b'').decode('utf-8', 'replace').strip()
        raise BackupError(f'rclone {" ".join(args)} a echoue : {message}')
    return result.stdout


def copy_to_drive():
    """Copie les snapshots du depot local vers le depot Drive (ajout seul).

    ``restic copy`` n'ajoute que les snapshots absents du depot Drive et ne
    supprime jamais rien : l'historique Drive survit a un depot local perdu.
    Retourne ``(chemin_drive, nombre_de_snapshots_copies)``.
    """
    local = repository()
    if local.startswith('rclone:'):
        raise BackupError(
            'Le depot local est deja distant (rclone:) : copie vers Drive inutile.'
        )
    if not _config_present(local):
        raise BackupError(f'Depot restic local introuvable : {local}')

    remote = remote_repo()
    if remote == local:
        raise BackupError('Le depot Drive est identique au depot local.')
    output = _run(['copy', '--from-repo', local], repo=remote, source_repo=local)
    return remote, _count_copied(output)


def _count_copied(output):
    """Compte les lignes « snapshot … copied to … » de la sortie de restic copy."""
    count = 0
    for line in output.decode('utf-8', 'replace').splitlines():
        if 'snapshot ' in line and ' copied to ' in line:
            count += 1
    return count


def upload_latest_zip():
    """Depose un zip des donnees courantes sur le Drive (derniere version).

    Fichier a nom stable (``tarotbot-latest.zip``) ecrase a chaque sauvegarde :
    il represente toujours l'etat le plus recent de ``data/``, lisible sans
    restic. Retourne le chemin distant.
    """
    # Import differe : export_lib importe EXCLUDED_FILES d'ici (evite un cycle).
    from tarot_commands.export_lib import build_export

    dest = os.environ.get('BACKUP_DEST_PATH', 'TarotBot')
    archive = build_export(src=src_dir())
    try:
        remote_path = f'gdrive:{dest}/tarotbot-latest.zip'
        _rclone(['copyto', archive, remote_path])
    finally:
        shutil.rmtree(os.path.dirname(archive), ignore_errors=True)
    return remote_path


def build_repo_archive(dest_dir=None):
    """Zippe le depot restic local (historique complet des sauvegardes).

    Retourne le chemin du zip. Pour relire ces donnees : RESTIC_PASSWORD +
    ``restic -r <depot_extrait> restore …``.
    """
    repo = repository()
    if repo.startswith('rclone:'):
        raise BackupError(
            'Le depot restic est distant : impossible de zipper sans le '
            'telecharger. Configure RESTIC_REPOSITORY sur un chemin local.'
        )
    if not os.path.isdir(repo):
        raise BackupError(f'Depot restic local introuvable : {repo}')

    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix='tarotbot-repo-')
    else:
        os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    path_zip = os.path.join(dest_dir, f'tarotbot-restic-repo-{stamp}.zip')

    with zipfile.ZipFile(path_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(repo):
            for filename in files:
                full = os.path.join(root, filename)
                zf.write(full, os.path.relpath(full, repo))
    return path_zip


def main_backup():
    """Entree de ``backup.sh`` : snapshot local, prune local, copie Drive, zip."""
    print(f'Depot restic local : {repository()}')
    print(f'Depot Drive        : {remote_repo()}')
    if ensure_repo():
        print('Depot restic local initialise.')
    snapshot_id = backup_dir(src_dir())
    print(f'Snapshot restic cree : {snapshot_id}')
    keep, removed = prune()
    print(f'Retention locale : {len(keep)} conserve(s), {len(removed)} supprime(s).')
    for snap in removed:
        print(f'  supprime {snap.get("short_id")} ({snap.get("time")})')
    try:
        if ensure_remote_repo():
            print('Depot Drive initialise.')
        remote, copied = copy_to_drive()
        print(f'{copied} snapshot(s) copie(s) vers {remote}.')
        keep_r, removed_r = prune_remote()
        print(f'Retention Drive : {len(keep_r)} conserve(s), {len(removed_r)} supprime(s).')
    except BackupError as exc:
        print(f'Avertissement : copie Drive echouee ({exc}).')
    try:
        remote_zip = upload_latest_zip()
        print(f'Zip de la derniere version depose : {remote_zip}')
    except BackupError as exc:
        print(f'Avertissement : zip de la derniere version non depose ({exc}).')
    return snapshot_id


if __name__ == '__main__':
    try:
        main_backup()
    except BackupError as exc:
        raise SystemExit(str(exc))
