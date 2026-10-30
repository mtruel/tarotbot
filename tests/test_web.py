"""Régression : saisie web, ACL Discord et chemins protégés."""

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from multidict import MultiDict

from tarot_commands.game import autoparse
from tarot_commands.internal_api import create_app as create_internal_app
from tarot_commands.sessions import find_history_by_message_id, temp_session
from tarot_commands.state import load_history
from tarot_commands.web_game import InvalidGame, validate_game
from tarot_web.app import (
    chart_svg,
    create_app,
    graph_data,
    history_entry,
    history_time,
    parse_form,
    render,
    statistics,
)

PLAYERS = ["Alice", "Bob", "Claire", "David", "Eve"]
GAME = {
    "points_attaque": 54,
    "bouts": 1,
    "enchere": 2,
    "preneur": "Alice",
    "partenaire": None,
    "defenseurs": ["Bob", "Claire", "David"],
    "miseres": [],
    "primes_attaque": [],
    "primes_defense": [],
}
CONFIG = {
    "DISCORD_OAUTH_CLIENT_ID": "123",
    "DISCORD_OAUTH_CLIENT_SECRET": "client-secret",
    "DISCORD_OAUTH_REDIRECT_URI": "https://example.org/oauth/callback",
    "WEB_SESSION_SECRET": "unit-test-secret-that-is-long-enough",
    "TAROT_INTERNAL_TOKEN": "internal-secret-that-is-long-enough",
    "DISCORD_GUILD_ID": "999",
}


class TestHome(unittest.TestCase):
    def test_chart_cumulative_values_and_axes(self):
        history = [{"scores": {"<Alice>": 1.5, "Bob": -1.5}}, {"scores": {"Bob": 1.5}}]
        svg = chart_svg(history, ["<Alice>", "Bob"])
        root = ElementTree.fromstring(svg)
        ns = {"svg": "http://www.w3.org/2000/svg"}
        lines = root.findall("svg:polyline", ns)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].find("svg:title", ns).text, "<Alice>")
        self.assertEqual(lines[0].get("points"), "75.0,125.0 430.0,25.0 785.0,25.0")
        self.assertEqual(lines[1].get("points"), "75.0,125.0 430.0,225.0 785.0,125.0")
        self.assertIn("Parties", svg)
        self.assertIn('opacity="0.45"', svg)
        self.assertNotIn("nan", chart_svg([], ["Alice"]).lower())

    def test_chart_player_limit_and_empty_series(self):
        players = [f"Joueur {index}" for index in range(15)]
        history = [{"scores": {players[0]: 1.5, players[-1]: -1.5}}]
        ns = {"svg": "http://www.w3.org/2000/svg"}

        def titles(svg):
            root = ElementTree.fromstring(svg)
            return [line.find("svg:title", ns).text for line in root.findall("svg:polyline", ns)]

        self.assertEqual(titles(chart_svg(history, iter(players))), players[:12])
        self.assertEqual(titles(chart_svg(history, players, limit=None)), players)
        self.assertEqual(titles(chart_svg(history, players, limit=0)), [])
        self.assertEqual(titles(chart_svg([], ["Alice", "Alice"])), ["Alice"])
        self.assertNotIn("nan", chart_svg([], []).lower())

    def test_graph_data_all_players_dates_and_fractional_scores(self):
        history = [
            {"time": "02/01/2026, 10:00:00", "scores": {"Alice": 1.5, "Bob": -1.5}},
            {"scores": {"Bob": 2}},
            {"time": "01/01/2026, 12:00:00", "scores": {"Alice": -0.5}},
        ]
        self.assertEqual(
            graph_data(history, ["Alice", "Bob", "Claire"]),
            {
                "games": 3,
                "dates": [None, "02/01/2026, 10:00:00", None, "01/01/2026, 12:00:00"],
                "players": [
                    {"name": "Alice", "values": [0, 1.5, 1.5, 1.0]},
                    {"name": "Bob", "values": [0, -1.5, 0.5, 0.5]},
                    {"name": "Claire", "values": [0, 0, 0, 0]},
                ],
            },
        )
        self.assertEqual(graph_data([], []), {"games": 0, "dates": [None], "players": []})

    def test_statistics_roles_and_unknown_history(self):
        history = [
            {
                "scores": {"Alice": 10, "Bob": 5, "Claire": -15},
                "preneur": "Alice",
                "partenaire": "Bob",
                "defenseurs": ["Claire"],
            },
            {
                "scores": {"Alice": -3, "Bob": 3},
                "preneur": "Bob",
                "partenaire": None,
                "defenseurs": ["Alice"],
            },
            {"scores": {"Alice": 1, "Bob": -1}, "type": "descendante"},
            {
                "scores": {"Alice": 0, "Bob": 0},
                "preneur": None,
                "partenaire": None,
                "defenseurs": None,
            },
        ]
        rows = {row["name"]: row for row in statistics(history, ["Alice", "Bob", "Claire", "Eve"])}
        self.assertEqual(
            (
                rows["Alice"]["games"],
                rows["Alice"]["takes"],
                rows["Alice"]["attacks"],
                rows["Alice"]["defenses"],
                rows["Alice"]["unknown_roles"],
            ),
            (4, 1, 1, 1, 1),
        )
        self.assertEqual(
            (
                rows["Bob"]["takes"],
                rows["Bob"]["attacks"],
                rows["Bob"]["defenses"],
                rows["Bob"]["unknown_roles"],
            ),
            (1, 2, 0, 1),
        )
        self.assertEqual(rows["Claire"]["defenses"], 1)
        self.assertEqual(rows["Eve"]["games"], 0)

    def test_ranking_displays_position_in_points_order(self):
        rows = statistics(
            [{"type": "descendante", "scores": {"Alice": 3, "Bob": 10, "Claire": -1}}], []
        )
        html = render(
            "home.html",
            debug=False,
            user={"name": "Test"},
            csrf="token",
            rows=rows,
            recent=[],
            chart="",
        ).text
        self.assertIn('data-sort="number" disabled>Rang</button>', html)
        for rank, name in enumerate(("Bob", "Alice", "Claire"), start=1):
            self.assertIn(
                f'<td class="home-rank" data-value="{rank}">{rank}</td>\n'
                f'            <th scope="row" data-value="{name}">{name}</th>',
                html,
            )

    def test_history_groups_and_details(self):
        entry = {
            "time": "01/01/2026, 12:00:00",
            "scores": {"Claire": -5, "Bob": 10, "Alice": 20, "David": -25},
            "preneur": "Alice",
            "partenaire": "Bob",
            "defenseurs": ["Claire", "David"],
            "enchere": "Garde",
            "points_attaque": 40,
            "bouts": 0,
            "primes_attaque": ["Chelem annoncé"],
            "primes_defense": ["Petit au bout"],
            "miseres": ["Bob"],
        }
        game = history_entry(entry)
        self.assertEqual(
            [(group["team"], [p["name"] for p in group["players"]]) for group in game["groups"]],
            [("attaque", ["Alice", "Bob"]), ("defense", ["Claire", "David"])],
        )
        html = render(
            "home.html",
            debug=False,
            user={"name": "Test"},
            csrf="token",
            rows=[],
            recent=[game],
            chart="",
        ).text
        for text in (
            "Preneur",
            "Partenaire",
            "Défense",
            "Garde",
            "40 points",
            "Bouts</strong> 0",
            "Chelem annoncé",
            "Petit au bout",
            "Misères</strong> Bob",
        ):
            self.assertIn(text, html)
        self.assertLess(
            html.index('class="home-history-time"'), html.index('class="home-game-details"')
        )
        self.assertLess(html.index('class="home-game-details"'), html.index('class="home-teams"'))
        self.assertLess(
            html.index('home-player-name">Alice'), html.index('home-player-name">Claire')
        )
        self.assertEqual(html.count('class="home-history-card"'), 1)

    def test_history_incomplete_roles_and_descendante(self):
        entry = {"scores": {"Alice": 1, "Bob": -1}, "preneur": "Alice", "defenseurs": None}
        game = history_entry(entry)
        self.assertEqual([g["team"] for g in game["groups"]], ["attaque", "inconnu"])
        game = history_entry({**entry, "type": "descendante", "miseres": ["Bob"]})
        self.assertEqual([g["team"] for g in game["groups"]], ["joueurs"])
        self.assertEqual([p["role"] for p in game["groups"][0]["players"]], ["", ""])
        game = history_entry({**entry, "defenseurs": ["Alice", "Bob", "Bob", "Inconnu"]})
        self.assertEqual(sum(len(g["players"]) for g in game["groups"]), 2)

    def test_history_day_separators(self):
        dates = [
            "02/01/2026, 14:30:00",
            "02/01/2026, 00:01:00",
            "01/01/2026, 23:59:59",
            "ancien format",
            "31/12/2025, 23:59:59",
            "30/12/2025, 23:59:59",
        ]
        recent = [history_entry({"time": date, "scores": {"Alice": 0}}) for date in dates]
        html = render(
            "home.html",
            debug=False,
            user={"name": "Test"},
            csrf="token",
            rows=[],
            recent=recent,
            chart="",
        ).text
        self.assertEqual(html.count('class="home-history-card"'), len(dates))
        self.assertEqual(html.count('class="home-day-separator"'), 2)
        same_day = html.index('datetime="2026-01-02T00:01:00"')
        previous_day = html.index('datetime="2026-01-01T23:59:59"')
        self.assertIn('class="home-day-separator"', html[same_day:previous_day])
        self.assertNotIn('class="home-day-separator"', html[:same_day])
        self.assertIn('00:01<span class="home-seconds">:00</span>', html)
        self.assertIn('23:59<span class="home-seconds">:59</span>', html)

    def test_home_history_and_empty_ranking(self):
        entry = {
            "time": "25/10/2026, 14:05:06",
            "type": "descendante",
            "scores": {"<Alice>": 1.5, "Bob": -1.5},
        }
        html = render(
            "home.html",
            debug=False,
            user={"name": "Test"},
            csrf="token",
            rows=[],
            recent=[history_entry(entry)],
            chart="",
        ).text
        self.assertLess(html.index('id="ranking-heading"'), html.index('id="recent-heading"'))
        self.assertLess(html.index('id="recent-heading"'), html.index('id="chart-heading"'))
        self.assertIn('datetime="2026-10-25T14:05:06"', html)
        self.assertIn('14:05<span class="home-seconds">:06</span>', html)
        self.assertIn('class="home-date">25 octobre 2026</span>', html)
        self.assertLess(
            html.index('class="home-date">25 octobre'), html.index('class="home-clock"')
        )
        self.assertIn('class="home-history-card"', html)
        self.assertNotIn('id="recent-hint"', html)
        self.assertIn("Descendante", html)
        self.assertIn("&lt;Alice&gt;", html)
        self.assertIn("+1.5", html)
        self.assertEqual(history_time("ancien format"), {"fallback": "ancien format"})
        self.assertEqual(history_time(None), {"fallback": "—"})
        fallback = history_entry({"time": "ancien format", "scores": {"Bob": 0}})
        html = render(
            "home.html",
            debug=False,
            user={"name": "Test"},
            csrf="token",
            rows=[],
            recent=[fallback],
            chart="",
        ).text
        self.assertIn('class="home-date">ancien format</span>', html)
        self.assertIn("Équipe inconnue", html)
        self.assertIn("Détails non renseignés", html)


