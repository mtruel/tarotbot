"""Console de commandes : rejoue les commandes Discord sur un faux salon."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import Awaitable, Callable
from typing import cast

import discord

from tarot_commands.add_player import add_player, add_players
from tarot_commands.confirm import reset_pending_confirms
from tarot_commands.delete import delete
from tarot_commands.edit import edit
from tarot_commands.game import auto, descendante, game
from tarot_commands.help import help as help_command
from tarot_commands.history import history
from tarot_commands.leaderboard import leaderboard, leaderboard2
from tarot_commands.ping import ping
from tarot_commands.rules import rules
from tarot_commands.sessions import clear_all_sessions
from tarot_commands.undo import undo
from tarot_debug.fake_discord import (
    FakeBot,
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMessage,
    FakeUser,
)
from tarot_debug.seed import seed_data_dir


def _value(args):
    return (), {"value": args}


def _msg(args):
    return (), {"msg": args}


def _points(args):
    return tuple(args.split()), {}


def _first(args):
    parts = args.split()
    return (parts[0] if parts else "",), {}


def _parts(args):
    return tuple(args.split()), {}


def _arg(args):
    parts = args.split()
    return (parts[0] if parts else None,), {}


def _none(_args):
    return (), {}


COMMANDS = {
    "add_player": (add_player, _first),
    "add_players": (add_players, _msg),
    "auto": (auto, _value),
    "delete": (delete, _value),
    "descendante": (descendante, _points),
    "edit": (edit, _value),
    "game": (game, _first),
    "help": (help_command, _parts),
    "history": (history, _value),
    "leaderboard": (leaderboard, _none),
    "leaderboard2": (leaderboard2, _none),
    "ping": (ping, _none),
    "rules": (rules, _arg),
    "undo": (undo, _none),
}


def parse_command(text):
    text = (text or "").strip()
    if not text.startswith("t/"):
        raise ValueError("Les commandes commencent par t/.")
    parts = text[2:].split(maxsplit=1)
    if not parts:
        raise ValueError("Commande vide.")
    name = parts[0].lower()
    if name not in COMMANDS:
        raise ValueError(f"Commande inconnue : t/{name}")
    return name, parts[1] if len(parts) > 1 else ""


def serialize_message(message):
    return {
        "id": message.id,
        "kind": "system" if message.ephemeral else "bot",
        "text": message.content,
        "view": serialize_view(message.view, message.id) if message.view else None,
    }


def serialize_view(view, message_id):
    items = []
    for item in view.children:
        if isinstance(item, discord.ui.Button):
            items.append(
                {
                    "id": item.custom_id,
                    "type": "button",
                    "label": item.label,
                    "style": item.style.name.lower(),
                    "disabled": item.disabled,
                }
            )
        elif isinstance(item, discord.ui.Select):
            items.append(
                {
                    "id": item.custom_id,
                    "type": "select",
                    "placeholder": item.placeholder,
                    "min_values": item.min_values,
                    "max_values": item.max_values,
                    "options": [
                        {
                            "label": option.label,
                            "value": option.value,
                            "emoji": str(option.emoji) if option.emoji else None,
                        }
                        for option in item.options
                    ],
                    "disabled": item.disabled,
                }
            )
    return {"message_id": message_id, "items": items}


class Console:
    """Une session de debug : un auteur, un salon, une file de confirmations."""

    def __init__(self, data_dir=".", *, user_name="Debug User"):
        self.data_dir = data_dir
        self.user = FakeUser(1, user_name)
        self.channel = FakeChannel(1)
        self.bot = FakeBot(self.channel, self.user)
        self._user_ids = itertools.count(1_000_000)
        self._cursor = 0
        self._task = None
        self._lock = asyncio.Lock()

    async def execute_text(self, text):
        async with self._lock:
            if not text.strip():
                await self._settle()
                return self._response()
            if self._task is not None and not self._task.done():
                if text.strip().startswith("t/"):
                    reminder = FakeMessage(
                        self.channel.new_id(),
                        "Une confirmation est en attente : réponds au mot demandé ci-dessus, "
                        "ou `non` pour annuler.",
                        None,
                        self.channel,
                    )
                    reminder.ephemeral = True
                    self.channel.messages.append(reminder)
                    return self._response()
                self.bot.push_message(self._user_message(text))
                await self._settle()
                return self._response()
            name, args = parse_command(text)
            message = self._user_message(text)
            ctx = FakeContext(self.bot, message, command=COMMANDS[name][0], invoked_with=name)
            self._task = asyncio.create_task(self._run(name, args, ctx))
            await self._settle()
            return self._response()

    async def execute_interaction(self, message_id, item_id, values):
        async with self._lock:
            message = await self.channel.fetch_message(int(message_id))
            view = message.view
            if view is None:
                raise ValueError("Ce message n'a pas de vue interactive.")
            item = next((child for child in view.children if child.custom_id == item_id), None)
            if item is None:
                raise ValueError("Élément interactif inconnu.")
            if isinstance(item, discord.ui.Select):
                selected = list(values)
                if not item.min_values <= len(selected) <= item.max_values:
                    raise ValueError(
                        f"Ce menu attend entre {item.min_values} et {item.max_values} valeurs."
                    )
                item._values = selected
            interaction = FakeInteraction(user=self.user, channel=self.channel, message=message)
            await item.callback(interaction)
            await self._settle()
            return self._response()

    async def reset(self):
        async with self._lock:
            if self._task is not None and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            self._task = None
            self.channel.messages.clear()
            self._cursor = 0
            clear_all_sessions()
            reset_pending_confirms()
            seed_data_dir(self.data_dir, reset=True)

    def _user_message(self, text):
        return FakeMessage(next(self._user_ids), text, self.user, self.channel)

    async def _settle(self):
        if self._task is None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(self._task), timeout=0.2)

    def _response(self):
        messages = self.channel.messages[self._cursor :]
        self._cursor = len(self.channel.messages)
        if self._task is not None and self._task.done():
            error = self._task.exception()
            self._task = None
            if error is not None:
                message = FakeMessage(
                    self.channel.new_id(), f"Erreur interne : {error}", None, self.channel
                )
                self.channel.messages.append(message)
                messages.append(message)
                self._cursor = len(self.channel.messages)
        return {
            "messages": [serialize_message(message) for message in messages],
            "pending": self._task is not None,
        }

    async def _run(self, name, args, ctx):
        command, parse = COMMANDS[name]
        positional, keyword = parse(args)
        callback = cast(Callable[..., Awaitable[None]], command.callback)
        await callback(ctx, *positional, **keyword)
