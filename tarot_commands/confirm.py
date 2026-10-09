"""Confirmation par message Discord (wait_for), partagee entre commandes."""

from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

DEFAULT_CANCEL_TOKENS: tuple[str, ...] = ('non',)
DEFAULT_TIMEOUT = 60

# (author_id, channel_id) — une seule confirmation textuelle a la fois.
_pending_keys: set[tuple[int, int]] = set()


def reset_pending_confirms():
    """Vide les confirmations en cours (tests)."""
    _pending_keys.clear()


def is_command_message(content: str) -> bool:
    """True si le message ressemble a une commande t/... (a ignorer)."""
    return (content or '').strip().lower().startswith('t/')


def matches_token(content: str, token: str) -> bool:
    return (content or '').strip() == token


def matches_any_token(content: str, tokens: Iterable[str]) -> bool:
    text = (content or '').strip()
    return text in set(tokens)


def try_begin_confirm(author_id: int, channel_id: int) -> bool:
    """Reserve un slot. False si une confirmation est deja en cours."""
    key = (author_id, channel_id)
    if key in _pending_keys:
        return False
    _pending_keys.add(key)
    return True


def end_confirm(author_id: int, channel_id: int):
    _pending_keys.discard((author_id, channel_id))


def format_cancel_tokens(cancel_tokens: Sequence[str]) -> str:
    return ' / '.join(f'`{t}`' for t in cancel_tokens)


def confirmation_prompt_suffix(
    confirm_token: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    cancel_tokens: Sequence[str] = DEFAULT_CANCEL_TOKENS,
) -> str:
    """Suffixe standard pour le message qui demande confirmation."""
    cancel = format_cancel_tokens(cancel_tokens)
    return (
        f'Confirme en répondant : `{confirm_token}` '
        f'(ou {cancel} pour annuler, {timeout} s).'
    )


def busy_confirm_message(
    command_label: str,
    confirm_token: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    cancel_tokens: Sequence[str] = DEFAULT_CANCEL_TOKENS,
) -> str:
    cancel = format_cancel_tokens(cancel_tokens)
    return (
        f'Une confirmation `{command_label}` est déjà en cours dans ce salon. '
        f'Termine-la (`{confirm_token}` / {cancel}) ou attends '
        f'qu’elle expire ({timeout} s).'
    )


def _message_check(ctx):
    def check(msg):
        if msg.author != ctx.author or msg.channel != ctx.channel:
            return False
        if is_command_message(msg.content):
            return False
        return True
    return check


async def wait_message_confirmation(
    ctx,
    confirm_token: str,
    *,
    cancel_tokens: Sequence[str] = DEFAULT_CANCEL_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Attend une reponse de confirmation.

    Returns
    -------
    str
        ``'confirmed'``, ``'cancelled'`` ou ``'timeout'``.
    """
    cancel_set = tuple(cancel_tokens)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    check = _message_check(ctx)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return 'timeout'
        try:
            msg = await ctx.bot.wait_for(
                'message',
                timeout=remaining,
                check=check,
            )
        except asyncio.TimeoutError:
            return 'timeout'

        if matches_token(msg.content, confirm_token):
            return 'confirmed'
        if matches_any_token(msg.content, cancel_set):
            return 'cancelled'

        cancel = format_cancel_tokens(cancel_set)
        await ctx.send(
            'Ce n\'est pas le bon mot de confirmation (faute de frappe ?). '
            f'Tape exactement `{confirm_token}` pour confirmer, '
            f'{cancel} pour annuler, ou laisse expirer.'
        )
