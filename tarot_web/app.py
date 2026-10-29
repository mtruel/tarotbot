"""Pages SSR du tarot, avec accès aux scores réservé aux membres Discord."""

import hmac
import os
import secrets
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from aiohttp import ClientSession, ClientTimeout, web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tarot_commands.rules import CONTRAT_PAR_BOUT, PRIMES
from tarot_commands.state import compute_scores, known_players
from tarot_commands.web_game import InvalidGame, validate_game

DISCORD_API = "https://discord.com/api/v10"
COOKIE = "tarot_session"
SESSION_KEY = web.RequestKey("session", dict)
FORM_KEY = web.RequestKey("form", object)
ROOT = Path(__file__).parent
HISTORY_PAGE_SIZE = 20
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
        takes = attacks = defenses = unknown_roles = 0
        for game in history:
            if name not in game["scores"] or game.get("type") == "descendante":
                continue
            if name == game.get("preneur"):
                takes += 1
                attacks += 1
            elif name == game.get("partenaire"):
                attacks += 1
            elif name in (game.get("defenseurs") or []):
                defenses += 1
            else:
                unknown_roles += 1
        mean = total / count if count else 0
        variance = sum((x - mean) ** 2 for x in values) / (count - 1) if count > 1 else 0
        rows.append(
            dict(
                name=name,
                points=int(total),
                games=count,
                takes=takes,
                attacks=attacks,
                defenses=defenses,
                unknown_roles=unknown_roles,
                mean=int(mean),
                wins=sum(v >= 0 for v in values),
                losses=sum(v < 0 for v in values),
                deviation=int(variance**0.5),
            )
        )
    return sorted(rows, key=lambda p: p["points"], reverse=True)


