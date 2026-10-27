from aiohttp import web

from tarot_web.app import create_app

web.run_app(create_app(), host="0.0.0.0", port=8080)
