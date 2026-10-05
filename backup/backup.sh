#!/bin/sh
# Sauvegarde automatique (planifiee par supercronic) : snapshot restic de /data
# dans un depot LOCAL, puis copie des snapshots vers le depot Drive (ajout seul).
#
# La logique (et la politique de retention) vit dans tarot_commands/backup_lib.py
# pour rester testable et partagee avec la commande Discord t/export backup.
# Ce script n'est qu'un point d'entree mince, sans set -e : on veut propager
# l'exit code de la bibliotheque et laisser restic liberer le verrou du depot.
exec python -m tarot_commands.backup_lib
