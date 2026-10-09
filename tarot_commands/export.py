import asyncio
import os
import shutil

import discord
from discord.ext import commands

from tarot_commands.backup_lib import (
    BackupError,
    backup_dir,
    build_repo_archive,
    copy_to_drive,
    ensure_repo,
    remote_repo,
)
from tarot_commands.export_lib import build_export
from tarot_commands.help import error_message
from tarot_commands.paths import data_dir

# Limite d'upload Discord : 8 Mo par défaut, 25 Mo pour les serveurs boostés.
DISCORD_UPLOAD_LIMIT = 8 * 1024 * 1024

# Références vers les tâches de fond, pour qu'elles ne soient pas ramassées par
# le garbage collector avant la fin de la copie Drive.
_BACKGROUND_TASKS = set()


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


@commands.command()
async def export(ctx, action=None):
    """
    Envoie une archive zip des données (scores, historique, saisons).
    """
    if action is None:
        await _export_zip(ctx)
    elif action.lower() == "backup":
        await _export_backup(ctx)
    else:
        await ctx.send(
            error_message(
                "export",
                f"Action inconnue : `{action}`. Utilise `t/export` ou `t/export backup`.",
            )
        )


async def _export_zip(ctx):
    path = await asyncio.to_thread(build_export)
    try:
        size = os.path.getsize(path)
        if size > DISCORD_UPLOAD_LIMIT:
            await ctx.send(
                f"Export trop volumineux pour Discord ({size / 1_000_000:.1f} Mo). "
                "Utilise `t/export backup` à la place."
            )
            return
        await ctx.send("Export des données :", file=discord.File(path))
    finally:
        # Le dossier temporaire est propre a cette commande : on le supprime.
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def _run_backup_local():
    """Snapshot restic local + zip du depot (sans copie Drive)."""
    ensure_repo()
    snapshot_id = backup_dir(data_dir())
    archive = build_repo_archive()
    return snapshot_id, archive


async def _copy_drive_background(ctx, snapshot_short):
    """Copie Drive en arriere-plan, apres la reponse Discord."""
    try:
        remote, copied = await asyncio.to_thread(copy_to_drive)
        await ctx.send(
            f"Copie Drive à jour (`{snapshot_short}`, {copied} snapshot(s) copié(s)) : `{remote}`."
        )
    except BackupError as exc:
        await ctx.send(
            f"Le snapshot `{snapshot_short}` est bien en local (`data/restic`), "
            f"mais la copie vers Google Drive a échoué : {exc}"
        )


async def _export_backup(ctx):
    await ctx.send("Sauvegarde restic locale en cours...")
    try:
        snapshot_id, archive = await asyncio.to_thread(_run_backup_local)
    except BackupError as exc:
        await ctx.send(error_message("export", str(exc)))
        return

    snapshot_short = snapshot_id[:8]
    try:
        size = os.path.getsize(archive)
        if size > DISCORD_UPLOAD_LIMIT:
            await ctx.send(
                f"Archive trop volumineuse pour Discord ({size / 1_000_000:.1f} Mo). "
                f"Snapshot restic `{snapshot_short}` cree dans `data/restic`. "
                f"Copie vers Google Drive (`{remote_repo()}`) en cours..."
            )
        else:
            await ctx.send(
                f"Snapshot restic `{snapshot_short}` cree. "
                "Archive du depot restic local (tout l'historique) :",
                file=discord.File(archive),
            )
            await ctx.send(f"Copie vers Google Drive (`{remote_repo()}`) en cours...")
    finally:
        shutil.rmtree(os.path.dirname(archive), ignore_errors=True)

    _spawn(_copy_drive_background(ctx, snapshot_short))
