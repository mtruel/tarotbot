#!/bin/sh
set -eu

# supercronic (cron non-root, pensé pour les conteneurs) tourne en tâche de
# fond, le bot Discord reste au premier plan pour recevoir les signaux Docker
# (SIGTERM à l'arrêt du conteneur).
/usr/local/bin/supercronic /etc/tarotbot/crontab &
exec python /app/bot.py
