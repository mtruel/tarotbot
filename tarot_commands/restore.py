import asyncio
import os
import shutil
import tempfile

import discord
from discord.ext import commands

from tarot_commands.confirm import (
    DEFAULT_TIMEOUT,
    busy_confirm_message,
    confirmation_prompt_suffix,
    end_confirm,
    try_begin_confirm,
    wait_message_confirmation,
)
from tarot_commands.export_lib import build_export
from tarot_commands.help import error_message
from tarot_commands.paths import data_dir
from tarot_commands.restore_lib import (
    RestoreError,
    apply_restore,
    read_archive,
    read_snapshot,
)

# Mot de confirmation : comparaison exacte, aucune tolerance.
CONFIRM_TOKEN = 'ecraser_saison_en_cours'
CONFIRM_TIMEOUT = DEFAULT_TIMEOUT

DISCORD_UPLOAD_LIMIT = 8 * 1024 * 1024


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

    author_id = ctx.author.id
    channel_id = ctx.channel.id
    if not try_begin_confirm(author_id, channel_id):
        await ctx.send(busy_confirm_message(
            't/restore', CONFIRM_TOKEN, timeout=CONFIRM_TIMEOUT,
        ))
        if cleanup:
            shutil.rmtree(work, ignore_errors=True)
        return

    try:
        # Backup des donnees actuelles, joint au message de confirmation.
        current_backup = await asyncio.to_thread(build_export, work)
        with open(current_backup, 'rb') as f:
            backup_file = discord.File(f, filename=os.path.basename(current_backup))

            await ctx.send(
                'Cette opération est **DESTRUCTIVE**. Êtes-vous sûr ? '
                'Voici une backup des données actuelles.\n'
                + confirmation_prompt_suffix(
                    CONFIRM_TOKEN, timeout=CONFIRM_TIMEOUT,
                ),
                file=backup_file,
            )

        outcome = await wait_message_confirmation(
            ctx, CONFIRM_TOKEN, timeout=CONFIRM_TIMEOUT,
        )
        if outcome == 'timeout':
            await ctx.send('Confirmation expirée, rien n\'a été restauré.')
            return
        if outcome == 'cancelled':
            await ctx.send('Annulé, rien n\'a été restauré.')
            return

        snapshot = await asyncio.to_thread(apply_restore, validated, data_dir())
        await ctx.send(
            'Restauration effectuée.\n'
            f'Sauvegarde des données précédentes : `{os.path.basename(snapshot)}`.'
        )
    finally:
        end_confirm(author_id, channel_id)
        if cleanup:
            shutil.rmtree(work, ignore_errors=True)
