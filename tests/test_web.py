"""Régression : saisie web, ACL Discord et chemins protégés."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from multidict import MultiDict

from tarot_commands.internal_api import create_app as create_internal_app
from tarot_commands.sessions import find_history_by_message_id
from tarot_commands.state import load_history
from tarot_commands.web_game import InvalidGame, validate_game
from tarot_web.app import chart_svg, create_app, parse_form, render

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
            "preview.html", scores={"<img src=x>": 42}, error="", csrf="123", commit_id="456"
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
    def __init__(self, message_id):
        self.id = message_id

    async def delete(self):
        pass


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return FakeMessage(100 + len(self.sent))


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

    def get(self, url, **_kwargs):
        if url.endswith("/users/@me/guilds"):
            return FakeResponse(200, [{"id": self.guild}])
        if url.endswith("/users/@me"):
            return FakeResponse(200, {"id": "42", "username": "Tester"})
        return FakeResponse(200, {"history": [], "players": PLAYERS})

    def post(self, url, **kwargs):
        if url.endswith("/oauth2/token"):
            return FakeResponse(200, {"access_token": "token", "expires_in": 3600})
        self.commits.append(kwargs["json"])
        return FakeResponse(200, {"message_id": 101, "table_sent": True})


class TestWeb(unittest.IsolatedAsyncioTestCase):
    async def start_client(self, config=CONFIG, guild="999"):
        self.http = FakeHTTP(guild=guild)
        self.client = TestClient(
            TestServer(await create_app(http=self.http, config=config)),
            cookie_jar=CookieJar(unsafe=True),
        )
        await self.client.start_server()

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
        self.assertIn('src="/static/game.js"', html)
        self.assertIn('type="search"', html)
        self.assertIn(
            '<select id="preneur" name="preneur" required><option value="">Choisir un joueur…</option></select>',
            html,
        )
        self.assertIn(
            '<select id="partenaire" name="partenaire"><option value="">Aucun · joue seul</option></select>',
            html,
        )
        self.assertNotIn('name="miseres"', html)
        self.assertIn('id="touch-roles"', html)
        self.assertIn('id="taker-choices"', html)
        self.assertIn('id="partner-choices"', html)
        self.assertIn('type="radio" name="enchere" value="1"', html)
        self.assertIn('type="radio" name="bouts" value="0"', html)
        self.assertIn('inputmode="numeric"', html)
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
        preview = await self.client.post("/preview", data=form, cookies=cookie)
        self.assertEqual(preview.status, 200)
        text = await preview.text()
        self.assertIn("Aperçu des scores", text)
        self.assertIn("Bob", text)
        self.assertIn('name="miseres" value="Bob"', text)
        self.assertNotIn('name="miseres" value="Eve"', text)
        self.assertIn('<option value="Alice" selected>Alice</option>', text)
        self.assertNotIn('<option value="Eve"', text)
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
