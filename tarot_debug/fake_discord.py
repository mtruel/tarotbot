"""Faux objets Discord pour rejouer les commandes sans gateway."""

from __future__ import annotations

import asyncio
import itertools

import discord

_UNSET = object()


class _FakeHTTPResponse:
    status = 404
    reason = "Not Found"


class FakeUser:
    def __init__(self, user_id=1, name="Debug User"):
        self.id = user_id
        self.name = name
        self.display_name = name
        self.bot = False

    def __eq__(self, other):
        return isinstance(other, FakeUser) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class FakeMessage:
    def __init__(self, message_id, content, author, channel, *, reference=None):
        self.id = message_id
        self.content = content
        self.author = author
        self.channel = channel
        self.reference = reference
        self.view = None
        self.ephemeral = False
        self.deleted = False

    async def edit(self, *, content=_UNSET, view=_UNSET, **_kwargs):
        if content is not _UNSET:
            self.content = content
        if view is not _UNSET:
            self.view = view
        return self

    async def delete(self):
        self.deleted = True

    async def add_reaction(self, *_args, **_kwargs):
        return None


class FakeChannel:
    def __init__(self, channel_id=1, name="debug"):
        self.id = channel_id
        self.name = name
        self.messages = []
        self._ids = itertools.count(1000)

    def new_id(self):
        return next(self._ids)

    async def send(self, content=None, *, view=None, file=None, **_kwargs):
        message = FakeMessage(self.new_id(), content or "", None, self)
        message.view = view
        self.messages.append(message)
        return message

    async def fetch_message(self, message_id):
        for message in self.messages:
            if message.id == message_id:
                return message
        raise discord.NotFound(_FakeHTTPResponse(), "Unknown Message")


class FakeBot:
    def __init__(self, channel, user):
        self.channel = channel
        self.user = user
        self._queue = asyncio.Queue()
        self._closed = False

    def is_closed(self):
        return self._closed

    def is_ready(self):
        return True

    def get_channel(self, channel_id):
        return self.channel if channel_id == self.channel.id else None

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    def push_message(self, message):
        self._queue.put_nowait(message)

    async def wait_for(self, event, *, timeout=None, check=None):
        if event != "message":
            raise ValueError(f"Événement non supporté : {event}")
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise TimeoutError
            message = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            if check is None or check(message):
                return message


class FakeContext:
    def __init__(self, bot, message, *, command=None, invoked_with=""):
        self.bot = bot
        self.message = message
        self.channel = message.channel
        self.author = message.author
        self.guild = None
        self.command = command
        self.invoked_with = invoked_with

    async def send(self, content=None, *, view=None, file=None, **kwargs):
        return await self.channel.send(content, view=view, file=file, **kwargs)


class FakeInteractionResponse:
    def __init__(self, interaction):
        self.interaction = interaction

    async def send_message(self, content=None, *, ephemeral=False, **_kwargs):
        message = await self.interaction.channel.send(content)
        message.ephemeral = ephemeral
        return message

    async def edit_message(self, *, content=_UNSET, view=_UNSET, **_kwargs):
        return await self.interaction.message.edit(content=content, view=view)

    async def defer(self, **_kwargs):
        return None


class FakeFollowup:
    def __init__(self, interaction):
        self.interaction = interaction

    async def send(self, content=None, *, ephemeral=False, **kwargs):
        message = await self.interaction.channel.send(content, **kwargs)
        message.ephemeral = ephemeral
        return message


class FakeInteraction:
    def __init__(self, *, user, channel, message=None):
        self.user = user
        self.channel = channel
        self.message = message
        self.response = FakeInteractionResponse(self)
        self.followup = FakeFollowup(self)