class TestValidation(unittest.TestCase):
    def test_valid_and_scores_untrusted(self):
        session, scores = validate_game({**GAME, "scores": {"Alice": 9999}}, PLAYERS)
        self.assertEqual(scores["Alice"], 56 * 3)
        self.assertEqual(session.source, "web")

    def test_reject_invalid_games(self):
        for changes in (
            {"points_attaque": -1},
            {"points_attaque": 92},
            {"points_attaque": True},
            {"bouts": 4},
            {"enchere": 3},
            {"primes_attaque": ["triche"]},
            {"defenseurs": ["Bob", "Bob", "David"]},
            {"defenseurs": ["Nobody", "Claire", "David"]},
            {"defenseurs": ["Alice", "Claire", "David"]},
            {"miseres": ["Nobody"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(InvalidGame):
                validate_game({**GAME, **changes}, PLAYERS)

    def test_html_escaped(self):
        html = render(
            "game.html",
            players=["<img src=x>"],
            primes=[],
            targets=[56, 51, 41, 36],
            selected_players=[],
            selected_miseres=[],
            selected_primes_attaque=[],
            selected_primes_defense=[],
            scores=None,
        ).text
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertNotIn("<img src=x>", html)
        self.assertIn("&lt;", chart_svg([{"scores": {"<user>": 1}}], ["<user>"]))

    def test_form(self):
        form = MultiDict(
            [
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
                ("preneur", "Alice"),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("joueurs", "David"),
            ]
        )
        session, _ = validate_game(parse_form(form), PLAYERS)
        self.assertEqual(session.game_players["Défenseurs"], ["Bob", "Claire", "David"])
        with self.assertRaises(InvalidGame):
            parse_form(MultiDict([*form.items(), ("joueurs", "Alice")]))
        with self.assertRaises(InvalidGame):
            parse_form(MultiDict([*form.items(), ("miseres", "Eve")]))
        with self.assertRaises(InvalidGame):
            parse_form(MultiDict([*form.items(), ("partenaire", "Bob")]))
        wrong_taker = form.copy()
        wrong_taker["preneur"] = "Eve"
        with self.assertRaises(InvalidGame):
            parse_form(wrong_taker)
        five = MultiDict([*form.items(), ("joueurs", "Eve"), ("partenaire", "Bob")])
        self.assertEqual(parse_form(five)["defenseurs"], ["Claire", "David", "Eve"])


class FakeMessage:
    def __init__(self, message_id, content=""):
        self.id = message_id
        self.content = content

    async def delete(self):
        pass

    async def edit(self, *, content=None, **_kwargs):
        if content is not None:
            self.content = content


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.messages = []

    async def send(self, text, **kwargs):
        self.sent.append((text, kwargs))
        message = FakeMessage(100 + len(self.sent), text)
        self.messages.append(message)
        return message


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def is_closed(self):
        return False

    def is_ready(self):
        return True

    def get_channel(self, _id):
        return self.channel


class TestInternalAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import os

        self.oldcwd = os.getcwd()
        os.chdir(self.tmp.name)
        Path("history.json").write_text("[]")
        Path("players.json").write_text(json.dumps(PLAYERS))
        self.channel = FakeChannel()
        with patch("tarot_commands.internal_api.discord.TextChannel", FakeChannel):
            self.app = await create_internal_app(
                FakeBot(self.channel), token="internal-api-test-token-long-enough", channel_id="123"
            )
        # Patch the class for the duration of the requests, not only app construction.
        self.channel_patch = patch("tarot_commands.internal_api.discord.TextChannel", FakeChannel)
        self.channel_patch.start()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.channel_patch.stop()
        import os

        os.chdir(self.oldcwd)
        self.tmp.cleanup()

    async def test_auth_state_and_commit(self):
        self.assertEqual((await self.client.get("/state")).status, 401)
        self.assertEqual(
            (await self.client.get("/state", headers={"Authorization": "Bearer wrong"})).status, 401
        )
        headers = {"Authorization": "Bearer internal-api-test-token-long-enough"}
        state = await (await self.client.get("/state", headers=headers)).json()
        self.assertEqual(state["players"], PLAYERS)
        payload = {
            "commit_id": str(uuid4()),
            "web_author": {"id": "42", "name": "Test"},
            "game": {**GAME, "scores": {"Alice": 999999}},
        }
        first = await self.client.post("/commit", json=payload, headers=headers)
        self.assertEqual(first.status, 200, await first.text())
        self.assertEqual((await first.json())["message_id"], 101)
        second = await self.client.post("/commit", json=payload, headers=headers)
        self.assertTrue((await second.json())["duplicate"])
        self.assertEqual(len(self.channel.sent), 2)
        self.assertEqual(len(load_history()), 1)
        entry = find_history_by_message_id(load_history(), 102)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["message_id"], 101)
        self.assertEqual(entry["related_message_ids"], [102])
        self.assertNotEqual(entry["scores"]["Alice"], 999999)
        self.assertIn("id: `101`", self.channel.sent[1][0])
        self.assertTrue(all("allowed_mentions" in kwargs for _text, kwargs in self.channel.sent))

    async def test_commit_announcement_carries_game_id(self):
        """L'id affiché dans l'annonce d'une partie web doit retrouver la partie.

        `t/edit` et `t/delete` lisent un id dans l'annonce : ce doit être
        l'id canonique de la partie, pas l'id Discord de l'auteur web.
        """
        headers = {"Authorization": "Bearer internal-api-test-token-long-enough"}
        payload = {
            "commit_id": str(uuid4()),
            "web_author": {"id": "42", "name": "Test"},
            "game": dict(GAME),
        }
        response = await self.client.post("/commit", json=payload, headers=headers)
        self.assertEqual(response.status, 200, await response.text())

        announcement = self.channel.messages[0]
        self.assertIn("-# id: `101`", announcement.content)
        self.assertIn(
            "Saisie [web](https://tarot-imb.beta.public.truel.fr) par Test.", announcement.content
        )
        # L'id Discord de l'auteur web n'est pas un id de partie : il ne doit
        # plus s'afficher comme tel dans l'annonce.
        self.assertNotIn("(42)", announcement.content)
        phrase = re.search(r"`(t/auto [^`]+)`", announcement.content)
        self.assertIsNotNone(phrase)
        session = temp_session()
        autoparse(phrase.group(1)[len("t/auto ") :], session)
        self.assertEqual(session.game_players["Preneur"], ["Alice"])
        self.assertEqual(session.game_players["Défenseurs"], ["Bob", "Claire", "David"])
        self.assertEqual(session.points_attaque, 54)
        self.assertEqual(session.bouts, 1)
        self.assertEqual(session.enchere, 2)

        defense_game = {**GAME, "primes_defense": ["Petit au bout"]}
        response = await self.client.post(
            "/commit",
            json={
                "commit_id": str(uuid4()),
                "web_author": {"id": "42", "name": "Test"},
                "game": defense_game,
            },
            headers=headers,
        )
        self.assertEqual(response.status, 200, await response.text())
        phrase = re.search(r"`(t/auto [^`]+)`", self.channel.messages[-2].content)
        self.assertIsNotNone(phrase)
        session = temp_session()
        autoparse(phrase.group(1)[len("t/auto ") :], session)
        self.assertEqual(session.primes_defense, ["Petit au bout"])

        entry = find_history_by_message_id(load_history(), 101)
        self.assertIsNotNone(entry)

    async def test_bad_game(self):
        headers = {"Authorization": "Bearer internal-api-test-token-long-enough"}
        response = await self.client.post(
            "/commit",
            json={
                "commit_id": str(uuid4()),
                "web_author": {"id": "42", "name": "Test"},
                "game": {**GAME, "bouts": 9},
            },
            headers=headers,
        )
        self.assertEqual(response.status, 400)
        self.assertFalse(self.channel.sent)


class FakeResponse:
    def __init__(self, status, data):
        self.status = status
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return self.data


class FakeHTTP:
    def __init__(self, guild="999"):
        self.guild = guild
        self.commits = []
        self.history = []

    def get(self, url, **_kwargs):
        if url.endswith("/users/@me/guilds"):
            return FakeResponse(200, [{"id": self.guild}])
        if url.endswith("/users/@me"):
            return FakeResponse(200, {"id": "42", "username": "Tester"})
        return FakeResponse(200, {"history": self.history, "players": PLAYERS})

    def post(self, url, **kwargs):
        if url.endswith("/oauth2/token"):
            return FakeResponse(200, {"access_token": "token", "expires_in": 3600})
        self.commits.append(kwargs["json"])
        return FakeResponse(200, {"message_id": 101, "table_sent": True})


class TestWeb(unittest.IsolatedAsyncioTestCase):
    async def start_client(self, config=CONFIG, guild="999", login_debug=True):
        self.http = FakeHTTP(guild=guild)
        server = TestServer(await create_app(http=self.http, config=config))
        await server.start_server()
        self.client = TestClient(
            server, cookie_jar=CookieJar(unsafe=True, treat_as_secure_origin=server.make_url("/"))
        )
        await self.client.start_server()
        if config.get("TAROT_DEBUG") == "1" and login_debug:
            response = await self.client.get("/auth/discord", allow_redirects=False)
            self.assertEqual(response.status, 302)

    async def asyncTearDown(self):
        if hasattr(self, "client"):
            await self.client.close()

    async def test_login_state_csrf_and_private_page(self):
        await self.start_client()
        response = await self.client.get("/", allow_redirects=False)
        self.assertEqual(response.status, 200)
        self.assertIn("Se connecter avec Discord", await response.text())
        self.assertNotIn("oauth_state", response.cookies)
        login = await self.client.get("/login", allow_redirects=False)
        self.assertEqual(login.status, 200)
        self.assertIn('href="/auth/discord"', await login.text())
        self.assertEqual(await response.text(), await login.text())
        self.assertNotIn("oauth_state", login.cookies)
        private = await self.client.get("/game", allow_redirects=False)
        self.assertEqual(private.status, 302)
        self.assertEqual(private.headers["Location"], "/")

        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        self.assertEqual(oauth.status, 302)
        self.assertTrue(
            oauth.headers["Location"].startswith("https://discord.com/oauth2/authorize?")
        )
        self.assertIn("state=", oauth.headers["Location"])
        bad = await self.client.get("/oauth/callback?state=wrong&code=ok", allow_redirects=False)
        self.assertEqual(bad.status, 403)
        state = oauth.cookies["oauth_state"].value
        self.client.session.cookie_jar.update_cookies(
            {"oauth_state": state}, response_url=self.client.make_url("/")
        )
        accepted = await self.client.get(
            f"/oauth/callback?state={state}&code=ok",
            allow_redirects=False,
            cookies={"oauth_state": state},
        )
        self.assertEqual(accepted.status, 302)
        page = await self.client.get(
            "/",
            cookies={"tarot_session": accepted.cookies["tarot_session"].value},
            allow_redirects=False,
        )
        self.assertEqual(page.status, 200)
        self.assertIn("Alice", await page.text())
        denied = await self.client.post(
            "/preview",
            cookies={"tarot_session": accepted.cookies["tarot_session"].value},
            data={"points_attaque": "54"},
            allow_redirects=False,
        )
        self.assertEqual(denied.status, 403)

    async def test_oauth_session_expiry_cookie_and_guild_recheck(self):
        await self.start_client()
        original_post = self.http.post
        for token_lifetime, max_age in ((120, 120), (86400, 43200)):
            with self.subTest(token_lifetime=token_lifetime):

                def post(url, **kwargs):
                    if url.endswith("/oauth2/token"):
                        return FakeResponse(
                            200, {"access_token": "token", "expires_in": token_lifetime}
                        )
                    return original_post(url, **kwargs)

                with (
                    patch("tarot_web.app.time") as clock,
                    patch.object(self.http, "post", side_effect=post),
                ):
                    clock.monotonic.return_value = 100
                    oauth = await self.client.get("/auth/discord", allow_redirects=False)
                    nonce = oauth.cookies["oauth_state"].value
                    accepted = await self.client.get(
                        f"/oauth/callback?state={nonce}&code=ok",
                        cookies={"oauth_state": nonce},
                        allow_redirects=False,
                    )
                    cookie = accepted.cookies["tarot_session"]
                    self.assertEqual(int(cookie["max-age"]), max_age)
                    self.assertTrue(cookie["secure"])
                    self.assertTrue(cookie["httponly"])
                    self.assertEqual(cookie["samesite"], "Lax")
                    clock.monotonic.return_value = 100 + max_age - 1
                    self.assertEqual(
                        (await self.client.get("/game", allow_redirects=False)).status, 200
                    )
                    clock.monotonic.return_value = 100 + max_age
                    self.assertEqual(
                        (await self.client.get("/game", allow_redirects=False)).status, 302
                    )

        with patch("tarot_web.app.time") as clock:
            clock.monotonic.return_value = 100
            oauth = await self.client.get("/auth/discord", allow_redirects=False)
            nonce = oauth.cookies["oauth_state"].value
            await self.client.get(
                f"/oauth/callback?state={nonce}&code=ok",
                cookies={"oauth_state": nonce},
                allow_redirects=False,
            )
            self.http.guild = "other"
            clock.monotonic.return_value = 399
            self.assertEqual((await self.client.get("/game", allow_redirects=False)).status, 200)
            clock.monotonic.return_value = 400
            self.assertEqual((await self.client.get("/game", allow_redirects=False)).status, 403)
            self.assertEqual((await self.client.get("/game", allow_redirects=False)).status, 302)

    async def test_shared_header_and_logout_form(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        for path in ("/", "/history", "/graphs", "/game", "/debug/chat"):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                html = await response.text()
                self.assertIn("/static/header.css", html)
                self.assertIn('class="app-header-brand" href="/">TAROT IMB</a>', html)
                self.assertIn('href="/#ranking-heading"', html)
                self.assertIn('href="/history"', html)
                self.assertIn('href="/graphs"', html)
                if path == "/game":
                    self.assertNotIn('class="app-header-action"', html)
                else:
                    self.assertIn('class="app-header-action" href="/game"', html)
                self.assertIn("<summary>Compte</summary>", html)
                self.assertIn('class="app-header-user">Debug User', html)
                self.assertRegex(
                    html,
                    r'<form method="post" action="/logout">\s*<input type="hidden" name="csrf" value="[^"\s]+">',
                )
                if path == "/game":
                    self.assertLess(html.index('action="/logout"'), html.index('id="game-form"'))
                    self.assertNotIn('action="/logout"', html[html.index('id="game-form"') :])
        login = await (await self.client.get("/login")).text()
        self.assertIn("TAROT IMB", login)
        self.assertNotIn('class="app-header"', login)
        saved = render(
            "saved.html", message_id=101, table_sent=True, csrf="token", user={"name": "<Alice>"}
        ).text
        self.assertIn("&lt;Alice&gt;", saved)
        self.assertIn('action="/logout"', saved)
        stylesheet = await self.client.get("/static/header.css")
        self.assertEqual(stylesheet.status, 200)

    async def test_graphs_page(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        empty = await (await self.client.get("/graphs")).text()
        self.assertIn("Aucune courbe à afficher", empty)
        self.http.history = [{"scores": {f"Joueur {i}": i for i in range(14)}}]
        response = await self.client.get("/graphs")
        self.assertEqual(response.status, 200)
        html = await response.text()
        self.assertIn('id="graphs-heading"', html)
        self.assertIn('src="/static/echarts.min.js"', html)
        self.assertIn('src="/static/graphs.js"', html)
        self.assertIn('id="scores-chart-fallback"', html)
        match = re.search(
            r'<script type="application/json" id="scores-chart-data">(.*?)</script>', html
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(data["games"], 1)
        self.assertEqual(data["dates"], [None, None])
        self.assertEqual(len(data["players"]), 19)
        self.assertEqual(data["players"][-1], {"name": "Joueur 13", "values": [0, 13]})
        self.assertIn("Joueur 13", html)
        self.assertIn('stroke="hsl(0 65% 45%)"', html)

    async def test_graphs_json_escapes_html(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        name = '</script><script>alert("x")</script>'
        self.http.history = [{"time": name, "scores": {name: 1.5}}]
        html = await (await self.client.get("/graphs")).text()
        self.assertNotIn(name, html)
        match = re.search(
            r'<script type="application/json" id="scores-chart-data">(.*?)</script>', html
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(data["players"][-1], {"name": name, "values": [0, 1.5]})
        self.assertEqual(data["dates"], [None, name])

    async def test_history_pagination(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        self.http.history = [{"scores": {f"Joueur {i}": i}} for i in range(45)]
        home = await (await self.client.get("/")).text()
        self.assertIn('href="/history"', home)
        first = await self.client.get("/history")
        self.assertEqual(first.status, 200)
        html = await first.text()
        names = re.findall(r'class="home-player-name">([^<]+)</span>', html)
        self.assertEqual(names, [f"Joueur {i}" for i in range(44, 24, -1)])
        self.assertIn("45 parties", html)
        self.assertIn('src="/static/history.js"', html)
        self.assertIn('class="home-history-status" role="status"', html)
        self.assertIn('href="/history?page=2" rel="next"', html)
        self.assertNotIn('rel="prev"', html)
        second = await (await self.client.get("/history?page=2")).text()
        names = re.findall(r'class="home-player-name">([^<]+)</span>', second)
        self.assertEqual(names, [f"Joueur {i}" for i in range(24, 4, -1)])
        self.assertIn('href="/history?page=1" rel="prev"', second)
        last = await (await self.client.get("/history?page=3")).text()
        names = re.findall(r'class="home-player-name">([^<]+)</span>', last)
        self.assertEqual(names, [f"Joueur {i}" for i in range(4, -1, -1)])
        self.assertNotIn('rel="next"', last)
        for query in ("page=0", "page=-1", "page=abc", "page=9999999999", "page="):
            with self.subTest(query=query):
                self.assertEqual((await self.client.get(f"/history?{query}")).status, 400)
        self.assertEqual((await self.client.get("/history?page=4")).status, 404)
        self.http.history = []
        empty = await (await self.client.get("/history")).text()
        self.assertIn("Aucune partie pour le moment", empty)
        self.assertNotIn('class="home-pagination"', empty)

    async def test_history_requires_session(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"}, login_debug=False)
        for path in ("/history", "/graphs"):
            response = await self.client.get(path, allow_redirects=False)
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers["Location"], "/")

    async def test_logout_invalidates_authenticated_session(self):
        await self.start_client()
        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        nonce = oauth.cookies["oauth_state"].value
        login = await self.client.get(
            f"/oauth/callback?state={nonce}&code=ok",
            cookies={"oauth_state": nonce},
            allow_redirects=False,
        )
        cookie = {"tarot_session": login.cookies["tarot_session"].value}
        page = await self.client.get("/", cookies=cookie)
        html = await page.text()
        self.assertIn('action="/logout"', html)
        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        invalid = await self.client.post(
            "/logout", data={"csrf": "incorrect"}, cookies=cookie, allow_redirects=False
        )
        self.assertEqual(invalid.status, 403)
        self.assertEqual((await self.client.get("/game", cookies=cookie)).status, 200)
        logout = await self.client.post(
            "/logout", data={"csrf": csrf}, cookies=cookie, allow_redirects=False
        )
        self.assertEqual(logout.status, 302)
        self.assertEqual(logout.headers["Location"], "/login")
        self.assertEqual(logout.cookies["tarot_session"].value, "")
        private = await self.client.get("/game", cookies=cookie, allow_redirects=False)
        self.assertEqual(private.status, 302)
        self.assertEqual(private.headers["Location"], "/")
        homepage = await self.client.get("/", cookies=cookie)
        self.assertIn("Se connecter avec Discord", await homepage.text())

    async def test_debug_login_logout_and_reconnect(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"}, login_debug=False)
        login_pages = []
        for path in ("/", "/login"):
            page = await self.client.get(path, allow_redirects=False)
            self.assertEqual(page.status, 200)
            html = await page.text()
            self.assertIn('href="/auth/discord"', html)
            self.assertIn("Se connecter au mode debug", html)
            self.assertIn('name="robots" content="noindex"', html)
            login_pages.append(html)
        self.assertEqual(*login_pages)
        for path in ("/game", "/debug/chat"):
            response = await self.client.get(path, allow_redirects=False)
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers["Location"], "/")
        with (
            patch.object(self.http, "get", wraps=self.http.get) as get,
            patch.object(self.http, "post", wraps=self.http.post) as post,
        ):
            login = await self.client.get("/auth/discord", allow_redirects=False)
            get.assert_not_called()
            post.assert_not_called()
        self.assertEqual(login.headers["Location"], "/")
        cookie = login.cookies["tarot_session"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        old_cookie = cookie.value
        tampered = await self.client.get(
            "/game", cookies={"tarot_session": old_cookie + "tampered"}, allow_redirects=False
        )
        self.assertEqual(tampered.status, 302)
        self.assertEqual(tampered.headers["Location"], "/")
        page = await self.client.get("/")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        invalid = await self.client.post(
            "/logout", data={"csrf": "incorrect"}, allow_redirects=False
        )
        self.assertEqual(invalid.status, 403)
        self.assertEqual((await self.client.get("/game")).status, 200)
        response = await self.client.post("/logout", data={"csrf": csrf}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/login")
        self.assertEqual(response.cookies["tarot_session"].value, "")
        for cookie_value in (old_cookie, old_cookie + "tampered"):
            private = await self.client.get(
                "/game", cookies={"tarot_session": cookie_value}, allow_redirects=False
            )
            self.assertEqual(private.status, 302)
            self.assertEqual(private.headers["Location"], "/")
        homepage = await self.client.get("/")
        self.assertIn('href="/auth/discord"', await homepage.text())
        login = await self.client.get("/auth/discord", allow_redirects=False)
        self.assertNotEqual(login.cookies["tarot_session"].value, old_cookie)
        page = await self.client.get("/")
        new_csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        self.assertNotEqual(csrf, new_csrf)
        self.assertEqual((await self.client.post("/logout", data={"csrf": csrf})).status, 403)

    async def test_debug_session_expiry_and_cleanup(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"}, login_debug=False)
        with patch("tarot_web.app.time") as clock:
            clock.monotonic.return_value = 100
            first = await self.client.get("/auth/discord", allow_redirects=False)
            old_cookie = first.cookies["tarot_session"].value
            clock.monotonic.return_value = 43300
            second = await self.client.get("/auth/discord", allow_redirects=False)
            new_cookie = second.cookies["tarot_session"].value
            self.assertNotEqual(new_cookie, old_cookie)
            clock.monotonic.return_value = 100
            page = await self.client.get(
                "/game", cookies={"tarot_session": old_cookie}, allow_redirects=False
            )
            self.assertEqual(page.status, 302)
            self.assertEqual(page.headers["Location"], "/")
            clock.monotonic.return_value = 86500
            page = await self.client.get(
                "/game", cookies={"tarot_session": new_cookie}, allow_redirects=False
            )
            self.assertEqual(page.status, 302)
            self.assertEqual(page.headers["Location"], "/")
            clock.monotonic.return_value = 43300
            page = await self.client.get(
                "/game", cookies={"tarot_session": new_cookie}, allow_redirects=False
            )
            self.assertEqual(page.status, 302)
            self.assertEqual(page.headers["Location"], "/")

    async def test_mobile_form_preview_and_changed_confirmation(self):
        await self.start_client()
        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        nonce = oauth.cookies["oauth_state"].value
        accepted = await self.client.get(
            f"/oauth/callback?state={nonce}&code=ok",
            cookies={"oauth_state": nonce},
            allow_redirects=False,
        )
        cookie = {"tarot_session": accepted.cookies["tarot_session"].value}
        page = await self.client.get("/game", cookies=cookie)
        html = await page.text()
        self.assertIn('name="joueurs"', html)
        self.assertNotIn('name="defenseurs"', html)
        self.assertIn('name="viewport"', html)

        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("joueurs", "David"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        response = await self.client.post(
            "/preview", data=form, cookies=cookie, allow_redirects=False
        )
        self.assertEqual(response.status, 303)
        preview = await self.client.get(response.headers["Location"], cookies=cookie)
        self.assertEqual(preview.status, 200)
        text = await preview.text()
        self.assertIn("Bob", text)
        commit_id = re.search(r'name="commit_id" value="([^"]+)"', text).group(1)
        changed = MultiDict([*form.items(), ("commit_id", commit_id)])
        changed["points_attaque"] = "55"
        rejected = await self.client.post("/commit", data=changed, cookies=cookie)
        self.assertEqual(rejected.status, 409)
        self.assertFalse(self.http.commits)
        unchanged = MultiDict([*form.items(), ("commit_id", commit_id)])
        saved = await self.client.post("/commit", data=unchanged, cookies=cookie)
        self.assertEqual(saved.status, 200)
        self.assertEqual(len(self.http.commits), 1)
        self.assertEqual(self.http.commits[0]["game"]["defenseurs"], ["Bob", "Claire", "David"])

    async def test_unified_pages_keep_navigation_and_controls(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        for path, stylesheet, expected in (
            ("/", "home-theme.css", ('href="/game"', 'action="/logout"')),
            ("/debug/chat", "aux-theme.css", ('id="console-log"', 'id="console-form"')),
        ):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                html = await response.text()
                self.assertIn("/static/unified.css", html)
                self.assertIn(f"/static/{stylesheet}", html)
                for text in expected:
                    self.assertIn(text, html)
        for stylesheet in (
            "unified.css",
            "home-theme.css",
            "aux-theme.css",
        ):
            response = await self.client.get(f"/static/{stylesheet}")
            self.assertEqual(response.status, 200)
        saved = render("saved.html", message_id=101, table_sent=False).text
        self.assertIn("Identifiant Discord : 101", saved)
        self.assertIn("Le tableau n'a pas pu être publié", saved)
        self.assertIn('href="/"', saved)
        login = render("login.html").text
        self.assertIn('href="/auth/discord"', login)
        self.assertIn("/static/unified.css", login)

    async def test_favicon_is_available_on_all_pages(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        icon_link = 'rel="icon" type="image/svg+xml" href="/static/favicon.svg"'
        for path in ("/", "/history", "/graphs", "/game", "/game2", "/debug/chat"):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                self.assertIn(icon_link, await response.text())
        for template in ("login.html", "saved.html"):
            with self.subTest(template=template):
                self.assertIn(icon_link, render(template, message_id=101, table_sent=True).text)
        icon = await self.client.get("/static/favicon.svg")
        self.assertEqual(icon.status, 200)
        self.assertEqual(icon.content_type, "image/svg+xml")
        self.assertIn("Le Petit, atout 1", await icon.text())

    async def test_game2_bookmark_redirects_to_game_without_a_second_workflow(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        response = await self.client.get("/game2", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/game")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        self.assertEqual(
            (
                await self.client.post("/preview2", data={"csrf": csrf}, allow_redirects=False)
            ).status,
            404,
        )
        self.assertEqual(
            (await self.client.get("/game2/preview/old", allow_redirects=False)).status, 404
        )

    async def test_removed_game_variants_are_unavailable(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        for variant in range(3, 8):
            with self.subTest(variant=variant):
                response = await self.client.get(f"/game{variant}")
                self.assertEqual(response.status, 404)

    async def test_game_preview_redirect_is_refreshable_without_resubmission(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        with patch("tarot_web.app.parse_form", wraps=parse_form) as parse:
            response = await self.client.post("/preview", data=form, allow_redirects=False)
            self.assertEqual(response.status, 303)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            location = response.headers["Location"]
            self.assertTrue(location.startswith("/game/preview/"))
            self.assertTrue(location.endswith("#preview"))
            first = await self.client.get(location)
            second = await self.client.get(location)
            self.assertEqual(parse.call_count, 1)
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        first_html = await first.text()
        self.assertEqual(first_html, await second.text())
        self.assertNotIn('class="app-header-action"', first_html)
        commit_id = re.search(r'name="commit_id" value="([^"]+)"', first_html).group(1)
        self.assertFalse(self.http.commits)
        confirmation = MultiDict([*form.items(), ("commit_id", commit_id)])
        self.assertEqual((await self.client.post("/commit", data=confirmation)).status, 200)
        self.assertEqual(len(self.http.commits), 1)
        expired = await self.client.get(location, allow_redirects=False)
        self.assertEqual(expired.status, 302)
        self.assertEqual(expired.headers["Location"], "/game?expired=1#preview")
        self.assertEqual((await self.client.post("/commit", data=confirmation)).status, 403)

    async def test_game_invalid_preview_redirect_and_expired_tabs(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "99"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        invalid = await self.client.post("/preview", data=form, allow_redirects=False)
        self.assertEqual(invalid.status, 303)
        invalid_location = invalid.headers["Location"]
        first = await self.client.get(invalid_location)
        second = await self.client.get(invalid_location)
        first_html = await first.text()
        self.assertEqual(first_html, await second.text())
        self.assertIn('id="form-error"', first_html)
        self.assertIn('value="99"', first_html)
        self.assertNotIn('name="commit_id"', first_html)
        self.assertFalse(self.http.commits)

        form["points_attaque"] = "54"
        valid = await self.client.post("/preview", data=form, allow_redirects=False)
        self.assertEqual(valid.status, 303)
        valid_location = valid.headers["Location"]
        expired = await self.client.get(invalid_location, allow_redirects=False)
        self.assertEqual(expired.status, 302)
        expired_page = await self.client.get(expired.headers["Location"])
        self.assertIn("Cet aperçu a expiré", await expired_page.text())
        self.assertEqual((await self.client.get(valid_location)).status, 200)

        self.assertEqual(
            (await self.client.post("/preview", data=form, allow_redirects=False)).status, 303
        )
        expired = await self.client.get(valid_location, allow_redirects=False)
        self.assertEqual(expired.status, 302)
        self.assertEqual(expired.headers["Location"], "/game?expired=1#preview")
        malformed = await self.client.get("/game/preview/%C3%A9", allow_redirects=False)
        self.assertEqual(malformed.status, 302)
        self.assertEqual(malformed.headers["Location"], "/game?expired=1#preview")

    async def test_preview_is_private_to_its_authenticated_session(self):
        await self.start_client()
        cookies = []
        for _ in range(2):
            oauth = await self.client.get("/auth/discord", allow_redirects=False)
            nonce = oauth.cookies["oauth_state"].value
            accepted = await self.client.get(
                f"/oauth/callback?state={nonce}&code=ok",
                cookies={"oauth_state": nonce},
                allow_redirects=False,
            )
            self.assertEqual(accepted.status, 302)
            cookies.append({"tarot_session": accepted.cookies["tarot_session"].value})

        page = await self.client.get("/game", cookies=cookies[0])
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        response = await self.client.post(
            "/preview", data=form, cookies=cookies[0], allow_redirects=False
        )
        self.assertEqual(response.status, 303)
        location = response.headers["Location"]
        other = await self.client.get(location, cookies=cookies[1], allow_redirects=False)
        self.assertEqual(other.status, 302)
        self.assertEqual(other.headers["Location"], "/game?expired=1#preview")
        preview = await self.client.get(location, cookies=cookies[0])
        self.assertEqual(preview.status, 200)
        commit_id = re.search(r'name="commit_id" value="([^"]+)"', await preview.text()).group(1)
        other_page = await self.client.get("/game", cookies=cookies[1])
        other_csrf = re.search(r'name="csrf" value="([^"]+)"', await other_page.text()).group(1)
        confirmation = MultiDict([*form.items(), ("commit_id", commit_id)])
        confirmation["csrf"] = other_csrf
        self.assertEqual(
            (await self.client.post("/commit", data=confirmation, cookies=cookies[1])).status, 403
        )
        confirmation["csrf"] = csrf
        self.assertEqual(
            (await self.client.post("/commit", data=confirmation, cookies=cookies[0])).status, 200
        )
        self.assertEqual(len(self.http.commits), 1)

    async def test_confirmation_rate_limit_is_preserved(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        for index in range(4):
            with self.subTest(index=index):
                response = await self.client.post("/preview", data=form, allow_redirects=False)
                self.assertEqual(response.status, 303)
                preview = await self.client.get(response.headers["Location"])
                commit_id = re.search(
                    r'name="commit_id" value="([^"]+)"', await preview.text()
                ).group(1)
                confirmation = MultiDict([*form.items(), ("commit_id", commit_id)])
                saved = await self.client.post("/commit", data=confirmation)
                self.assertEqual(saved.status, 200 if index < 3 else 429)
        self.assertEqual(len(self.http.commits), 3)

    async def test_game_preview_survives_failed_commit_for_retry(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        response = await self.client.post("/preview", data=form, allow_redirects=False)
        location = response.headers["Location"]
        preview = await self.client.get(location)
        html = await preview.text()
        commit_id = re.search(r'name="commit_id" value="([^"]+)"', html).group(1)
        confirmation = MultiDict([*form.items(), ("commit_id", commit_id)])
        with patch.object(self.http, "post", return_value=FakeResponse(503, {})):
            self.assertEqual((await self.client.post("/commit", data=confirmation)).status, 503)
        retried_preview = await self.client.get(location)
        self.assertEqual(await retried_preview.text(), html)
        self.assertEqual((await self.client.post("/commit", data=confirmation)).status, 200)
        self.assertEqual(len(self.http.commits), 1)

    async def test_game_new_preview_survives_an_inflight_commit(self):
        await self.start_client(config={**CONFIG, "TAROT_DEBUG": "1"})
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = MultiDict(
            [
                ("csrf", csrf),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
        )
        initial = await self.client.post("/preview", data=form, allow_redirects=False)
        initial_page = await self.client.get(initial.headers["Location"])
        initial_id = re.search(
            r'name="commit_id" value="([^"]+)"', await initial_page.text()
        ).group(1)
        confirmation = MultiDict([*form.items(), ("commit_id", initial_id)])
        started = asyncio.Event()
        resume = asyncio.Event()

        class SlowResponse(FakeResponse):
            async def __aenter__(self):
                started.set()
                await resume.wait()
                return self

        with patch.object(self.http, "post", return_value=SlowResponse(200, {"message_id": 101})):
            pending = asyncio.create_task(self.client.post("/commit", data=confirmation))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                form["points_attaque"] = "55"
                new_preview = await self.client.post("/preview", data=form, allow_redirects=False)
                new_location = new_preview.headers["Location"]
            finally:
                resume.set()
            self.assertEqual((await pending).status, 200)

        refreshed = await self.client.get(new_location, allow_redirects=False)
        self.assertEqual(refreshed.status, 200)
        new_id = re.search(r'name="commit_id" value="([^"]+)"', await refreshed.text()).group(1)
        self.assertNotEqual(new_id, initial_id)
        new_confirmation = MultiDict([*form.items(), ("commit_id", new_id)])
        self.assertEqual((await self.client.post("/commit", data=new_confirmation)).status, 200)

    async def test_game_preview_and_commit_contract(self):
        await self.start_client()
        for path in ("/game", "/game2", "/game/preview/missing"):
            response = await self.client.get(path, allow_redirects=False)
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers["Location"], "/")
        self.assertEqual((await self.client.post("/preview", allow_redirects=False)).status, 302)
        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        nonce = oauth.cookies["oauth_state"].value
        accepted = await self.client.get(
            f"/oauth/callback?state={nonce}&code=ok",
            cookies={"oauth_state": nonce},
            allow_redirects=False,
        )
        cookie = {"tarot_session": accepted.cookies["tarot_session"].value}
        rendered = []

        def capture_render(name, **context):
            if name == "game.html":
                rendered.append((name, context))
            return render(name, **context)

        with patch("tarot_web.app.render", side_effect=capture_render):
            game = await self.client.get("/game", cookies=cookie)
            self.assertEqual(game.status, 200)
            self.assertEqual(game.headers["Cache-Control"], "no-store")
            self.assertEqual(game.headers["X-Frame-Options"], "DENY")
            self.assertIn("form-action 'self'", game.headers["Content-Security-Policy"])
            html = await game.text()
            self.assertIn("<body>\n", html)
            self.assertIn('id="game-form"', html)
            self.assertRegex(html, r'action="/preview(?:#preview)?"')
            self.assertIn('id="players-picker"', html)
            self.assertIn('class="section-icon players-suit" aria-hidden="true">♠</span>', html)
            self.assertIn('id="players-summary"', html)
            self.assertIn("3 À 5 JOUEURS", html)
            self.assertIn('id="players-done"', html)
            self.assertIn('id="taker-picker"', html)
            self.assertIn('id="taker-summary"', html)
            self.assertIn('id="taker-choices"', html)
            self.assertIn('id="partner-field"', html)
            self.assertIn('id="partner-summary"', html)
            self.assertIn('id="partner-choices"', html)
            self.assertIn('id="points-minus"', html)
            self.assertIn('id="points-minus-five"', html)
            self.assertIn('id="points-plus-five"', html)
            self.assertIn('id="points-plus"', html)
            self.assertIn('id="target-help"', html)
            self.assertIn(
                'id="extras-summary" class="extras-summary" aria-live="polite" hidden', html
            )
            self.assertIn('class="team-label">Attaque</h3>', html)
            self.assertIn('class="team-label">Défense</h3>', html)
            self.assertIn('name="preneur"', html)
            self.assertIn('name="partenaire"', html)
            self.assertIn('id="calculate-action">', html)
            self.assertNotIn('class="intro-text"', html)
            self.assertEqual(rendered[0][0], "game.html")
            csrf = rendered[0][1]["csrf"]
            form = MultiDict(
                [
                    ("csrf", csrf),
                    ("joueurs", "Alice"),
                    ("joueurs", "Bob"),
                    ("joueurs", "Claire"),
                    ("joueurs", "David"),
                    ("preneur", "Alice"),
                    ("points_attaque", "54"),
                    ("bouts", "1"),
                    ("enchere", "2"),
                ]
            )
            denied = form.copy()
            denied["csrf"] = "wrong"
            self.assertEqual(
                (await self.client.post("/preview", data=denied, cookies=cookie)).status, 403
            )
            response = await self.client.post(
                "/preview", data=form, cookies=cookie, allow_redirects=False
            )
            self.assertEqual(response.status, 303)
            preview = await self.client.get(response.headers["Location"], cookies=cookie)
            self.assertEqual(preview.status, 200)
            preview_html = await preview.text()
            self.assertIn("4 JOUEURS", preview_html)
            self.assertIn("Seuil à atteindre : 51 points.", preview_html)
            self.assertIn('id="calculate-action" hidden', preview_html)
            self.assertIn('class="primary-button confirm-button"', preview_html)
            self.assertIn("<noscript>", preview_html)
            self.assertIn("Recalculer les scores", preview_html)
            self.assertIn('<div class="recap-facts">', preview_html)
            name, context = rendered[-1]
            self.assertEqual(name, "game.html")
            self.assertEqual(context["selected_players"], ["Alice", "Bob", "Claire", "David"])
            self.assertEqual(context["game_data"], parse_form(form))
            self.assertEqual(context["scores"]["Alice"], 168)
            self.assertEqual(context["error"], "")
            commit_id = context["commit_id"]
            self.assertTrue(commit_id)
            confirmation = MultiDict([*form.items(), ("commit_id", commit_id)])
            bad_csrf = confirmation.copy()
            bad_csrf["csrf"] = "wrong"
            self.assertEqual(
                (await self.client.post("/commit", data=bad_csrf, cookies=cookie)).status, 403
            )
            changed = confirmation.copy()
            changed["points_attaque"] = "55"
            self.assertEqual(
                (await self.client.post("/commit", data=changed, cookies=cookie)).status, 409
            )
            self.assertFalse(self.http.commits)
            self.assertEqual(
                (await self.client.post("/commit", data=confirmation, cookies=cookie)).status, 200
            )
            self.assertEqual(len(self.http.commits), 1)
            self.assertEqual(self.http.commits[0]["game"], parse_form(form))
            self.assertEqual(
                (await self.client.post("/commit", data=confirmation, cookies=cookie)).status, 403
            )

    async def test_validation_invalidates_shared_preview(self):
        await self.start_client()
        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        nonce = oauth.cookies["oauth_state"].value
        accepted = await self.client.get(
            f"/oauth/callback?state={nonce}&code=ok",
            cookies={"oauth_state": nonce},
            allow_redirects=False,
        )
        cookie = {"tarot_session": accepted.cookies["tarot_session"].value}
        rendered = []

        def capture_render(name, **context):
            if name == "game.html":
                rendered.append((name, context))
            return render(name, **context)

        with patch("tarot_web.app.render", side_effect=capture_render):
            await self.client.get("/game", cookies=cookie)
            form = MultiDict(
                [
                    ("csrf", rendered[-1][1]["csrf"]),
                    ("joueurs", "Alice"),
                    ("joueurs", "Bob"),
                    ("joueurs", "Claire"),
                    ("joueurs", "David"),
                    ("preneur", "Alice"),
                    ("points_attaque", "54"),
                    ("bouts", "1"),
                    ("enchere", "2"),
                ]
            )
            response = await self.client.post(
                "/preview", data=form, cookies=cookie, allow_redirects=False
            )
            self.assertEqual(response.status, 303)
            await self.client.get(response.headers["Location"], cookies=cookie)
            commit_id = rendered[-1][1]["commit_id"]
            confirmation = MultiDict([*form.items(), ("commit_id", commit_id)])
            for invalid in (
                MultiDict([*form.items(), ("joueurs", "Alice")]),
                MultiDict([*form.items(), ("miseres", "Eve")]),
                MultiDict([*form.items(), ("joueurs", "Nobody")]),
            ):
                response = await self.client.post(
                    "/preview", data=invalid, cookies=cookie, allow_redirects=False
                )
                self.assertEqual(response.status, 303)
                self.assertEqual(
                    (await self.client.get(response.headers["Location"], cookies=cookie)).status,
                    200,
                )
                name, context = rendered[-1]
                self.assertEqual(name, "game.html")
                self.assertTrue(context["error"])
                self.assertIsNone(context["scores"])
                self.assertIsNone(context["game_data"])
                self.assertEqual(context["selected_players"], invalid.getall("joueurs"))
            self.assertEqual(
                (await self.client.post("/commit", data=confirmation, cookies=cookie)).status, 403
            )
            self.assertFalse(self.http.commits)

            five = MultiDict(
                [
                    *form.items(),
                    ("joueurs", "Eve"),
                    ("partenaire", "Bob"),
                    ("miseres", "Claire"),
                    ("primes_attaque", "Simple Poignée"),
                    ("primes_defense", "Petit au bout"),
                ]
            )
            response = await self.client.post(
                "/preview", data=five, cookies=cookie, allow_redirects=False
            )
            self.assertEqual(response.status, 303)
            await self.client.get(response.headers["Location"], cookies=cookie)
            previous = rendered[-1][1]
            response = await self.client.post(
                "/preview", data=five, cookies=cookie, allow_redirects=False
            )
            self.assertEqual(response.status, 303)
            five_preview = await self.client.get(response.headers["Location"], cookies=cookie)
            self.assertEqual(five_preview.status, 200)
            five_html = await five_preview.text()
            self.assertIn("<dt>Primes attaque</dt><dd>Simple Poignée</dd>", five_html)
            self.assertIn("<dt>Primes défense</dt><dd>Petit au bout</dd>", five_html)
            self.assertIn("<dt>Misères</dt><dd>Claire</dd>", five_html)
            self.assertIn(
                "Attaque : Simple Poignée · Défense : Petit au bout · Misères : Claire", five_html
            )
            current = rendered[-1][1]
            self.assertEqual(
                {k: v for k, v in previous.items() if k != "commit_id"},
                {k: v for k, v in current.items() if k != "commit_id"},
            )
            self.assertEqual(current["selected_miseres"], ["Claire"])
            self.assertEqual(current["selected_primes_attaque"], ["Simple Poignée"])
            self.assertEqual(current["selected_primes_defense"], ["Petit au bout"])
            self.assertEqual(current["game_data"]["partenaire"], "Bob")
            self.assertEqual(current["game_data"]["defenseurs"], ["Claire", "David", "Eve"])
            old_confirmation = MultiDict([*five.items(), ("commit_id", previous["commit_id"])])
            self.assertEqual(
                (await self.client.post("/commit", data=old_confirmation, cookies=cookie)).status,
                403,
            )
            new_confirmation = MultiDict([*five.items(), ("commit_id", current["commit_id"])])
            self.assertEqual(
                (await self.client.post("/commit", data=new_confirmation, cookies=cookie)).status,
                200,
            )
            self.assertEqual(self.http.commits[0]["game"], parse_form(five))

    async def test_outside_guild(self):
        await self.start_client(guild="another-server")
        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        nonce = oauth.cookies["oauth_state"].value
        response = await self.client.get(
            f"/oauth/callback?state={nonce}&code=ok",
            cookies={"oauth_state": nonce},
            allow_redirects=False,
        )
        self.assertEqual(response.status, 403)
        self.assertEqual((await self.client.get("/", allow_redirects=False)).status, 200)

    async def test_guild_empty(self):
        await self.start_client({**CONFIG, "DISCORD_GUILD_ID": ""})
        self.assertEqual((await self.client.get("/", allow_redirects=False)).status, 200)
        oauth = await self.client.get("/auth/discord", allow_redirects=False)
        state = oauth.cookies["oauth_state"].value
        self.assertEqual(
            (
                await self.client.get(
                    f"/oauth/callback?state={state}&code=ok", cookies={"oauth_state": state}
                )
            ).status,
            403,
        )
