"""Commande t/delete : supprimer une partie ciblee, avec confirmation textuelle."""

from __future__ import annotations

import asyncio

from discord.ext import commands

from tarot_commands.edit import is_snowflake_token
from tarot_commands.help import error_message
from tarot_commands.history import delete_history_entry
from tarot_commands.sessions import find_history_by_message_id
from tarot_commands.state import load_history

CONFIRM_TOKEN = 'oui supprime'
CONFIRM_TIMEOUT = 60

# (author_id, channel_id) en attente de confirmation — un seul delete à la fois.
_pending_delete_keys: set[tuple[int, int]] = set()


def reset_pending_deletes():
    """Vide les confirmations en cours (tests)."""
    _pending_delete_keys.clear()


def is_command_message(content: str) -> bool:
    """True si le message ressemble a une commande t/... (a ignorer pendant la conf.)."""
    return (content or '').strip().lower().startswith('t/')


def is_confirm_token(content: str) -> bool:
    return (content or '').strip() == CONFIRM_TOKEN


def try_begin_delete_confirm(author_id: int, channel_id: int) -> bool:
    """Reserve un slot de confirmation. False si un delete est deja en cours."""
    key = (author_id, channel_id)
    if key in _pending_delete_keys:
        return False
    _pending_delete_keys.add(key)
    return True


def end_delete_confirm(author_id: int, channel_id: int):
    _pending_delete_keys.discard((author_id, channel_id))


def resolve_delete_target(content: str, reference_message_id: int | None):
    """Resout l'id cible, ou None si usage invalide.

    Priorite a un id numerique explicite s'il est present (meme avec une reponse).
    """
    text = (content or '').strip()
    if not text and reference_message_id is None:
        return None

    parts = text.split(None, 1) if text else []
    if parts and is_snowflake_token(parts[0]):
        return int(parts[0])

    if reference_message_id is not None:
        return reference_message_id

    return None


def _join_names(names):
    names = [n for n in (names or []) if n]
    if not names:
        return '—'
    return ', '.join(names)


def format_entry_summary(entry: dict) -> str:
    """Recapitulatif lisible d'une entree history (partie ou descendante)."""
    entry_type = entry.get('type', 'partie')
    lines = []

    if entry_type == 'descendante':
        joueurs = entry.get('joueurs') or []
        points = entry.get('points') or []
        pairs = []
        for i, name in enumerate(joueurs):
            pts = points[i] if i < len(points) else '?'
            pairs.append(f'{name} {pts}')
        lines.append('Descendante : ' + (', '.join(pairs) if pairs else '—'))
    else:
        preneur = entry.get('preneur') or '?'
        enchere = entry.get('enchere') or '?'
        pts = entry.get('points_attaque')
        pts_txt = f'{pts}pts' if pts is not None else '?pts'
        bouts = entry.get('bouts')
        bouts_txt = f'{bouts} bout' + ('' if bouts == 1 else 's') if bouts is not None else '? bouts'
        partenaire = entry.get('partenaire')
        avec = f' avec {partenaire}' if partenaire else ''
        lines.append(f'{preneur} {enchere} {pts_txt} {bouts_txt}{avec}')
        lines.append(f'contre {_join_names(entry.get("defenseurs"))}')

        primes_a = entry.get('primes_attaque') or []
        primes_d = entry.get('primes_defense') or []
        primes_bits = []
        if primes_a:
            primes_bits.append('attaque : ' + ', '.join(primes_a))
        if primes_d:
            primes_bits.append('défense : ' + ', '.join(primes_d))
        if primes_bits:
            lines.append('poignées / primes : ' + ' · '.join(primes_bits))

    miseres = entry.get('miseres') or []
    if miseres:
        lines.append('misères : ' + ', '.join(miseres))

    scores = entry.get('scores') or {}
    if scores:
        score_bits = [f'{name} {int(val) if val == int(val) else val}'
                      for name, val in scores.items()]
        lines.append('scores : ' + ', '.join(score_bits))

    return '\n'.join(lines)


def _confirmation_message_check(ctx):
    """Filtre wait_for : auteur/salon, ignore les commandes t/."""
    def check(msg):
        if msg.author != ctx.author or msg.channel != ctx.channel:
            return False
        if is_command_message(msg.content):
            return False
        return True
    return check


async def _wait_for_confirmation(ctx):
    """Attend `oui supprime`. True si confirme, False si timeout.

    Les messages `t/...` sont ignores (pas de nag). Les autres messages hors
    token declenchent un rappel.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CONFIRM_TIMEOUT
    check = _confirmation_message_check(ctx)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        try:
            msg = await ctx.bot.wait_for(
                'message',
                timeout=remaining,
                check=check,
            )
        except asyncio.TimeoutError:
            return False

        if is_confirm_token(msg.content):
            return True

        await ctx.send(
            'Ce n\'est pas le bon mot de confirmation (faute de frappe ?). '
            f'Tape exactement `{CONFIRM_TOKEN}` pour confirmer, '
            'ou laisse expirer pour annuler.'
        )


@commands.command(name='delete')
async def delete(ctx, *, value: str = ''):
    """Supprime une partie de l'historique apres confirmation (IRREVERSIBLE)."""
    reference_id = None
    if ctx.message.reference and ctx.message.reference.message_id:
        reference_id = ctx.message.reference.message_id

    target_id = resolve_delete_target(value, reference_id)
    if target_id is None:
        await ctx.send(error_message(
            'delete',
            'Indique l’id de la partie, ou réponds au message (commande / tableau).\n'
            'Exemple : `t/delete 1557730091864301699`',
        ))
        return

    history = load_history()
    entry = find_history_by_message_id(history, target_id)
    if entry is None:
        await ctx.send(error_message(
            'delete',
            f'Aucune partie liée à l’id `{target_id}`.',
        ))
        return

    author_id = ctx.author.id
    channel_id = ctx.channel.id
    if not try_begin_delete_confirm(author_id, channel_id):
        await ctx.send(
            'Une confirmation `t/delete` est déjà en cours dans ce salon. '
            f'Termine-la (`{CONFIRM_TOKEN}`) ou attends qu’elle expire '
            f'({CONFIRM_TIMEOUT} s).'
        )
        return

    try:
        canonical_id = entry.get('message_id', target_id)
        summary = format_entry_summary(entry)
        await ctx.send(
            f'Sûr de supprimer la partie `{canonical_id}` ?\n'
            f'{summary}\n'
            f'Confirme en répondant : `{CONFIRM_TOKEN}` '
            f'(tu as {CONFIRM_TIMEOUT} s).'
        )

        if not await _wait_for_confirmation(ctx):
            await ctx.send('Confirmation expirée, rien n’a été supprimé.')
            return

        removed = delete_history_entry(canonical_id)
        if removed is None:
            await ctx.send(error_message(
                'delete',
                f'Aucune partie avec l’id `{canonical_id}` (peut-être déjà supprimée).',
            ))
            return

        await ctx.send(f'Partie `{canonical_id}` supprimée.')
    finally:
        end_delete_confirm(author_id, channel_id)
