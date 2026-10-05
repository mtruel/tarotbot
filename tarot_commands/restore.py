import asyncio
import os
import shutil
import tempfile

import discord
from discord.ext import commands

from tarot_commands.export_lib import build_export
from tarot_commands.help import error_message
from tarot_commands.paths import data_dir
from tarot_commands.restore_lib import (
    RESTIC_SOURCES,
    RestoreError,
    apply_restore,
    read_archive,
    read_snapshot,
)

# Mot de confirmation : comparaison exacte, aucune tolerance.
CONFIRM_TOKEN = 'ecraser_saison_en_cours'

# Budget total (secondes) laisse a l'utilisateur pour confirmer. Ne se recharge
# pas a chaque faute de frappe.
CONFIRM_TIMEOUT = 60

DISCORD_UPLOAD_LIMIT = 8 * 1024 * 1024


async def _wait_for_confirmation(ctx):
    """Attend le mot de confirmation. True si confirme, False si timeout.

    Signale les fautes de frappe sans interrompre l'attente. Le budget est
    global : on recalcule le temps restant a chaque message.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + CONFIRM_TIMEOUT
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        try:
            msg = await ctx.bot.wait_for(
                'message',
                timeout=remaining,
                check=lambda m: m.author == ctx.author
                and m.channel == ctx.channel,
            )
        except asyncio.TimeoutError:
            return False

        if msg.content.strip() == CONFIRM_TOKEN:
            return True

        await ctx.send(
            'Ce n\'est pas le bon mot de confirmation (faute de frappe ?). '
            f'Tape exactement `{CONFIRM_TOKEN}` pour confirmer, '
            'ou laisse expirer pour annuler.'
        )


@commands.command()
@commands.has_permissions(administrator=True)
async def restore(ctx, s='no', source=None):
    """
    Restaure les données depuis une archive zip ou un snapshot restic
    (IRRÉVERSIBLE SANS ACCÈS AU SERVEUR).
    """
    if s != 'IAMSURE':
        await ctx.send(error_message(
            'restore',
            'Pour restaurer les données : `t/restore IAMSURE` avec une archive '
            '`.zip` en pièce jointe, ou `t/restore IAMSURE backup` pour le '
            'dernier snapshot restic.',
        ))
        return

    attachments = [a for a in ctx.message.attachments
                   if a.filename.endswith('.zip')]

    if attachments:
        await _restore_from_attachment(ctx, attachments[0])
    elif source:
        await _restore_from_restic(ctx, source)
    else:
        await ctx.send(error_message(
            'restore',
            'Fournis une archive `.zip` en pièce jointe (par exemple celle de '
            '`t/export`) ou demande un snapshot restic : `t/restore IAMSURE '
            'backup`.',
        ))


async def _restore_from_attachment(ctx, attachment):
    if attachment.size > DISCORD_UPLOAD_LIMIT:
        await ctx.send(error_message(
            'restore',
            f'Archive trop volumineuse ({attachment.size / 1_000_000:.1f} Mo).',
        ))
        return

    work = tempfile.mkdtemp(prefix='tarotbot-restore-')
    try:
        archive = os.path.join(work, 'archive.zip')
        await attachment.save(archive)

        # Validation AVANT le moindre message de confirmation : si l'archive
        # est invalide, rien n'est propose et rien ne sera jamais ecrit.
        try:
            validated = await asyncio.to_thread(read_archive, archive)
        except RestoreError as exc:
            await ctx.send(error_message('restore', str(exc)))
            return

        await _confirm_and_apply(ctx, validated, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def _restore_from_restic(ctx, source):
    # 'latest', 'backup' et 'restic' designent le dernier snapshot ; la
    # normalisation vit dans read_snapshot (partagee avec run_restore.sh).
    await ctx.send('Lecture du snapshot restic en cours...')
    try:
        # Lecture du depot hors de la boucle asyncio pour ne pas bloquer le
        # heartbeat Discord.
        validated = await asyncio.to_thread(read_snapshot, source)
    except RestoreError as exc:
        await ctx.send(error_message('restore', str(exc)))
        return
    await _confirm_and_apply(ctx, validated, None)


async def _confirm_and_apply(ctx, validated, work):
    """Envoie le message de confirmation puis applique la restauration."""
    if work is None:
        work = tempfile.mkdtemp(prefix='tarotbot-restore-')
        cleanup = True
    else:
        cleanup = False
    try:
        # Backup des donnees actuelles, joint au message de confirmation.
        current_backup = await asyncio.to_thread(build_export, work)
        with open(current_backup, 'rb') as f:
            backup_file = discord.File(f, filename=os.path.basename(current_backup))

            await ctx.send(
                'Cette opération est **DESTRUCTIVE**. Êtes-vous sûr ? '
                'Voici une backup des données actuelles.\n'
                f'Tapez `{CONFIRM_TOKEN}` pour confirmer '
                f'(tu as {CONFIRM_TIMEOUT} s).',
                file=backup_file,
            )

        if not await _wait_for_confirmation(ctx):
            await ctx.send('Confirmation expirée, rien n\'a été restauré.')
            return

        snapshot = await asyncio.to_thread(apply_restore, validated, data_dir())
        await ctx.send(
            'Restauration effectuée.\n'
            f'Sauvegarde des données précédentes : `{os.path.basename(snapshot)}`.'
        )
    finally:
        if cleanup:
            shutil.rmtree(work, ignore_errors=True)
