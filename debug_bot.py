"""Point d'entrée du faux bot de l'environnement de debug."""

import asyncio
import os
import sys

from aiohttp import web

from tarot_commands.internal_api import create_app as create_internal_app
from tarot_commands.state import migrate_state
from tarot_debug.api import add_debug_routes
from tarot_debug.console import Console
from tarot_debug.guardrails import check
from tarot_debug.seed import seed_data_dir

DATA_DIR = os.environ.get("TAROT_DEBUG_DATA_DIR", ".")


async def main():
    check(DATA_DIR)
    seed_data_dir(DATA_DIR)
    migrate_state()
    console = Console(DATA_DIR, user_name=os.environ.get("TAROT_DEBUG_USER_NAME", "Debug User"))
    app = await create_internal_app(
        console.bot,
        token=os.environ["TAROT_INTERNAL_TOKEN"],
        channel_id=os.environ.get("TAROT_CHANNEL_ID", "1"),
        channel_type=type(console.channel),
    )
    add_debug_routes(app, console)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    print("Faux bot debug prêt sur :8081", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Debug bot: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
