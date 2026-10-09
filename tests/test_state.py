"""Tests sans connexion Discord, avec donnees isolees dans un dossier temporaire.

Executer via Docker avec tests/ monte dans /tests (voir README).
"""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from tarot_commands.state import (
    check_legacy_scores, compute_scores, known_players, load_history,
    load_player_names, migrate_state, migrate_related_message_ids,
    normalize_player_names, save_history, save_player_names,
)
from tarot_commands.restore_lib import RestoreError, read_archive, read_snapshot, restore_archive
from tarot_commands.export_lib import build_export
from tarot_commands.history import (
    append_related_message_id,
    delete_history_entry,
    replace_history_entry,
    update_history,
)
from tarot_commands.sessions import find_history_by_message_id
from tarot_commands.edit import (
    EditOverwriteButton,
    handle_edit_message_edit,
    resolve_edit_target,
    strip_optional_auto_prefix,
)
from tarot_commands.delete import (
    end_delete_confirm,
    format_entry_summary,
    is_command_message,
    is_confirm_token,
    reset_pending_deletes,
    resolve_delete_target,
    try_begin_delete_confirm,
)
from tarot_commands.add_player import add_player, add_players
from tarot_commands.new_season import new_season
from tarot_commands.leaderboard import leaderboard_text, leaderboard2_text
from tarot_commands import game
import curves


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        reset_pending_deletes()
        save_player_names(['Alice', 'Bob', 'Carol', 'SansPartie'])
        self.games = [
            {'time': '01/10/2026, 12:00:00', 'scores': {'Alice': 40, 'Bob': -20, 'Carol': -20}},
            {'time': '01/10/2026, 13:00:00', 'scores': {'Alice': -10, 'Bob': 20, 'Carol': -10}},
        ]
        save_history(self.games)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def archive(self, players=None, history=None, prefix='', include_players=True):
        path = os.path.join(self.tmp.name, 'archive.zip')
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr(prefix + 'history.json', json.dumps(self.games if history is None else history))
            if include_players:
                zf.writestr(prefix + 'players.json', json.dumps(load_player_names() if players is None else players))
            zf.writestr(prefix + 'players_backup.json', '{invalid-json')
            zf.writestr(prefix + 'config.json', '{invalid-json')
            zf.writestr(prefix + 'Saison1/players.json', '{invalid-json')
        return path

    def test_totals_and_player_names(self):
        self.assertEqual(compute_scores(), {'Alice': 30, 'Bob': 0, 'Carol': -30, 'SansPartie': 0})
        save_player_names(['SansPartie'])
        self.assertEqual(known_players(), ['SansPartie', 'Alice', 'Bob', 'Carol'])
        self.assertEqual(normalize_player_names({'Alice': 123}), ['Alice'])
        self.assertEqual(normalize_player_names(['Alice', 'Alice']), ['Alice'])
        self.assertIn('SansPartie', leaderboard_text())
        self.assertIn('SansPartie', leaderboard2_text())

    def test_migration_keeps_scores_names_and_snapshot(self):
        legacy = compute_scores()
        Path('players.json').write_text(json.dumps(legacy))
        Path('players_backup.json').write_text('{}')
        before_scores = [dict(g['scores']) for g in load_history()]
        migrate_state()
        self.assertIsInstance(json.loads(Path('players.json').read_text()), list)
        self.assertEqual(compute_scores(), legacy)
        history = load_history()
        self.assertEqual([g['scores'] for g in history], before_scores)
        for entry in history:
            self.assertEqual(entry.get('related_message_ids'), [])
        backups = list(Path('.').glob('_pre_migration_*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads((backups[0] / 'players.json').read_text()), legacy)
        migrate_state()
        self.assertEqual(len(list(Path('.').glob('_pre_migration_*'))), 1)

    def test_related_message_ids_migration_lookup_replace(self):
        history = [
            {
                'time': '01/10/2026, 12:00:00',
                'message_id': 100001,
                'type': 'partie',
                'scores': {'Alice': 40, 'Bob': -20, 'Carol': -20},
            },
            {
                'time': '01/10/2026, 13:00:00',
                'message_id': 100002,
                'related_message_ids': [200002],
                'type': 'partie',
                'scores': {'Alice': -10, 'Bob': 20, 'Carol': -10},
            },
        ]
        save_history(history)
        self.assertTrue(migrate_related_message_ids(history))
        self.assertEqual(history[0]['related_message_ids'], [])
        self.assertFalse(migrate_related_message_ids(history))
        save_history(history)

        migrate_state()
        loaded = load_history()
        self.assertEqual(loaded[0]['related_message_ids'], [])
        self.assertEqual(loaded[1]['related_message_ids'], [200002])

        self.assertIs(find_history_by_message_id(loaded, 100001), loaded[0])
        self.assertIs(find_history_by_message_id(loaded, 200002), loaded[1])
        self.assertIsNone(find_history_by_message_id(loaded, 999999))

        replaced = replace_history_entry(
            200002,
            {'Alice': 5, 'Bob': -5, 'Carol': 0},
            {
                'message_id': 999,
                'type': 'partie',
                'preneur': 'Alice',
                'partenaire': None,
                'defenseurs': ['Bob', 'Carol'],
                'bouts': 1,
                'points_attaque': 50,
                'enchere': 'Garde',
                'multiplicateur': 2,
                'primes_attaque': [],
                'primes_defense': [],
                'miseres': [],
            },
        )
        self.assertIsNotNone(replaced)
        self.assertEqual(replaced['message_id'], 100002)
        self.assertEqual(replaced['time'], '01/10/2026, 13:00:00')
        self.assertEqual(replaced['related_message_ids'], [200002])
        self.assertEqual(replaced['scores']['Alice'], 5)
        self.assertEqual(replaced['points_attaque'], 50)

        self.assertTrue(append_related_message_id(100002, 300002))
        entry = find_history_by_message_id(load_history(), 100002)
        self.assertEqual(entry['related_message_ids'], [200002, 300002])

        before = load_history()
        self.assertIsNone(replace_history_entry(
            404404,
            {'Alice': 1},
            {'type': 'partie', 'message_id': 404404},
        ))
        self.assertEqual(load_history(), before)
        self.assertFalse(append_related_message_id(404404, 1))

    def test_resolve_edit_target(self):
        self.assertEqual(
            resolve_edit_target('1557730091864301699 Alice garde 50 2 vs Bob', None),
            (1557730091864301699, 'Alice garde 50 2 vs Bob'),
        )
        self.assertEqual(
            resolve_edit_target(
                '1557730091864301699 t/auto Alice garde 50 2 vs Bob',
                111,
            ),
            (1557730091864301699, 'Alice garde 50 2 vs Bob'),
        )
        self.assertEqual(
            resolve_edit_target('Alice garde 50 2 vs Bob', 222),
            (222, 'Alice garde 50 2 vs Bob'),
        )
        self.assertEqual(resolve_edit_target('', None), (None, None))
        self.assertEqual(resolve_edit_target('pas un id', None), (None, None))
        self.assertEqual(strip_optional_auto_prefix('t/auto Alice garde 45 2 vs Bob'),
                         'Alice garde 45 2 vs Bob')

    def test_handle_edit_message_edit_pending(self):
        game.reset_cache()
        save_history([{
            'time': '01/10/2026, 12:00:00',
            'message_id': 1557730091864301699,
            'related_message_ids': [],
            'type': 'partie',
            'scores': {'Alice': 40, 'Bob': -20, 'Carol': -20},
        }])
        session = game.create_session(400, author_id=42, source='edit')
        session.edit_target_message_id = 1557730091864301699
        game.autoparse('Alice garde 45 2 vs Bob Carol', session)
        session.confirm_message_id = 888
        old_reparse = session.reparse

        action, payload = handle_edit_message_edit(
            400,
            't/edit 1557730091864301699 Alice garde 45 2 vs Bob Carol',
            42,
        )
        self.assertEqual(action, 'noop')
        self.assertEqual(session.reparse, old_reparse)

        action, payload = handle_edit_message_edit(
            400,
            't/edit 1557730091864301699 Alice garde 50 2 vs Bob Carol',
            42,
        )
        self.assertEqual(action, 'updated')
        self.assertEqual(payload.points_attaque, 50)
        self.assertEqual(session.edit_target_message_id, 1557730091864301699)

        # Changer l'id dans le texte ne change pas la cible ; seul le corps est re-parse.
        action, payload = handle_edit_message_edit(
            400,
            't/edit 9999999999999999999 Bob petite 56 3 vs Alice Carol',
            42,
        )
        self.assertEqual(action, 'updated')
        self.assertEqual(payload.game_players['Preneur'], ['Bob'])
        self.assertEqual(session.edit_target_message_id, 1557730091864301699)

        action, payload = handle_edit_message_edit(
            400,
            't/edit 1557730091864301699 Alice garde 50 2 vs Bob Carol',
            99,
        )
        self.assertEqual(action, 'ignore')

        action, payload = handle_edit_message_edit(
            400,
            't/edit 1557730091864301699 pas un parse valide',
            42,
        )
        self.assertEqual(action, 'error')

        game.pop_session(400)
        action, payload = handle_edit_message_edit(
            400,
            't/edit 1557730091864301699 Alice garde 60 1 vs Bob Carol',
            42,
        )
        self.assertEqual(action, 'ignore')
        game.reset_cache()

    def test_edit_overwrite_timeout_respects_view_generation(self):
        """Une ancienne View Écraser ne doit pas pop_session après un re-bind."""
        async def exercise():
            game.reset_cache()
            session = game.create_session(500, author_id=42, source='edit')
            view1 = EditOverwriteButton(500)
            gen1 = view1.view_generation
            self.assertEqual(session.view_generation, gen1)
            self.assertGreater(gen1, 0)

            view2 = EditOverwriteButton(500)
            self.assertNotEqual(view1.view_generation, view2.view_generation)
            self.assertEqual(session.view_generation, view2.view_generation)

            await view1.on_timeout()
            self.assertIsNotNone(game.get_session(500))

            await view2.on_timeout()
            self.assertIsNone(game.get_session(500))
            game.reset_cache()

        asyncio.run(exercise())

    def test_delete_confirm_helpers(self):
        self.assertTrue(is_command_message('t/leaderboard'))
        self.assertTrue(is_command_message('  T/delete 123'))
        self.assertFalse(is_command_message('oui supprime'))
        self.assertFalse(is_command_message('bonjour'))
        self.assertTrue(is_confirm_token('oui supprime'))
        self.assertTrue(is_confirm_token('  oui supprime  '))
        self.assertFalse(is_confirm_token('Oui Supprime'))
        self.assertFalse(is_confirm_token('t/delete'))

        self.assertTrue(try_begin_delete_confirm(1, 10))
        self.assertFalse(try_begin_delete_confirm(1, 10))
        self.assertTrue(try_begin_delete_confirm(1, 11))
        self.assertTrue(try_begin_delete_confirm(2, 10))
        end_delete_confirm(1, 10)
        self.assertTrue(try_begin_delete_confirm(1, 10))
        reset_pending_deletes()
        self.assertTrue(try_begin_delete_confirm(1, 10))
        reset_pending_deletes()

    def test_migration_refuses_inconsistency_without_changes(self):
        Path('players.json').write_text('{"Alice":999}')
        before = Path('players.json').read_bytes()
        with self.assertRaises(ValueError):
            migrate_state()
        self.assertEqual(Path('players.json').read_bytes(), before)
        self.assertFalse(list(Path('.').glob('_pre_migration_*')))

    def test_fresh_state_and_missing_player_names(self):
        Path('players.json').unlink()
        migrate_state()
        self.assertEqual(load_player_names(), ['Alice', 'Bob', 'Carol'])
        Path('players.json').unlink()
        Path('history.json').unlink()
        migrate_state()
        self.assertEqual(load_player_names(), [])
        self.assertEqual(load_history(), [])

    def test_atomic_write_preserves_symlink_and_previous_json_on_error(self):
        Path('data').mkdir()
        Path('players.json').rename('data/players.json')
        Path('players.json').symlink_to('data/players.json')
        save_player_names(['Nouveau'])
        self.assertTrue(Path('players.json').is_symlink())
        self.assertEqual(load_player_names('data/players.json'), ['Nouveau'])
        before = Path('history.json').read_bytes()
        with patch('tarot_commands.state.os.replace', side_effect=OSError('test')):
            with self.assertRaises(OSError):
                save_history([])
        self.assertEqual(Path('history.json').read_bytes(), before)
        self.assertFalse(list(Path('.').glob('*.tmp')))

    def test_atomic_write_keeps_file_mode(self):
        os.chmod('history.json', 0o644)
        save_history(self.games)
        self.assertEqual(os.stat('history.json').st_mode & 0o777, 0o644)
        os.chmod('history.json', 0o640)
        save_history(self.games)
        self.assertEqual(os.stat('history.json').st_mode & 0o777, 0o640)
        save_player_names(['Nouveau'], 'nouveau.json')
        self.assertEqual(os.stat('nouveau.json').st_mode & 0o777, 0o644)

    def test_menu_players_respects_discord_limit(self):
        self.assertEqual(game.menu_players(), ['Alice', 'Bob', 'Carol', 'SansPartie'])
        player_names = [f'J{i}' for i in range(30)]
        history = [{'scores': {'J29': 1, 'J0': -1}}]
        players = game.menu_players(history, player_names)
        self.assertEqual(len(players), game.MAX_SELECT_OPTIONS)
        self.assertIn('J29', players)
        self.assertEqual(players, [p for p in player_names if p in players])
        save_player_names(player_names)
        save_history(history)
        selector = game.SelectPlayers('Preneur', 'x', 0)
        self.assertEqual(len(selector.options), game.MAX_SELECT_OPTIONS)

    def test_new_season_follows_symlinks(self):
        Path('data').mkdir()
        for name in ('players.json', 'history.json'):
            Path(name).rename(f'data/{name}')
            Path(name).symlink_to(f'data/{name}')
        with patch('tarot_commands.new_season.data_dir', return_value='data'):
            asyncio.run(new_season.callback(AsyncMock(), 'IAMSURE'))
        archives = [p for p in Path('data').iterdir() if p.is_dir()]
        self.assertEqual(len(archives), 1)
        self.assertFalse((archives[0] / 'history.json').is_symlink())
        self.assertEqual(load_history(archives[0] / 'history.json'), self.games)
        self.assertEqual(load_history(), [])

    def test_record_add_and_delete_entries(self):
        ctx = AsyncMock()
        asyncio.run(add_player.callback(ctx, 'Nouveau'))
        asyncio.run(add_player.callback(ctx, 'nouveau'))
        asyncio.run(add_players.callback(ctx, msg='  Eve   Frank Eve  '))
        self.assertEqual(load_player_names().count('Nouveau'), 1)
        self.assertEqual(load_player_names().count('Eve'), 1)
        self.assertEqual(compute_scores()['Nouveau'], 0)

        self.assertEqual(
            resolve_delete_target('1557730091864301699', None),
            1557730091864301699,
        )
        self.assertEqual(resolve_delete_target('', 111), 111)
        self.assertEqual(
            resolve_delete_target('1557730091864301699', 222),
            1557730091864301699,
        )
        self.assertIsNone(resolve_delete_target('', None))
        self.assertIsNone(resolve_delete_target('pas-un-id', None))

        save_history([
            {
                'time': '01/10/2026, 12:00:00',
                'message_id': 100001,
                'type': 'partie',
                'preneur': 'Alice',
                'enchere': 'Petite',
                'points_attaque': 50,
                'bouts': 2,
                'partenaire': None,
                'defenseurs': ['Bob', 'Carol'],
                'primes_attaque': [],
                'primes_defense': [],
                'miseres': [],
                'related_message_ids': [],
                'scores': {'Alice': 40, 'Bob': -20, 'Carol': -20},
            },
            {
                'time': '01/10/2026, 13:00:00',
                'message_id': 100002,
                'type': 'partie',
                'related_message_ids': [200002],
                'scores': {'Alice': -10, 'Bob': 20, 'Carol': -10},
            },
        ])
        update_history(
            {'Nouveau': 5, 'Alice': -5},
            {'type': 'test', 'message_id': 100003},
        )
        self.assertEqual(compute_scores()['Nouveau'], 5)
        self.assertFalse(Path('players_backup.json').exists())

        summary = format_entry_summary(load_history()[0])
        self.assertIn('Alice', summary)
        self.assertIn('Petite', summary)
        self.assertIn('contre Bob, Carol', summary)

        self.assertIsNone(delete_history_entry(404404))
        self.assertEqual(len(load_history()), 3)

        removed = delete_history_entry(200002)
        self.assertEqual(removed['message_id'], 100002)
        self.assertEqual(compute_scores()['Nouveau'], 5)
        self.assertEqual(compute_scores()['Alice'], 35)

        self.assertIsNotNone(delete_history_entry(100003))
        self.assertEqual(compute_scores()['Nouveau'], 0)
        self.assertEqual(compute_scores()['Alice'], 40)

        self.assertIsNotNone(delete_history_entry(100001))
        self.assertTrue(all(v == 0 for v in compute_scores().values()))
        self.assertEqual(load_history(), [])
        self.assertIsNone(delete_history_entry(100001))

    def test_game_parsing_menus_and_calculation(self):
        game.reset_cache()
        session = game.create_session(1, source='auto')
        game.autoparse('Alice garde 45 2 vs Bob Carol', session)
        scores = game.calcul_scores(session)
        update_history(scores, game.partie_details(session))
        self.assertEqual(len(load_history()), 3)
        self.assertEqual(compute_scores()['Alice'], 30 + scores['Alice'])
        selector = game.SelectPlayers('Preneur', 'x', 1)
        self.assertIn('SansPartie', [option.label for option in selector.options])
        game.reset_cache()
        session = game.create_session(2, source='auto')
        game.autoparse('descendante Alice 20 Bob 20 Carol 51', session)
        scores = game.calcul_score_descendante(
            session.descendante_players, session.descendante_points,
        )
        update_history(scores, game.descendante_details(session))
        self.assertEqual(len(load_history()), 4)
        game.reset_cache()

    def test_calculation_buttons_record_once_in_history(self):
        async def exercise():
            game.reset_cache()
            session = game.create_session(10, source='auto')
            game.autoparse('Alice garde 45 2 vs Bob Carol', session)
            expected = game.calcul_scores(session)
            view = game.GameCalculButton(10)
            interaction = AsyncMock()
            score_msg = AsyncMock()
            score_msg.id = 900010
            interaction.followup.send = AsyncMock(return_value=score_msg)
            await view.children[0].callback(interaction)
            entry = load_history()[-1]
            self.assertEqual(entry['scores'], expected)
            self.assertEqual(entry['related_message_ids'], [900010])
            self.assertIn('id: `10`', interaction.followup.send.call_args.args[0])
            self.assertEqual(compute_scores()['Alice'], 30 + expected['Alice'])
            self.assertTrue(view.children[0].disabled)
            self.assertEqual(load_player_names(), ['Alice', 'Bob', 'Carol', 'SansPartie'])
            session = game.create_session(11, source='auto')
            game.autoparse('descendante Alice 20 Bob 20 Carol 51', session)
            view = game.DescendanteCalculButton(11)
            score_msg2 = AsyncMock()
            score_msg2.id = 900011
            interaction.followup.send = AsyncMock(return_value=score_msg2)
            await view.children[0].callback(interaction)
            self.assertEqual(len(load_history()), 4)
            self.assertEqual(load_history()[-1]['related_message_ids'], [900011])
            self.assertTrue(view.children[0].disabled)
            self.assertFalse(Path('players_backup.json').exists())
            game.reset_cache()
        asyncio.run(exercise())

    def test_parallel_sessions_do_not_mix(self):
        game.reset_cache()
        s1 = game.create_session(100, author_id=1, source='auto')
        s2 = game.create_session(200, author_id=2, source='auto')
        game.autoparse('Alice garde 45 2 vs Bob Carol', s1)
        game.autoparse('Bob petite 56 3 vs Alice Carol', s2)
        self.assertEqual(s1.game_players['Preneur'], ['Alice'])
        self.assertEqual(s2.game_players['Preneur'], ['Bob'])
        self.assertEqual(s1.points_attaque, 45)
        self.assertEqual(s2.points_attaque, 56)
        self.assertIs(game.get_session(100), s1)
        self.assertIs(game.get_session(200), s2)
        game.reset_cache()

    def test_handle_auto_edit_pending_and_history(self):
        game.reset_cache()
        session = game.create_session(300, author_id=42, source='auto')
        game.autoparse('Alice garde 45 2 vs Bob Carol', session)
        session.confirm_message_id = 999
        old_reparse = session.reparse

        action, payload = game.handle_auto_edit(
            300, 't/auto Alice garde 45 2 vs Bob Carol', 42,
        )
        self.assertEqual(action, 'noop')
        self.assertEqual(session.reparse, old_reparse)

        action, payload = game.handle_auto_edit(
            300, 't/auto Alice garde 50 2 vs Bob Carol', 42,
        )
        self.assertEqual(action, 'updated')
        self.assertEqual(payload.points_attaque, 50)
        self.assertNotEqual(payload.reparse, old_reparse)

        action, payload = game.handle_auto_edit(
            300, 't/auto Alice garde 50 2 vs Bob Carol', 99,
        )
        self.assertEqual(action, 'ignore')

        scores = game.calcul_scores(session)
        update_history(scores, game.partie_details(session))
        game.pop_session(300)

        action, payload = game.handle_auto_edit(
            300, 't/auto Alice garde 60 1 vs Bob Carol', 42,
        )
        self.assertEqual(action, 'warn')

        action, payload = game.handle_auto_edit(
            300, 't/auto Alice garde 50 2 vs Bob Carol', 42,
        )
        self.assertEqual(action, 'noop')
        game.reset_cache()

    def test_new_season_archives_legacy_backup_if_present(self):
        Path('players_backup.json').write_text('{}')
        asyncio.run(new_season.callback(AsyncMock(), 'IAMSURE'))
        archives = [p for p in Path('.').iterdir() if p.is_dir()]
        self.assertTrue((archives[0] / 'players_backup.json').exists())
        self.assertFalse(Path('players_backup.json').exists())
        self.assertEqual(load_history(), [])

    def test_new_season_without_backup_and_with_legacy_residue(self):
        ctx = AsyncMock()
        asyncio.run(new_season.callback(ctx, 'IAMSURE'))
        self.assertEqual(load_history(), [])
        self.assertEqual(load_player_names(), [])
        archives = [p for p in Path('.').iterdir() if p.is_dir()]
        self.assertEqual(len(archives), 1)
        self.assertEqual(load_history(archives[0] / 'history.json'), self.games)
        # Une seconde demande le meme jour ne doit pas ecraser l'archive.
        asyncio.run(new_season.callback(ctx, 'IAMSURE'))
        self.assertEqual(load_history(archives[0] / 'history.json'), self.games)

    def test_old_new_missing_and_nested_restore(self):
        expected = compute_scores()
        for prefix in ('', '2026-10-05/'):
            data = read_archive(self.archive(players=expected, prefix=prefix))
            self.assertEqual(data['players.json'], load_player_names())
            self.assertEqual(set(data), {'players.json', 'history.json'})
        self.assertEqual(read_archive(self.archive())['players.json'], load_player_names())
        data = read_archive(self.archive(include_players=False))
        self.assertEqual(data['players.json'], ['Alice', 'Bob', 'Carol'])
        path = self.archive(players={'Alice': 999})
        before = Path('history.json').read_bytes()
        with self.assertRaises(RestoreError):
            restore_archive(path, self.tmp.name)
        self.assertEqual(Path('history.json').read_bytes(), before)
        one_game = {**self.games[0], 'message_id': 424242, 'related_message_ids': []}
        path = self.archive(
            players={'Alice': 40, 'Bob': -20, 'Carol': -20, 'Inscrit': 0},
            history=[one_game],
        )
        snapshot = restore_archive(path, self.tmp.name)
        self.assertTrue(Path(snapshot, 'history.json').exists())
        self.assertEqual(compute_scores()['Inscrit'], 0)
        self.assertEqual(compute_scores()['Alice'], 40)
        self.assertIsNotNone(delete_history_entry(424242))
        self.assertEqual(compute_scores()['Alice'], 0)

    def test_restore_snapshot_legacy_and_current(self):
        for players in (compute_scores(), load_player_names()):
            files = {'history.json': json.dumps(self.games).encode(),
                     'players.json': json.dumps(players).encode()}
            with patch('tarot_commands.restore_lib.resolve_snapshot', return_value={'id': 'snapshot'}), \
                    patch('tarot_commands.restore_lib._restic_dump', side_effect=lambda sid, name: files.get(name)):
                self.assertEqual(read_snapshot()['players.json'], load_player_names())

    def test_invalid_archives(self):
        for bad in ({}, [{'scores': []}], [{'scores': {'Alice': True}}],
                    [{'scores': {'Alice': '5'}}], [{'scores': {'Alice': float('nan')}}]):
            with self.assertRaises(RestoreError):
                read_archive(self.archive(history=bad))
        for bad in (None, 'Alice', [3], ['']):
            if bad is None:
                continue
            with self.assertRaises(RestoreError):
                read_archive(self.archive(players=bad))
        # Un JSON syntaxiquement incorrect ne doit pas etre accepte.
        path = self.archive()
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('history.json', '{')
        with self.assertRaises(RestoreError):
            read_archive(path)

    def test_export_and_curves(self):
        Path('Saison1').mkdir()
        save_history(self.games, 'Saison1/history.json')
        Path('config.json').write_text('{}')
        Path('_pre_migration_x').mkdir()
        Path('_pre_migration_x/players.json').write_text('{}')
        Path('history.backup-20261001-000000.json').write_text('[]')
        path = build_export(dest_dir=self.tmp.name, src=self.tmp.name)
        data = read_archive(path)
        self.assertEqual(data['history.json'], self.games)
        with zipfile.ZipFile(path) as zf:
            self.assertIn('Saison1/history.json', zf.namelist())
            self.assertNotIn('config.json', zf.namelist())
            self.assertNotIn('players_backup.json', zf.namelist())
            self.assertFalse([n for n in zf.namelist()
                              if n.startswith('_pre_') or n.startswith('history.backup-')])
        curves.render_curves()
        self.assertTrue(Path('curves.png').is_file())
        curves.plt.close('all')

    def test_mixed_season_stitcher(self):
        from season_stitcher import fuse_history_and_players
        Path('Saison1').mkdir()
        Path('Saison2').mkdir()
        save_history(self.games[:1], 'Saison1/history.json')
        Path('Saison1/players.json').write_text(json.dumps({'Alice': 40, 'Bob': -20, 'Carol': -20}))
        save_history(self.games[1:], 'Saison2/history.json')
        save_player_names(['Inscrit'], 'Saison2/players.json')
        with patch('season_stitcher.ARCHIVES_DIR', self.tmp.name):
            fuse_history_and_players(['Saison1', 'Saison2'])
        self.assertEqual(load_history(), self.games)
        self.assertEqual(compute_scores(), {'Alice': 30, 'Bob': 0, 'Carol': -30, 'Inscrit': 0})


if __name__ == '__main__':
    unittest.main()
