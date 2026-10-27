"""API privée : lecture d'état et enregistrement par le bot (seul écrivain)."""

import asyncio
import contextlib
import hmac
import os
from uuid import UUID

import discord
from aiohttp import web

from tarot_commands.game import format_score_table_message, partie_details
from tarot_commands.history import append_related_message_id, update_history
from tarot_commands.state import load_history, load_player_names
from tarot_commands.web_game import validate_game


async def create_app(bot, *, token=None, channel_id=None, channel_type=None):
    secret = token if token is not None else os.environ.get("TAROT_INTERNAL_TOKEN", "")
    channel = channel_id if channel_id is not None else os.environ.get("TAROT_CHANNEL_ID", "")
    if channel_type is None:
        channel_type = discord.TextChannel
    if not secret:
        raise ValueError("TAROT_INTERNAL_TOKEN manquant")
    if len(secret) < 32:
        raise ValueError("TAROT_INTERNAL_TOKEN trop court")
    if not str(channel).isdigit() or int(channel) <= 0:
        raise ValueError("TAROT_CHANNEL_ID invalide")
    lock = asyncio.Lock()

    @web.middleware
    async def authenticate(request, handler):
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {secret}"):
            raise web.HTTPUnauthorized()
        return await handler(request)

    async def state(_request):
        try:
            return web.json_response({"history": load_history(), "players": load_player_names()})
        except (OSError, ValueError) as exc:
            raise web.HTTPServiceUnavailable(text="Scores indisponibles") from exc

    async def commit(request):
        if request.content_length is not None and request.content_length > 16384:
            raise web.HTTPRequestEntityTooLarge(max_size=16384, actual_size=request.content_length)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Partie invalide")
            commit_id = payload["commit_id"]
            author = payload["web_author"]
            if not isinstance(commit_id, str) or str(UUID(commit_id)) != commit_id:
                raise ValueError("Identifiant de confirmation invalide")
            if (
                not isinstance(author, dict)
                or not isinstance(author.get("id"), str)
                or not author["id"].isdigit()
                or not isinstance(author.get("name"), str)
                or not 0 < len(author["name"]) <= 100
            ):
                raise ValueError("Auteur invalide")
            async with lock:
                for entry in load_history():
                    if entry.get("web_commit_id") == commit_id:
                        return web.json_response(
                            {"message_id": entry["message_id"], "duplicate": True}
                        )
                session, scores = validate_game(payload["game"])
                if bot.is_closed() or not bot.is_ready():
                    raise web.HTTPServiceUnavailable(text="Discord indisponible")
                target = bot.get_channel(int(channel)) or await bot.fetch_channel(int(channel))
                if not isinstance(target, channel_type):
                    raise web.HTTPServiceUnavailable(text="Salon inaccessible")
                # Aucun await entre la lecture et l'écriture dans update_history.
                announcement = await target.send(
                    f"Partie saisie sur le web par {discord.utils.escape_mentions(author['name'])} "
                    f"({author['id']}). Contrat : {session.enchere}, "
                    f"preneur : {discord.utils.escape_mentions(session.game_players['Preneur'][0])}. "
                    f"Bouts : {session.bouts}, points attaque : {session.points_attaque}. "
                    f"Partenaire : {discord.utils.escape_mentions(session.game_players['Partenaire'][0]) if session.game_players['Partenaire'] else 'aucun'}. "
                    f"Défense : {', '.join(discord.utils.escape_mentions(p) for p in session.game_players['Défenseurs'])}. "
                    f"Primes attaque : {', '.join(session.primes_attaque) or 'aucune'} ; "
                    f"primes défense : {', '.join(session.primes_defense) or 'aucune'} ; "
                    f"misères : {', '.join(discord.utils.escape_mentions(p) for p in session.miseres) or 'aucune'}. "
                    f"Référence web : {commit_id}.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                session.request_message_id = announcement.id
                details = partie_details(session)
                details.update(web_author={"id": author["id"], "name": author["name"]})
                details["web_commit_id"] = commit_id
                try:
                    update_history(scores, details)
                except (OSError, ValueError):
                    # Ne pas laisser un message orphelin faire croire que la partie est sauvée.
                    with contextlib.suppress(discord.HTTPException):
                        await announcement.delete()
                    raise

                try:
                    score_msg = await target.send(
                        format_score_table_message(scores, announcement.id),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    append_related_message_id(announcement.id, score_msg.id)
                except discord.HTTPException:
                    # La partie est déjà écrite : ne pas renvoyer une erreur qui inciterait
                    # à la recréer. L'annonce reste utilisable pour t/edit ou t/delete.
                    return web.json_response({"message_id": announcement.id, "table_sent": False})
                return web.json_response({"message_id": announcement.id, "table_sent": True})
        except OSError as exc:
            raise web.HTTPServiceUnavailable(text="Historique indisponible") from exc
        except discord.HTTPException as exc:
            raise web.HTTPServiceUnavailable(text="Discord indisponible") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

    app = web.Application(middlewares=[authenticate], client_max_size=16384)
    app.router.add_get("/state", state)
    app.router.add_post("/commit", commit)
    return app


async def start_api(bot):
    if not os.environ.get("TAROT_INTERNAL_TOKEN"):
        return None
    app = await create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    return runner
