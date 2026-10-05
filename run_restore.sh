#!/bin/sh
# Restaure les donnees du bot depuis une archive zip OU un snapshot restic,
# hors Discord.
#
# A utiliser quand le bot ne demarre plus ou n'a pas acces a Discord. La
# validation est partagee avec la commande t/restore (tarot_commands/restore_lib).
#
# Usage :
#   ./run_restore.sh ecraser_saison_en_cours /chemin/vers/backup.zip
#   ./run_restore.sh ecraser_saison_en_cours backup          # dernier snapshot restic
#   ./run_restore.sh ecraser_saison_en_cours latest          # idem
#   ./run_restore.sh ecraser_saison_en_cours <id-snapshot>   # snapshot restic precis
#
# Le mot de confirmation doit etre EXACT (comme dans Discord). Le bot est
# arrete pendant l'operation puis redemarre, meme en cas d'echec.
set -eu
cd "$(dirname "$0")"

CONFIRM_TOKEN='ecraser_saison_en_cours'
SOURCE="${2:-}"

if [ "${1:-}" != "$CONFIRM_TOKEN" ]; then
    echo "Restauration annulee : mot de confirmation incorrect." >&2
    echo "Usage : ./run_restore.sh $CONFIRM_TOKEN /chemin/vers/backup.zip | backup | <id-snapshot>" >&2
    exit 1
fi
if [ -z "$SOURCE" ]; then
    echo "Source manquante (archive zip ou snapshot restic)." >&2
    exit 1
fi

# Une source ressemblant a un chemin de fichier doit exister : sinon on le
# traiterait a tort comme un identifiant de snapshot restic.
case "$SOURCE" in
    *.zip|*/*)
        if [ ! -f "$SOURCE" ]; then
            echo "Archive introuvable : $SOURCE" >&2
            exit 1
        fi
        ;;
esac

echo "Arret du bot..."
docker compose stop tarotbot

# Redemarre le bot quoi qu'il arrive (succes, echec de restauration, signal).
trap 'echo "Redemarrage du bot..."; docker compose up -d' EXIT

if [ -f "$SOURCE" ]; then
    echo "Validation et restauration depuis l'archive zip..."
    docker compose run --rm \
        -v "$(cd "$(dirname "$SOURCE")" && pwd)/$(basename "$SOURCE"):/restore/archive.zip:ro" \
        --entrypoint python tarotbot -c "
import sys
sys.path.insert(0, '/app')
from tarot_commands.restore_lib import restore_archive, RestoreError
try:
    snapshot = restore_archive('/restore/archive.zip', '/data')
except RestoreError as exc:
    print('Echec :', exc, file=sys.stderr)
    sys.exit(1)
print('Restauration effectuee. Snapshot :', snapshot)
"
else
    echo "Validation et restauration depuis le snapshot restic '$SOURCE'..."
    docker compose run --rm -e "RESTIC_REF=$SOURCE" --entrypoint python tarotbot -c "
import os, sys
sys.path.insert(0, '/app')
from tarot_commands.restore_lib import restore_snapshot, RestoreError
try:
    snapshot = restore_snapshot(os.environ.get('RESTIC_REF') or None, '/data')
except RestoreError as exc:
    print('Echec :', exc, file=sys.stderr)
    sys.exit(1)
print('Restauration effectuee. Snapshot :', snapshot)
"
fi
