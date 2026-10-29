"""Régression de l'environnement de debug : seed, garde-fous, console."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from tarot_commands.internal_api import create_app as create_internal_app
from tarot_commands.state import load_history, load_player_names
from tarot_debug.api import add_debug_routes
from tarot_debug.build_fixture import ACTIVE_PLAYERS, PLAYERS, build
from tarot_debug.console import Console
from tarot_debug.guardrails import DebugGuardError, check
from tarot_debug.seed import seed_data_dir
from tarot_web.app import create_app
from tests.test_web import CONFIG


class TestSeed(unittest.TestCase):
    def test_build_is_deterministic_and_keeps_inactive_players_out_of_history(self):
        history = build()
        self.assertEqual(history, build())
        self.assertEqual(len(history), 36)
        self.assertTrue(all(set(entry["scores"]) <= set(ACTIVE_PLAYERS) for entry in history))
        self.assertTrue(set(PLAYERS) - set(ACTIVE_PLAYERS))

    def test_seed_creates_fixture_and_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_data_dir(tmp)
            players = json.loads((Path(tmp) / "players.json").read_text())
            history = json.loads((Path(tmp) / "history.json").read_text())
            self.assertEqual(len(players), 30)
            self.assertEqual(players, PLAYERS)
            self.assertEqual(len(set(players)), 30)
            long_names = [
                "Pauline-Marguerite",
                "Quentin-Emmanuel",
                "Romain-Alexandre",
                "Sarah-Éléonore",
                "Théo-Maximilien",
            ]
            start = players.index(long_names[0])
            self.assertEqual(players[start : start + 5], long_names)
            self.assertGreaterEqual(min(map(len, long_names)), 14)
            self.assertGreaterEqual(len(history), 30)
            self.assertTrue((Path(tmp) / ".debug").exists())

    def test_seed_is_idempotent_without_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_data_dir(tmp)
            path = Path(tmp) / "history.json"
            path.write_text("[]")
            seed_data_dir(tmp)
            self.assertEqual(path.read_text(), "[]")

    def test_reset_restores_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_data_dir(tmp)
            path = Path(tmp) / "history.json"
            path.write_text("[]")
            seed_data_dir(tmp, reset=True)
            self.assertGreaterEqual(len(json.loads(path.read_text())), 30)
            self.assertEqual(json.loads((Path(tmp) / "players.json").read_text()), PLAYERS)

    def test_refuses_prod_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "history.json").write_text("[]")
            with self.assertRaises(DebugGuardError):
                seed_data_dir(tmp)


class TestGuardrails(unittest.TestCase):
    def test_requires_debug_flag(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(DebugGuardError):
            check(tmp, environ={})

    def test_refuses_discord_token(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(DebugGuardError):
            check(tmp, environ={"TAROT_DEBUG": "1", "DISCORD_TOKEN": "real-token"})

    def test_refuses_prod_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "history.json").write_text("[]")
            with self.assertRaises(DebugGuardError):
                check(tmp, environ={"TAROT_DEBUG": "1"})

    def test_accepts_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            check(tmp, environ={"TAROT_DEBUG": "1"})

    def test_accepts_seeded_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_data_dir(tmp)
            check(tmp, environ={"TAROT_DEBUG": "1"})


class TestConsole(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oldcwd = os.getcwd()
        os.chdir(self.tmp.name)
        seed_data_dir(self.tmp.name)
        self.console = Console(self.tmp.name)

    async def asyncTearDown(self):
        os.chdir(self.oldcwd)
        self.tmp.cleanup()

    async def test_ping(self):
        result = await self.console.execute_text("t/ping")
        self.assertFalse(result["pending"])
        self.assertEqual(result["messages"][0]["text"], "pong!")

    async def test_auto_confirmation_then_calcul(self):
        result = await self.console.execute_text("t/auto Alice garde 45 2 vs Bob Claire")
        self.assertFalse(result["pending"])
        message = result["messages"][0]
        self.assertIn("Is this parse correct?", message["text"])
        self.assertEqual(message["view"]["items"][0]["label"], "Calcul")
        before = len(load_history())
        result = await self.console.execute_interaction(
            message["id"], message["view"]["items"][0]["id"], []
        )
        self.assertFalse(result["pending"])
        self.assertEqual(len(load_history()), before + 1)
        self.assertTrue(any("id:" in item["text"] for item in result["messages"]))

    async def test_delete_confirmation(self):
        target = load_history()[0]["message_id"]
        result = await self.console.execute_text(f"t/delete {target}")
        self.assertTrue(result["pending"])
        self.assertIn("oui supprime", result["messages"][0]["text"])
        result = await self.console.execute_text("oui supprime")
        self.assertFalse(result["pending"])
        self.assertIn("supprimée", result["messages"][-1]["text"])
        self.assertNotIn(target, [entry["message_id"] for entry in load_history()])

    async def test_pending_poll_and_command_reminder(self):
        target = load_history()[0]["message_id"]
        result = await self.console.execute_text(f"t/delete {target}")
        self.assertTrue(result["pending"])
        poll = await self.console.execute_text("")
        self.assertTrue(poll["pending"])
        self.assertEqual(poll["messages"], [])
        reminder = await self.console.execute_text("t/ping")
        self.assertTrue(reminder["pending"])
        self.assertIn("confirmation est en attente", reminder["messages"][0]["text"])
        result = await self.console.execute_text("non")
        self.assertFalse(result["pending"])
        self.assertIn("Annulé", result["messages"][-1]["text"])

    async def test_select_rejects_too_few_values(self):
        result = await self.console.execute_text("t/game 45")
        players_view = result["messages"][0]["view"]
        with self.assertRaises(ValueError):
            await self.console.execute_interaction(
                players_view["message_id"], players_view["items"][2]["id"], ["Bob"]
            )

    async def test_game_selects_then_calcul(self):
        result = await self.console.execute_text("t/game 45")
        self.assertFalse(result["pending"])
        self.assertEqual(len(result["messages"]), 3)
        players_view = result["messages"][0]["view"]
        primes_view = result["messages"][1]["view"]
        calcul_view = result["messages"][2]["view"]
        self.assertEqual(len(players_view["items"]), 5)
        self.assertEqual(len(primes_view["items"]), 3)
        self.assertEqual(calcul_view["items"][0]["label"], "Calcul")
        await self.console.execute_interaction(
            players_view["message_id"], players_view["items"][0]["id"], ["Alice"]
        )
        await self.console.execute_interaction(
            players_view["message_id"], players_view["items"][2]["id"], ["Bob", "Claire"]
        )
        await self.console.execute_interaction(
            players_view["message_id"], players_view["items"][3]["id"], ["Garde"]
        )
        await self.console.execute_interaction(
            players_view["message_id"], players_view["items"][4]["id"], ["2"]
        )
        before = len(load_history())
        result = await self.console.execute_interaction(
            calcul_view["message_id"], calcul_view["items"][0]["id"], []
        )
        self.assertFalse(result["pending"])
        self.assertEqual(len(load_history()), before + 1)

    async def test_edit_button(self):
        target = load_history()[0]["message_id"]
        result = await self.console.execute_text(f"t/edit {target} Alice garde 50 2 vs Bob Claire")
        self.assertFalse(result["pending"])
        message = result["messages"][0]
        self.assertEqual(message["view"]["items"][0]["label"], "Écraser")
        result = await self.console.execute_interaction(
            message["id"], message["view"]["items"][0]["id"], []
        )
        self.assertFalse(result["pending"])
        updated = next(entry for entry in load_history() if entry["message_id"] == target)
        self.assertEqual(updated["points_attaque"], 50)

    async def test_history_leaderboard_and_add_player(self):
        for command in ("t/history", "t/leaderboard", "t/rules", "t/help", "t/undo"):
            with self.subTest(command=command):
                result = await self.console.execute_text(command)
                self.assertFalse(result["pending"])
                self.assertTrue(result["messages"])
        result = await self.console.execute_text("t/add_player Zoe")
        self.assertFalse(result["pending"])
        self.assertIn("Zoe", load_player_names())


class TestDebugAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oldcwd = os.getcwd()
        os.chdir(self.tmp.name)
        seed_data_dir(self.tmp.name)
        self.console = Console(self.tmp.name)
        self.app = await create_internal_app(
            self.console.bot,
            token="internal-api-test-token-long-enough",
            channel_id="1",
            channel_type=type(self.console.channel),
        )
        add_debug_routes(self.app, self.console)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        os.chdir(self.oldcwd)
        self.tmp.cleanup()

    async def test_auth_and_command(self):
        response = await self.client.post("/debug/command", json={"text": "t/ping"})
        self.assertEqual(response.status, 401)
        headers = {"Authorization": "Bearer internal-api-test-token-long-enough"}
        response = await self.client.post(
            "/debug/command", json={"text": "t/ping"}, headers=headers
        )
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["messages"][0]["text"], "pong!")
        self.assertFalse(data["pending"])

    async def test_reset(self):
        headers = {"Authorization": "Bearer internal-api-test-token-long-enough"}
        await self.client.post("/debug/command", json={"text": "t/add_player Zoe"}, headers=headers)
        self.assertIn("Zoe", load_player_names())
        response = await self.client.post("/debug/reset", headers=headers)
        self.assertEqual(response.status, 200)
        self.assertNotIn("Zoe", load_player_names())


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
    def __init__(self):
        self.commands = []
        self.resets = 0

    def get(self, url, **_kwargs):
        if "discord.com" in url:
            raise AssertionError("Une requête Discord est interdite en debug")
        if url.endswith("/state"):
            return FakeResponse(200, {"players": ["Alice", "Bob", "Claire"], "history": []})
        return FakeResponse(404, {})

    def post(self, url, **kwargs):
        if "discord.com" in url:
            raise AssertionError("Une requête Discord est interdite en debug")
        if url.endswith("/debug/command"):
            self.commands.append(kwargs["json"])
            return FakeResponse(
                200,
                {
                    "messages": [{"id": 1, "kind": "bot", "text": "pong!", "view": None}],
                    "pending": False,
                },
            )
        if url.endswith("/debug/reset"):
            self.resets += 1
            return FakeResponse(200, {"ok": True})
        return FakeResponse(200, {"message_id": 1, "table_sent": True})


class TestWebDebug(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.http = FakeHTTP()
        self.app = await create_app(
            http=self.http,
            config={
                "TAROT_DEBUG": "1",
                "WEB_SESSION_SECRET": "debug-session-secret-0000000000000000",
                "TAROT_INTERNAL_TOKEN": "debug-internal-token-0000000000000000",
            },
        )
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(
            self.server,
            cookie_jar=CookieJar(unsafe=True, treat_as_secure_origin=self.server.make_url("/")),
        )
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def login(self, client):
        response = await client.get("/auth/discord", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/")

    async def test_home_after_login_shows_banner(self):
        await self.login(self.client)
        response = await self.client.get("/", allow_redirects=False)
        self.assertEqual(response.status, 200)
        text = await response.text()
        self.assertIn('<details class="debug-banner">', text)
        self.assertIn("<summary><strong>MODE DEBUG</strong></summary>", text)
        self.assertIn("Console de commandes", text)
        self.assertIn('action="/debug/reset"', text)
        self.assertIn('name="robots" content="noindex"', text)
        self.assertIn("Alice", text)

    async def test_debug_refuses_discord_token(self):
        with patch.dict(os.environ, {"DISCORD_TOKEN": "real-token"}), self.assertRaises(ValueError):
            await create_app(
                config={
                    "TAROT_DEBUG": "1",
                    "WEB_SESSION_SECRET": "debug-session-secret-0000000000000000",
                    "TAROT_INTERNAL_TOKEN": "debug-internal-token-0000000000000000",
                }
            )

    async def test_chat_command_and_reset(self):
        await self.login(self.client)
        response = await self.client.get("/debug/chat")
        self.assertEqual(response.status, 200)
        text = await response.text()
        csrf = re.search(r'name="csrf" value="([^"]+)"', text).group(1)
        denied = await self.client.post(
            "/debug/command", json={"text": "t/ping"}, headers={"X-CSRF-Token": "wrong"}
        )
        self.assertEqual(denied.status, 403)
        self.assertEqual(self.http.commands, [])
        denied = await self.client.post("/debug/reset", data={"csrf": "wrong"})
        self.assertEqual(denied.status, 403)
        self.assertEqual(self.http.resets, 0)
        response = await self.client.post(
            "/debug/command",
            json={"text": "t/ping"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["messages"][0]["text"], "pong!")
        self.assertEqual(self.http.commands[0]["text"], "t/ping")
        response = await self.client.post(
            "/debug/reset", data={"csrf": csrf}, allow_redirects=False
        )
        self.assertEqual(response.status, 302)
        self.assertEqual(self.http.resets, 1)

    async def test_login_is_idempotent_and_preserves_preview_and_csrf(self):
        await self.login(self.client)
        page = await self.client.get("/game")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        form = [
            ("csrf", csrf),
            ("joueurs", "Alice"),
            ("joueurs", "Bob"),
            ("joueurs", "Claire"),
            ("preneur", "Alice"),
            ("points_attaque", "54"),
            ("bouts", "1"),
            ("enchere", "2"),
        ]
        response = await self.client.post("/preview", data=form, allow_redirects=False)
        self.assertEqual(response.status, 303)
        location = response.headers["Location"]
        before = await self.client.get(location)
        html = await before.text()
        commit_id = re.search(r'name="commit_id" value="([^"]+)"', html).group(1)
        for _ in range(2):
            login = await self.client.get("/auth/discord", allow_redirects=False)
            self.assertEqual(login.status, 302)
            self.assertEqual(login.headers["Location"], "/")
            self.assertNotIn("tarot_session", login.cookies)
            preview = await self.client.get(location, allow_redirects=False)
            self.assertEqual(preview.status, 200)
            self.assertEqual(await preview.text(), html)
        response = await self.client.post("/commit", data=[*form, ("commit_id", commit_id)])
        self.assertEqual(response.status, 200)

    async def test_command_after_logout_returns_unauthorized(self):
        await self.login(self.client)
        page = await self.client.get("/debug/chat")
        csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
        logout = await self.client.post("/logout", data={"csrf": csrf}, allow_redirects=False)
        self.assertEqual(logout.status, 302)
        response = await self.client.post(
            "/debug/command", json={"text": "t/ping"}, headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(response.status, 401)
        self.assertNotIn("Location", response.headers)
        self.assertEqual(self.http.commands, [])

    async def test_command_after_session_expiry_returns_unauthorized(self):
        with patch("tarot_web.app.time") as clock:
            clock.monotonic.return_value = 100
            await self.login(self.client)
            page = await self.client.get("/debug/chat")
            csrf = re.search(r'name="csrf" value="([^"]+)"', await page.text()).group(1)
            clock.monotonic.return_value = 43300
            response = await self.client.post(
                "/debug/command", json={"text": "t/ping"}, headers={"X-CSRF-Token": csrf}
            )
            self.assertEqual(response.status, 401)
            self.assertNotIn("Location", response.headers)
            self.assertEqual(self.http.commands, [])

    async def test_sessions_and_previews_are_isolated_between_browsers(self):
        other = TestClient(
            self.server,
            cookie_jar=CookieJar(unsafe=True, treat_as_secure_origin=self.server.make_url("/")),
        )
        await other.start_server()
        try:
            await self.login(self.client)
            await self.login(other)
            first = await self.client.get("/game")
            second = await other.get("/game")
            csrf1 = re.search(r'name="csrf" value="([^"]+)"', await first.text()).group(1)
            csrf2 = re.search(r'name="csrf" value="([^"]+)"', await second.text()).group(1)
            self.assertNotEqual(csrf1, csrf2)
            form = [
                ("csrf", csrf1),
                ("joueurs", "Alice"),
                ("joueurs", "Bob"),
                ("joueurs", "Claire"),
                ("preneur", "Alice"),
                ("points_attaque", "54"),
                ("bouts", "1"),
                ("enchere", "2"),
            ]
            preview1 = await self.client.post("/preview", data=form, allow_redirects=False)
            self.assertEqual(preview1.status, 303)
            form[0] = ("csrf", csrf2)
            form[-3] = ("points_attaque", "55")
            preview2 = await other.post("/preview", data=form, allow_redirects=False)
            self.assertEqual(preview2.status, 303)
            location1 = preview1.headers["Location"]
            location2 = preview2.headers["Location"]
            self.assertEqual((await self.client.get(location1)).status, 200)
            self.assertEqual((await other.get(location2)).status, 200)
            foreign = await other.get(location1, allow_redirects=False)
            self.assertEqual(foreign.headers["Location"], "/game?expired=1#preview")
            denied = await other.post("/logout", data={"csrf": csrf1}, allow_redirects=False)
            self.assertEqual(denied.status, 403)
            logout = await self.client.post("/logout", data={"csrf": csrf1}, allow_redirects=False)
            self.assertEqual(logout.headers["Location"], "/login")
            self.assertEqual((await other.get(location2)).status, 200)
            self.assertEqual((await other.get("/debug/chat")).status, 200)
            await self.login(self.client)
            expired = await self.client.get(location1, allow_redirects=False)
            self.assertEqual(expired.headers["Location"], "/game?expired=1#preview")
            self.assertEqual((await other.get(location2)).status, 200)
        finally:
            await other.close()

    async def test_debug_routes_are_404_without_debug(self):
        app = await create_app(http=FakeHTTP(), config=CONFIG)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/debug/chat")).status, 404)
            self.assertEqual(
                (await client.post("/debug/command", json={"text": "t/ping"})).status, 404
            )
        finally:
            await client.close()
