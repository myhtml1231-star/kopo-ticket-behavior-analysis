import concurrent.futures
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from detector import Detector
from live_booking import init_live_schema


class LiveBookingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DB = Path(self.tmp.name) / 'test.db'
        app.detector = Detector()
        app.app.config['TESTING'] = True
        with app.db() as c:
            c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
        init_live_schema(app.db)
        self.service = app.app.extensions['live_booking']
        self.client = app.app.test_client()

    def tearDown(self):
        app.app.config['TESTING'] = False
        self.tmp.cleanup()

    def create(self, scene='seats', competitor=True):
        r = self.client.post('/api/live/start', json={'scene': scene, 'competitor': competitor})
        self.assertEqual(r.status_code, 200)
        self.rid = r.json['room']
        self.tokens = self.service.private[self.rid]
        return r.json

    def call(self, aid, action, data=None):
        url = f'/api/live/{self.rid}/{aid}/{action}'
        headers = {'X-Live-Token': self.tokens[aid]}
        return self.client.get(url, headers=headers) if data is None else self.client.post(url, headers=headers, json=data)

    def test_full_page_and_window_tokens(self):
        self.create('parallel')
        page = self.client.get(f'/practice/live/{self.rid}/1')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="sector-map"', page.data)
        self.assertIn(b'id="selected-list"', page.data)
        wrong = self.client.get(f'/api/live/{self.rid}/2/state', headers={'X-Live-Token': self.tokens['1']})
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(self.call('1', 'state').json['account_id'], self.call('5', 'state').json['account_id'])

    def test_real_inventory_success_when_competitor_is_off(self):
        self.create(competitor=False)
        self.assertFalse(any(s['available'] for s in self.call('1', 'seats?area=A').json['seats']))
        self.assertEqual(self.call('competitor', 'cancel', {'seat': 'A-4-8'}).status_code, 200)
        self.assertEqual(self.call('1', 'select', {'seat': 'A-4-8'}).status_code, 200)
        r = self.call('1', 'reserve', {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['outcome'], 'ok')
        self.assertTrue(r.json['reservation_id'])
        with app.db() as c:
            row = c.execute('SELECT status,actor FROM live_inventory WHERE room=? AND seat=?', (self.rid, 'A-4-8')).fetchone()
        self.assertEqual(tuple(row), ('reserved', '1'))

    def test_competitor_must_really_reserve_before_conflict_is_returned(self):
        self.create()
        self.call('competitor', 'cancel', {'seat': 'B-3-12'})
        self.call('1', 'select', {'seat': 'B-3-12'})
        self.call('competitor', 'select', {'seat': 'B-3-12'})
        self.assertEqual(self.call('competitor', 'reserve', {}).status_code, 200)
        r = self.call('1', 'reserve', {})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json['inventory_winner'], 'competitor')
        self.assertFalse(r.json['banned'])

    def test_cancel_requires_actual_ticket_ownership(self):
        self.create()
        self.assertEqual(self.call('1', 'cancel', {'seat': 'A-1-1'}).status_code, 409)
        self.assertEqual(self.call('competitor', 'cancel', {'seat': 'A-1-1'}).status_code, 200)

    def test_five_real_conflicts_and_regular_requests_trigger_ban(self):
        self.create()
        with patch('live_booking.time.time', return_value=1000) as now:
            for i in range(5):
                now.return_value = 1000 + i * 4.5
                seat = f'{"ABCDE"[i]}-4-8'
                self.call('competitor', 'cancel', {'seat': seat})
                self.call('1', 'select', {'seat': seat})
                self.call('competitor', 'select', {'seat': seat})
                self.assertEqual(self.call('competitor', 'reserve', {}).status_code, 200)
                r = self.call('1', 'reserve', {})
                self.assertEqual(r.status_code, 409 if i < 4 else 403)
            self.assertEqual(r.json['ban']['code'], 'periodic_inventory_conflicts')
            self.assertTrue(all(a['winner'] == 'competitor' for a in r.json['attempts']))

    def test_atomic_single_winner_for_two_actual_requests(self):
        self.create('parallel')
        self.call('1', 'select', {'seat': 'A-1-1'})
        self.call('2', 'select', {'seat': 'A-1-1'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda aid: self.service.reserve(self.rid, aid, delay=.08), ['1', '2']))
        self.assertEqual(sorted(code for _, code in results), [200, 409])
        self.assertFalse(self.service.room(self.rid)['banned'])

    def test_five_genuinely_inflight_requests_ban_all_windows(self):
        self.create('parallel')
        for i in range(1, 6):
            self.call(str(i), 'select', {'seat': f'A-1-{i}'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda aid: self.service.reserve(self.rid, aid, delay=.3), map(str, range(1, 6))))
        self.assertEqual([code for _, code in results], [403] * 5)
        self.assertEqual(self.service.room(self.rid)['ban']['code'], 'same_account_inflight')
        with app.db() as c:
            booked = c.execute("SELECT count(*) FROM live_inventory WHERE room=? AND status='reserved'", (self.rid,)).fetchone()[0]
            pending = c.execute('SELECT count(*) FROM live_requests WHERE room=? AND finished IS NULL', (self.rid,)).fetchone()[0]
        self.assertEqual(booked, 0)
        self.assertEqual(pending, 0)
        view = self.service.dashboard(self.service.room(self.rid))
        self.assertEqual(view['peak_inflight'], 5)
        self.assertGreater(view['overlap_ms'], 0)
        self.assertEqual(view['pending'], 0)

    def test_five_finished_sequential_requests_are_not_concurrency(self):
        self.create('parallel')
        for i in range(1, 6):
            self.call(str(i), 'select', {'seat': f'A-1-{i}'})
            _, code = self.service.reserve(self.rid, str(i), delay=0)
            self.assertEqual(code, 200)
        self.assertFalse(self.service.room(self.rid)['banned'])

    def test_native_launcher_is_owner_only_and_opens_full_urls(self):
        self.create('parallel')
        stranger = app.app.test_client()
        self.assertEqual(stranger.post(f'/api/live/{self.rid}/windows', json={}).status_code, 403)
        with patch('live_booking.open_browser_windows', return_value='chrome.exe') as launcher:
            response = self.client.post(f'/api/live/{self.rid}/windows', json={'width': 1920, 'height': 1080})
        self.assertEqual(response.status_code, 200)
        urls = launcher.call_args.args[0]
        self.assertEqual(len(urls), 5)
        self.assertTrue(all(u.startswith(f'http://127.0.0.1:5050/practice/live/{self.rid}/') for u in urls))

    def test_all_five_ready_still_wait_for_explicit_start(self):
        self.create('parallel')
        self.assertEqual(self.client.post(f'/api/live/{self.rid}/control', json={'action': 'fire'}).status_code, 409)
        self.assertEqual(self.call('1', 'ready', {}).status_code, 409)
        for i in range(1, 6):
            self.call(str(i), 'select', {'seat': f'A-1-{i}'})
            self.assertEqual(self.call(str(i), 'ready', {}).status_code, 200)
        room = self.service.room(self.rid)
        self.assertIsNone(room['fire_at'])
        self.assertEqual(room['phase'], 'waiting')
        self.assertEqual(self.client.post(f'/api/live/{self.rid}/control', json={'action': 'fire'}).status_code, 200)
        self.assertIsNotNone(self.service.room(self.rid)['fire_at'])
        self.assertEqual(self.client.post(f'/api/live/{self.rid}/control', json={'action': 'fire'}).status_code, 409)

    def test_grouped_view_uses_full_authenticated_pages(self):
        created = self.create('parallel')
        self.assertIn('/practice/multiview/', created['url'])
        page = self.client.get(f'/practice/multiview/{self.rid}')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b'class="client-card"'), 5)
        stranger = app.app.test_client()
        self.assertEqual(stranger.get(f'/api/live/{self.rid}/clients').status_code, 403)
        headers = {'X-Live-Token': self.tokens['controller']}
        clients = stranger.get(f'/api/live/{self.rid}/clients', headers=headers)
        self.assertEqual(len(clients.json['items']), 5)
        self.assertTrue(all(f'/practice/live/{self.rid}/' in i['url'] and 'embedded=1' in i['url'] for i in clients.json['items']))
        summary = stranger.get(f'/api/live/{self.rid}/dashboard', headers=headers)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json['peak_inflight'], 0)
        self.assertEqual(summary.json['overlap_ms'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
