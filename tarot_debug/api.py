"""Endpoints HTTP de la console, ajoutés à l'API interne du bot."""

from aiohttp import web


def add_debug_routes(app, console):
    async def command(request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Payload invalide")
            # session_id est accepté pour le protocole, mais une seule session existe.
            if "interaction" in payload:
                interaction = payload["interaction"]
                if not isinstance(interaction, dict):
                    raise ValueError("Interaction invalide")
                result = await console.execute_interaction(
                    interaction["message_id"],
                    interaction["item_id"],
                    interaction.get("values", []),
                )
            else:
                text = payload.get("text", "")
                if not isinstance(text, str):
                    raise ValueError("Texte invalide")
                result = await console.execute_text(text)
            return web.json_response(result)
        except (KeyError, TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

    async def reset(_request):
        await console.reset()
        return web.json_response({"ok": True})

    app.router.add_post("/debug/command", command)
    app.router.add_post("/debug/reset", reset)
    return app
