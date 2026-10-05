#!/bin/sh
# Déclenche une sauvegarde immédiate (snapshot restic -> Google Drive) sans
# attendre la planification Supercronic. Lance un conteneur jetable basé sur
# l'image tarotbot, en réutilisant .env et le montage ./data:/data.
#
# Usage : ./run_backup.sh
set -eu
cd "$(dirname "$0")"
exec docker compose run --rm --entrypoint /usr/local/bin/backup.sh tarotbot
