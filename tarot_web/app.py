"""Pages SSR du tarot, avec accès aux scores réservé aux membres Discord."""

import hmac
import os
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from aiohttp import ClientSession, ClientTimeout, web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tarot_commands.rules import PRIMES
from tarot_commands.state import compute_scores, known_players
from tarot_commands.web_game import InvalidGame, validate_game

DISCORD_API = "https://discord.com/api/v10"
COOKIE = "tarot_session"
SESSION_KEY = web.RequestKey("session", dict)
FORM_KEY = web.RequestKey("form", object)
ROOT = Path(__file__).parent
TEMPLATES = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())


def setting(name):
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"Configuration manquante : {name}")
    return value


def render(name, **context):
    return web.Response(
        text=TEMPLATES.get_template(name).render(**context), content_type="text/html"
    )


def statistics(history, players):
    totals = compute_scores(history, players)
    rows = []
    for name, total in totals.items():
        values = [g["scores"][name] for g in history if name in g["scores"]]
        count = len(values)
        mean = total / count if count else 0
        variance = sum((x - mean) ** 2 for x in values) / (count - 1) if count > 1 else 0
        rows.append(
            dict(
                name=name,
                points=int(total),
                games=count,
                mean=int(mean),
                wins=sum(v >= 0 for v in values),
                losses=sum(v < 0 for v in values),
                deviation=int(variance**0.5),
            )
        )
    return sorted(rows, key=lambda p: p["points"], reverse=True)


def chart_svg(history, players):
    """Courbes cumulées, SVG autonome ; noms échappés par Jinja dans la légende HTML."""
    from xml.sax.saxutils import escape

    players = list(players)[:12]
    totals = dict.fromkeys(players, 0)
    lines = {name: [0] for name in players}
    for game in history:
        for name in players:
            totals[name] += game["scores"].get(name, 0)
            lines[name].append(totals[name])
    values = [v for series in lines.values() for v in series] or [0]
    low, high = min(values), max(values)
    span = max(high - low, 1)
    count = max(len(history), 1)
    elements = [
        '<svg viewBox="0 0 800 240" role="img" aria-label="Évolution des points cumulés" xmlns="http://www.w3.org/2000/svg">'
    ]
    elements.append('<line x1="30" y1="210" x2="790" y2="210" stroke="currentColor"/>')
    for index, (name, series) in enumerate(lines.items()):
        color = f"hsl({(index * 137) % 360} 65% 45%)"
        elements.append(f"<title>{escape(name)}</title>")
        coordinates = " ".join(
            f"{30 + 760 * i / count:.1f},{210 - 180 * (value - low) / span:.1f}"
            for i, value in enumerate(series)
        )
        elements.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coordinates}"/>'
        )
    elements.append("</svg>")
    return "".join(elements)


def parse_form(data):
    def number(key):
        value = data.get(key, "")
        if not isinstance(value, str) or not value.isdecimal():
            raise InvalidGame(f"{key} invalide.")
        return int(value)

    joueurs = data.getall("joueurs", [])
    if len(joueurs) not in (3, 4, 5) or len(set(joueurs)) != len(joueurs):
        raise InvalidGame("Choisis 3 à 5 joueurs distincts.")
    preneur = data.get("preneur")
    partenaire = data.get("partenaire") or None
    if preneur not in joueurs:
        raise InvalidGame("Choisis un preneur parmi les joueurs de la partie.")
    if partenaire and (len(joueurs) != 5 or partenaire not in joueurs or partenaire == preneur):
        raise InvalidGame("Le partenaire doit être un autre joueur de la partie à cinq.")
    miseres = data.getall("miseres", [])
    if any(player not in joueurs for player in miseres):
        raise InvalidGame("Les misères doivent appartenir aux joueurs de la partie.")
    return {
        "points_attaque": number("points_attaque"),
        "bouts": number("bouts"),
        "enchere": number("enchere"),
        "preneur": preneur,
        "partenaire": partenaire,
        "defenseurs": [p for p in joueurs if p not in (preneur, partenaire)],
        "miseres": miseres,
        "primes_attaque": data.getall("primes_attaque", []),
        "primes_defense": data.getall("primes_defense", []),
    }