def history_time(value):
    """Formate la date enregistrée sans supposer de fuseau, avec repli pour les formats anciens."""
    try:
        when = datetime.strptime(value, "%d/%m/%Y, %H:%M:%S")
    except (TypeError, ValueError):
        return {"fallback": str(value) if value else "—"}
    months = (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    return {
        "iso": when.isoformat(),
        "clock": when.strftime("%H:%M"),
        "seconds": when.strftime("%S"),
        "date": f"{when.day} {months[when.month - 1]} {when.year}",
    }


def history_entry(entry):
    """Prépare les joueurs dans l'ordre des camps, sans inventer les rôles absents."""
    scores = entry["scores"]
    descendante = entry.get("type") == "descendante"
    groups = []
    seen = set()

    def add_group(names, team, roles):
        players = []
        for name, role in zip(names, roles, strict=True):
            if not isinstance(name, str) or name not in scores or name in seen:
                continue
            players.append({"name": name, "score": scores[name], "role": role})
            seen.add(name)
        if players:
            groups.append({"team": team, "players": players})

    if not descendante:
        add_group(
            [entry.get("preneur"), entry.get("partenaire")],
            "attaque",
            ["Preneur", "Partenaire"],
        )
        defenseurs = entry.get("defenseurs")
        if isinstance(defenseurs, list):
            add_group(defenseurs, "defense", [""] * len(defenseurs))
    remaining = [name for name in scores if name not in seen]
    add_group(remaining, "joueurs" if descendante else "inconnu", [""] * len(remaining))
    return {"entry": entry, "groups": groups, "time": history_time(entry.get("time"))}


def graph_data(history, players):
    """Cumuls et dates dans l'ordre d'enregistrement, avec un point initial à zéro."""
    players = list(players)
    totals = dict.fromkeys(players, 0)
    series = {name: [0] for name in players}
    dates = [None]
    for game in history:
        for name in players:
            totals[name] += game["scores"].get(name, 0)
            series[name].append(totals[name])
        date = game.get("time")
        dates.append(date if isinstance(date, str) and date else None)
    return {
        "games": len(history),
        "dates": dates,
        "players": [{"name": name, "values": series[name]} for name in players],
    }


def chart_svg(history, players, limit=12):
    """Courbes cumulées avec repères de points et de parties."""
    from xml.sax.saxutils import escape

    players = list(players)[:limit]
    totals = dict.fromkeys(players, 0)
    lines = {name: [0] for name in players}
    for game in history:
        for name in players:
            totals[name] += game["scores"].get(name, 0)
            lines[name].append(totals[name])
    values = [v for series in lines.values() for v in series] or [0]
    low, high = min(values), max(values)
    if low == high:
        low, high = low - 1, high + 1
    span = high - low
    count = max(len(history), 1)
    elements = [
        '<svg viewBox="0 0 800 270" role="img" aria-label="Évolution des points cumulés par numéro de partie" xmlns="http://www.w3.org/2000/svg">'
    ]
    for tick in range(5):
        value = low + span * tick / 4
        y = 225 - 200 * tick / 4
        elements.append(
            f'<line x1="75" y1="{y:.1f}" x2="785" y2="{y:.1f}" stroke="currentColor" opacity="0.12"/>'
            f'<text x="66" y="{y + 4:.1f}" text-anchor="end" fill="currentColor" font-size="11">{value:.4g}</text>'
        )
    zero_y = 225 - 200 * (0 - low) / span
    elements.append(
        f'<line x1="75" y1="{zero_y:.1f}" x2="785" y2="{zero_y:.1f}" stroke="currentColor" opacity="0.45"/>'
    )
    for index in sorted({0, len(history) // 2, len(history)}):
        x = 75 + 710 * index / count
        elements.append(
            f'<text x="{x:.1f}" y="245" text-anchor="middle" fill="currentColor" font-size="11">{index}</text>'
        )
    elements.append(
        '<text x="785" y="263" text-anchor="end" fill="currentColor" font-size="11">Parties</text>'
    )
    for index, (name, series) in enumerate(lines.items()):
        color = f"hsl({(index * 137) % 360} 65% 45%)"
        coordinates = " ".join(
            f"{75 + 710 * i / count:.1f},{225 - 200 * (value - low) / span:.1f}"
            for i, value in enumerate(series)
        )
        elements.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coordinates}"><title>{escape(name)}</title></polyline>'
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

    @web.middleware
    async def secure(request, handler):
        request[SESSION_KEY] = None
        if not debug and request.path.startswith("/debug/"):
            raise web.HTTPNotFound()
        if request.path not in (
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
                if debug and request.method == "POST" and request.path == "/debug/command":
                    raise web.HTTPUnauthorized(text="Session debug expirée ou déconnectée")
                if request.path != "/":
                    raise web.HTTPFound("/")
            else:
                if not debug and not guild_id:
                    raise web.HTTPForbidden(text="Serveur Discord non configuré")
                if not debug and session["guild_checked"] <= time.monotonic():
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
        return page("login.html")

    async def start_discord_login(request):
        now = time.monotonic()
        for sid, session in list(sessions.items()):
            if session["expires"] <= now:
                sessions.pop(sid, None)
        if debug:
            sid = verify_cookie(request.cookies.get(COOKIE, ""))
            if sid in sessions:
                raise web.HTTPFound("/")
            sid = secrets.token_urlsafe(32)
            max_age = 43200
            sessions[sid] = {
                "access": "",
                "user": {
                    "id": "1",
                    "name": os.environ.get("TAROT_DEBUG_USER_NAME", "Debug User"),
                },
                "csrf": secrets.token_urlsafe(32),
                "expires": now + max_age,
                "preview": None,
                "commits": deque(),
            }
            response = web.HTTPFound("/")
            response.set_cookie(
                COOKIE,
                signed_cookie(sid),
                max_age=max_age,
                httponly=True,
                secure=True,
                samesite="Lax",
            )
            raise response
        nonce = secrets.token_urlsafe(32)
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
            return page("login.html") if debug else render("login.html")
        snapshot = await state()
        history = snapshot["history"]
        players = snapshot["players"]
        names = known_players(history, players)
        return page(
            "home.html",
            rows=statistics(history, players),
            recent=[history_entry(game) for game in reversed(history[-10:])],
            chart=chart_svg(history, names),
            user=request[SESSION_KEY]["user"],
            csrf=request[SESSION_KEY]["csrf"],
        )

    async def graphs_page(request):
        snapshot = await state()
        history = snapshot["history"]
        names = known_players(history, snapshot["players"])
        totals = compute_scores(history, snapshot["players"])
        return page(
            "graphs.html",
            chart=chart_svg(history, names, limit=None),
            chart_data=graph_data(history, names),
            legend=[{"name": name, "total": totals[name]} for name in names],
            games=len(history),
            user=request[SESSION_KEY]["user"],
            csrf=request[SESSION_KEY]["csrf"],
        )

    async def history_page(request):
        raw_page = request.query.get("page", "1")
        if not raw_page.isascii() or not raw_page.isdecimal() or len(raw_page) > 9:
            raise web.HTTPBadRequest(text="Numéro de page invalide")
        number = int(raw_page)
        if number < 1:
            raise web.HTTPBadRequest(text="Numéro de page invalide")
        snapshot = await state()
        history = snapshot["history"]
        total = len(history)
        pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
        if number > pages:
            raise web.HTTPNotFound(text="Page d’historique introuvable")
        end = total - (number - 1) * HISTORY_PAGE_SIZE
        start = max(0, end - HISTORY_PAGE_SIZE)
        return page(
            "history.html",
            recent=[history_entry(game) for game in reversed(history[start:end])],
            number=number,
            pages=pages,
            total=total,
            user=request[SESSION_KEY]["user"],
            csrf=request[SESSION_KEY]["csrf"],
        )

    async def logout(request):
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
            targets=CONTRAT_PAR_BOUT,
            user=request[SESSION_KEY]["user"],
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
        error = "Cet aperçu a expiré. Recalcule les scores." if request.query.get("expired") else ""
        return game_page(request, names, error=error)

    async def game2(request):
        return web.Response(status=302, headers={"Location": "/game"})

    def redirect_to_preview(request, names, *, error="", scores=None, commit_id=""):
        page_id = commit_id or str(uuid4())
        request[SESSION_KEY]["preview_page"] = {
            "id": page_id,
            "names": names,
            "form": request[FORM_KEY].copy(),
            "error": error,
            "scores": scores,
            "commit_id": commit_id,
        }
        return web.Response(status=303, headers={"Location": f"/game/preview/{page_id}#preview"})

    async def preview(request):
        request[SESSION_KEY]["preview"] = None
        request[SESSION_KEY].pop("preview_page", None)
        snapshot = await state()
        names = known_players(snapshot["history"], snapshot["players"])
        try:
            game_data = parse_form(request[FORM_KEY])
            _session, scores = validate_game(game_data, names)
        except InvalidGame as exc:
            return redirect_to_preview(request, names, error=str(exc))
        commit_id = str(uuid4())
        request[SESSION_KEY]["preview"] = (commit_id, game_data)
        return redirect_to_preview(request, names, scores=scores, commit_id=commit_id)

    async def game_preview(request):
        session = request[SESSION_KEY]
        saved = session.get("preview_page")
        if not saved or saved["id"] != request.match_info["page_id"]:
            return web.Response(status=302, headers={"Location": "/game?expired=1#preview"})
        previewed = session["preview"]
        if saved["scores"] is not None and (not previewed or saved["commit_id"] != previewed[0]):
            return web.Response(status=302, headers={"Location": "/game?expired=1#preview"})
        return game_page(
            request,
            saved["names"],
            saved["form"],
            error=saved["error"],
            scores=saved["scores"],
            commit_id=saved["commit_id"],
        )

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
        if session["preview"] is previewed:
            session["preview"] = None
        saved_page = session.get("preview_page")
        if saved_page and saved_page["id"] == previewed[0]:
            session.pop("preview_page", None)
        recent.append(now)
        return page(
            "saved.html",
            message_id=result["message_id"],
            table_sent=result.get("table_sent", True),
            user=request[SESSION_KEY]["user"],
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
    app.router.add_get("/history", history_page)
    app.router.add_get("/graphs", graphs_page)
    app.router.add_post("/logout", logout)
    app.router.add_get("/game", game)
    app.router.add_post("/preview", preview)
    app.router.add_get("/game2", game2)
    app.router.add_get("/game/preview/{page_id}", game_preview)
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
