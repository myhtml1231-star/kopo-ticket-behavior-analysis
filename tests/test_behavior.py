import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from behavior import build_points
import app
from detector import Detector


def entry(rid, at, action='seat_select', **extra):
    return {'http_request_id': rid, 'http_started_at': at, 'session_id': 's1',
            'action': action, 'source': 'browser', 'risk_score': 0, 'rules': [], **extra}


class CoordinatesTests(unittest.TestCase):
    def test_coordinates_and_first_request(self):
        p = build_points([entry('a', 10), entry('b', 12), entry('c', 14)], 0, 20)
        self.assertEqual([r['requests_30s'] for r in p], [1, 2, 3])
        self.assertEqual([r['speed'] for r in p], [0, .5, .5])
        self.assertIsNone(p[0]['interval_ms'])

    def test_deduplicates_receive_complete_and_ban(self):
        events = [entry('a', 10, 'reserve_received'), entry('a', 10, 'reserve'),
                  entry('a', 10, 'account_ban', enforcement='ban', demo_rules=['5 concurrent'])]
        p = build_points(events, 0, 20)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['decision'], 'blocked')
        self.assertIn('5 concurrent', p[0]['rules'])

    def test_rolling_window_and_account_aggregation(self):
        events = [entry('a', 1, account_id='account'),
                  entry('b', 2, account_id='account', session_id='s2'),
                  entry('c', 40, account_id='account')]
        p = build_points(events, 0, 50)
        self.assertEqual(p[1]['requests_30s'], 2)
        self.assertEqual(p[-1]['requests_30s'], 1)
        self.assertEqual(p[-1]['speed'], 0)

    def test_labels_do_not_change_coordinates_or_decision(self):
        a = build_points([entry('a', 10, source='browser')], 0, 20)
        b = build_points([entry('a', 10, source='simulated_bot')], 0, 20)
        self.assertEqual((a[0]['speed'], a[0]['decision']), (b[0]['speed'], b[0]['decision']))

    def test_excludes_background_future_and_uncorrelated_logs(self):
        events = [entry('a', 10, 'inventory_competition'), entry(None, 10), entry('b', 100)]
        self.assertEqual(build_points(events, 0, 20), [])


class BehaviorApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db = app.DB
        app.DB = Path(self.tmp.name) / 'test.db'
        app.detector = Detector()
        app.sessions = app.detector.sessions
        with app.db() as c:
            c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
            c.execute('CREATE TABLE seats(seat TEXT PRIMARY KEY,session TEXT)')
        self.client = app.app.test_client()

    def tearDown(self):
        app.DB = self.original_db
        self.tmp.cleanup()

    def test_real_actions_create_three_points_polls_create_none(self):
        since = time.time() - 1
        for action in ['view', 'seat_select', 'reserve']:
            r = self.client.post('/api/action', json={'session': 'person', 'action': action, 'seat': 'A1'})
            self.assertEqual(r.status_code, 200)
        for _ in range(3):
            r = self.client.get('/api/behavior', query_string={'since': since})
            self.assertEqual(len(r.json['points']), 3)
            self.assertEqual(r.json['points'][-1]['requests_30s'], 3)
        with app.db() as c:
            event = json.loads(c.execute('SELECT payload FROM events LIMIT 1').fetchone()[0])
        self.assertIn('http_request_id', event)

    def test_invalid_query_and_presentation_pages(self):
        for value in ['no', 'nan', 'inf']:
            self.assertEqual(self.client.get('/api/behavior?since='+value).status_code, 400)
        for path in ['/presentation', '/behavior']:
            self.assertEqual(self.client.get(path).status_code, 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