async def create_app(*, http=None, config=None):
    debug = (
        config.get("TAROT_DEBUG") == "1"
        if config is not None
        else os.environ.get("TAROT_DEBUG") == "1"
    )
    if debug and os.environ.get("DISCORD_TOKEN"):
        raise ValueError("DISCORD_TOKEN ne doit pas être défini en debug")
    if config is None:
        keys = ["WEB_SESSION_SECRET", "TAROT_INTERNAL_TOKEN"]
        if not debug:
            keys = [
                "DISCORD_OAUTH_CLIENT_ID",
                "DISCORD_OAUTH_CLIENT_SECRET",
                "DISCORD_OAUTH_REDIRECT_URI",
                *keys,
            ]
        config = {key: setting(key) for key in keys}
    guild_id = (
        config.get("DISCORD_GUILD_ID")
        if "DISCORD_GUILD_ID" in config
        else os.environ.get("DISCORD_GUILD_ID", "")
    ) or ""
    if not debug and not config["DISCORD_OAUTH_REDIRECT_URI"].startswith("https://"):
        raise ValueError("Redirection OAuth non HTTPS")
    if len(config["WEB_SESSION_SECRET"]) < 32 or len(config["TAROT_INTERNAL_TOKEN"]) < 32:
        raise ValueError("Secrets trop courts : générer des valeurs aléatoires longues")
    owns_http = http is None
    if http is None:
        http = ClientSession(timeout=ClientTimeout(total=10), trust_env=False)
    sessions = {}
    pending_login = {}
    secret = config["TAROT_INTERNAL_TOKEN"]
    session_secret = config["WEB_SESSION_SECRET"].encode()

    def page(name, **context):
        context.setdefault("debug", debug)
        context.setdefault("debug_data_dir", os.environ.get("TAROT_DEBUG_DATA_DIR", "/data"))
        context.setdefault("debug_commit", os.environ.get("GIT_COMMIT", "unknown"))
        return render(name, **context)

    def signed_cookie(sid):
        return f"{sid}.{hmac.digest(session_secret, sid.encode(), 'sha256').hex()}"

    async def close_sessions(_app):
        sessions.clear()
        pending_login.clear()

    def verify_cookie(value):
        sid, separator, _signature = value.partition(".")
        if not separator or not hmac.compare_digest(signed_cookie(sid), value):
            return ""
        return sid

    async def discord_get(path, access):
        async with http.get(
            f"{DISCORD_API}{path}", headers={"Authorization": f"Bearer {access}"}
        ) as response:
            if response.status != 200:
                raise web.HTTPUnauthorized(
                    text="Session Discord expirée ou vérification impossible"
                )
            return await response.json()

    async def state():
        try:
            async with http.get(
                "http://tarotbot:8081/state", headers={"Authorization": f"Bearer {secret}"}
            ) as response:
                if response.status != 200:
                    raise web.HTTPServiceUnavailable(text="Scores indisponibles")
                return await response.json()
        except (OSError, TimeoutError) as exc:
            raise web.HTTPServiceUnavailable(text="Bot indisponible") from exc

    debug_session = {
        "access": "",
        "user": {
            "id": "1",
            "name": os.environ.get("TAROT_DEBUG_USER_NAME", "Debug User"),
        },
        "csrf": secrets.token_urlsafe(32),
        "expires": float("inf"),
        "guild_checked": float("inf"),
        "preview": None,
        "commits": deque(),
    }

    @web.middleware
    async def secure(request, handler):
        request[SESSION_KEY] = None
        if not debug and request.path.startswith("/debug/"):
            raise web.HTTPNotFound()
        if debug:
            request[SESSION_KEY] = debug_session
        elif request.path not in (
            "/login",
            "/auth/discord",
            "/oauth/callback",
        ) and not request.path.startswith("/static/"):
            sid = verify_cookie(request.cookies.get(COOKIE, ""))
            session = sessions.get(sid)
            if session and session["expires"] <= time.monotonic():
                sessions.pop(sid, None)
                session = None
            if not session:
                if request.path != "/":
                    raise web.HTTPFound("/")
            else:
                if not guild_id:
                    raise web.HTTPForbidden(text="Serveur Discord non configuré")
                if session["guild_checked"] <= time.monotonic():
                    guilds = await discord_get("/users/@me/guilds", session["access"])
                    if guild_id not in {g["id"] for g in guilds}:
                        sessions.pop(sid, None)
                        raise web.HTTPForbidden(text="Compte hors du serveur")
                    session["guild_checked"] = time.monotonic() + 300
                request[SESSION_KEY] = session
        if request.method == "POST":
            session = request[SESSION_KEY]
            if session is None:
                raise web.HTTPForbidden()
            if request.path == "/debug/command":
                supplied = request.headers.get("X-CSRF-Token", "")
                if not hmac.compare_digest(supplied, session["csrf"]):
                    raise web.HTTPForbidden(text="Jeton de formulaire incorrect")
            else:
                data = await request.post()
                request[FORM_KEY] = data
                if not hmac.compare_digest(str(data.get("csrf", "")), session["csrf"]):
                    raise web.HTTPForbidden(text="Jeton de formulaire incorrect")
        response = await handler(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def login(_request):
        if debug:
            raise web.HTTPFound("/")
        return page("login.html")

    async def start_discord_login(_request):
        if debug:
            raise web.HTTPFound("/")
        nonce = secrets.token_urlsafe(32)
        now = time.monotonic()
        for sid, session in list(sessions.items()):
            if session["expires"] <= now:
                sessions.pop(sid, None)
        for key, expiry in list(pending_login.items()):
            if expiry < now:
                pending_login.pop(key, None)
        pending_login[nonce] = now + 300
        query = urlencode(
            {
                "client_id": config["DISCORD_OAUTH_CLIENT_ID"],
                "redirect_uri": config["DISCORD_OAUTH_REDIRECT_URI"],
                "response_type": "code",
                "scope": "identify guilds",
                "state": nonce,
            }
        )
        response = web.HTTPFound(f"https://discord.com/oauth2/authorize?{query}")
        response.set_cookie(
            "oauth_state", nonce, max_age=300, httponly=True, secure=True, samesite="Lax"
        )
        raise response

    async def callback(request):
        if debug:
            raise web.HTTPFound("/")
        nonce = request.query.get("state", "")
        cookie_nonce = request.cookies.get("oauth_state", "")
        if (
            not nonce
            or not hmac.compare_digest(nonce, cookie_nonce)
            or pending_login.pop(nonce, 0) < time.monotonic()
        ):
            raise web.HTTPForbidden(text="Connexion OAuth invalide")
        code = request.query.get("code", "")
        if not code or not guild_id:
            raise web.HTTPForbidden(text="Connexion impossible")
        async with http.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": config["DISCORD_OAUTH_CLIENT_ID"],
                "client_secret": config["DISCORD_OAUTH_CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config["DISCORD_OAUTH_REDIRECT_URI"],
            },
        ) as response:
            if response.status != 200:
                raise web.HTTPForbidden(text="Échange OAuth refusé")
            token = await response.json()
        access = token["access_token"]
        user = await discord_get("/users/@me", access)
        guilds = await discord_get("/users/@me/guilds", access)
        if guild_id not in {g["id"] for g in guilds}:
            raise web.HTTPForbidden(text="Compte hors du serveur")
        sid = secrets.token_urlsafe(32)
        sessions[sid] = {
            "access": access,
            "user": {"id": user["id"], "name": user.get("global_name") or user["username"]},
            "csrf": secrets.token_urlsafe(32),
            "expires": time.monotonic() + min(43200, int(token.get("expires_in", 3600))),
            "guild_checked": time.monotonic() + 300,
            "preview": None,
            "commits": deque(),
        }
        result = web.HTTPFound("/")
        result.set_cookie(
            COOKIE,
            signed_cookie(sid),
            max_age=min(43200, int(token.get("expires_in", 3600))),
            httponly=True,
            secure=True,
            samesite="Lax",
        )
        result.del_cookie("oauth_state")
        raise result

    async def home(request):
        if request[SESSION_KEY] is None:
            return render("login.html")
        snapshot = await state()
        history = snapshot["history"]
        players = snapshot["players"]
        names = known_players(history, players)
        return page(
            "home.html",
            rows=statistics(history, players),
            recent=list(reversed(history[-10:])),
            chart=chart_svg(history, names),
            user=request[SESSION_KEY]["user"],
            csrf=request[SESSION_KEY]["csrf"],
        )

    async def logout(request):
        if debug:
            raise web.HTTPFound("/")
        sid = verify_cookie(request.cookies.get(COOKIE, ""))
        sessions.pop(sid, None)
        result = web.HTTPFound("/login")
        result.del_cookie(COOKIE)
        raise result

    def game_page(request, names, form=None, *, error="", scores=None, commit_id=""):
        return page(
            "game.html",
            players=names,
            primes=list(PRIMES),
            csrf=request[SESSION_KEY]["csrf"],
            selected_players=form.getall("joueurs", []) if form else [],
            selected_miseres=form.getall("miseres", []) if form else [],
            selected_primes_attaque=form.getall("primes_attaque", []) if form else [],
            selected_primes_defense=form.getall("primes_defense", []) if form else [],
            preneur=form.get("preneur", "") if form else "",
            partenaire=form.get("partenaire", "") if form else "",
            points_attaque=form.get("points_attaque", "") if form else "",
            bouts=form.get("bouts", "") if form else "",
            enchere=form.get("enchere", "") if form else "",
            error=error,
            scores=scores,
            commit_id=commit_id,
            game_data=parse_form(form) if scores is not None else None,
        )

    async def game(request):
        snapshot = await state()
        names = known_players(snapshot["history"], snapshot["players"])
        return game_page(request, names)

    async def preview(request):
        request[SESSION_KEY]["preview"] = None
        snapshot = await state()
        names = known_players(snapshot["history"], snapshot["players"])
        try:
            game_data = parse_form(request[FORM_KEY])
            _session, scores = validate_game(game_data, names)
        except InvalidGame as exc:
            return game_page(request, names, request[FORM_KEY], error=str(exc))
        commit_id = str(uuid4())
        request[SESSION_KEY]["preview"] = (commit_id, game_data)
        return game_page(request, names, request[FORM_KEY], scores=scores, commit_id=commit_id)

    async def commit(request):
        session = request[SESSION_KEY]
        previewed = session["preview"]
        if not previewed or not hmac.compare_digest(
            str(request[FORM_KEY].get("commit_id", "")), previewed[0]
        ):
            raise web.HTTPForbidden(text="Aperçu expiré")
        try:
            current_game = parse_form(request[FORM_KEY])
        except InvalidGame as exc:
            raise web.HTTPConflict(text="La partie a changé. Recalcule l’aperçu.") from exc
        if current_game != previewed[1]:
            raise web.HTTPConflict(text="La partie a changé. Recalcule l’aperçu.")
        now = time.monotonic()
        recent = session["commits"]
        while recent and recent[0] < now - 60:
            recent.popleft()
        if len(recent) >= 3:
            raise web.HTTPTooManyRequests(text="Réessaie dans une minute")
        payload = {"commit_id": previewed[0], "game": previewed[1], "web_author": session["user"]}
        try:
            async with http.post(
                "http://tarotbot:8081/commit",
                json=payload,
                headers={"Authorization": f"Bearer {secret}"},
            ) as response:
                if response.status != 200:
                    raise web.HTTPServiceUnavailable(
                        text="Enregistrement indisponible, réessaie avec la même confirmation"
                    )
                result = await response.json()
        except (OSError, TimeoutError) as exc:
            raise web.HTTPServiceUnavailable(
                text="Bot indisponible, réessaie avec la même confirmation"
            ) from exc
        session["preview"] = None
        recent.append(now)
        return page(
            "saved.html",
            message_id=result["message_id"],
            table_sent=result.get("table_sent", True),
            csrf=request[SESSION_KEY]["csrf"],
        )

    async def debug_console(request):
        return page(
            "console.html",
            user=request[SESSION_KEY]["user"],
            csrf=request[SESSION_KEY]["csrf"],
        )

    async def debug_command(request):
        try:
            payload = await request.json()
            async with http.post(
                "http://tarotbot:8081/debug/command",
                json=payload,
                headers={"Authorization": f"Bearer {secret}"},
            ) as response:
                if response.status != 200:
                    raise web.HTTPServiceUnavailable(text="Console indisponible")
                return web.json_response(await response.json())
        except (OSError, TimeoutError) as exc:
            raise web.HTTPServiceUnavailable(text="Bot indisponible") from exc
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

    async def debug_reset(_request):
        try:
            async with http.post(
                "http://tarotbot:8081/debug/reset",
                headers={"Authorization": f"Bearer {secret}"},
            ) as response:
                if response.status != 200:
                    raise web.HTTPServiceUnavailable(text="Réinitialisation indisponible")
        except (OSError, TimeoutError) as exc:
            raise web.HTTPServiceUnavailable(text="Bot indisponible") from exc
        raise web.HTTPFound("/")

    app = web.Application(middlewares=[secure], client_max_size=16384)
    app.router.add_get("/login", login)
    app.router.add_get("/auth/discord", start_discord_login)
    app.router.add_get("/oauth/callback", callback)
    app.router.add_get("/", home)
    app.router.add_post("/logout", logout)
    app.router.add_get("/game", game)
    app.router.add_post("/preview", preview)
    app.router.add_post("/commit", commit)
    app.router.add_get("/debug/chat", debug_console)
    app.router.add_post("/debug/command", debug_command)
    app.router.add_post("/debug/reset", debug_reset)
    app.router.add_static("/static/", ROOT / "static")
    app.on_cleanup.append(close_sessions)
    if owns_http:

        async def close(_app):
            await http.close()

        app.on_cleanup.append(close)
    return app
