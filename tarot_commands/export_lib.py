"""Construction d'archives zip des donnees du bot.

Module stdlib uniquement : partage par la commande Discord (t/export) et par
t/restore (backup des donnees courantes avant ecrasement), sans importer discord.
"""

import os
import tempfile
import zipfile
from datetime import datetime

from tarot_commands.backup_lib import EXCLUDED_DIRS, EXCLUDED_FILES
from tarot_commands.paths import data_dir

# EXCLUDED_FILES / EXCLUDED_DIRS partages avec la sauvegarde restic : jamais
# d'export de secret, ni du depot restic lui-meme.


def build_export(dest_dir=None, src=None):
    """Construit un zip des donnees du bot et retourne son chemin.

    Reprend le perimetre de la sauvegarde restic : les *.json a la racine des
    donnees (players.json pour les noms, history.json pour les points) et tous les
    dossiers de saisons archivees, recursivement. ``src`` permet de forcer le
    dossier source (defaut : ``data_dir()``).
    """
    if src is None:
        src = data_dir()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="tarotbot-export-")
    path = os.path.join(dest_dir, f"tarotbot-export-{stamp}.zip")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(os.listdir(src)):
            full = os.path.join(src, entry)
            if entry in EXCLUDED_FILES or entry in EXCLUDED_DIRS:
                continue
            # Copies de securite locales (restauration, migration,
            # rebuild_history.py) : gardees par restic, inutiles dans l'export.
            if entry.startswith(("_pre_restore_", "_pre_migration_")):
                continue
            if entry.startswith("history.backup-") and entry.endswith(".json"):
                continue
            if os.path.isdir(full):
                for root, _dirs, files in os.walk(full):
                    for filename in files:
                        if filename in EXCLUDED_FILES:
                            continue
                        file_path = os.path.join(root, filename)
                        zf.write(file_path, os.path.relpath(file_path, src))
            elif entry.endswith(".json"):
                zf.write(full, entry)
    return path
