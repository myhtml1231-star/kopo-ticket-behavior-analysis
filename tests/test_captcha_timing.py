import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import captcha_timing
from detector import Detector


class CaptchaTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db, self.original_mode = app.DB, app.CAPTCHA_ONLY_LOGGING
        app.DB = Path(self.tmp.name)/'test.db'
        app.CAPTCHA_ONLY_LOGGING = True
        app.detector = Detector()
        with app.db() as c:
            c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
            c.execute('CREATE TABLE seats(seat TEXT PRIMARY KEY,session TEXT)')
            c.execute('CREATE TABLE practice_runs(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
            c.execute('CREATE TABLE practice_inventory(run_id TEXT,seat TEXT,status TEXT,PRIMARY KEY(run_id,seat))')
            c.execute('CREATE TABLE ai_demo_runs(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
        self.client = app.app.test_client()

    def tearDown(self):
        app.DB, app.CAPTCHA_ONLY_LOGGING = self.original_db, self.original_mode
        self.tmp.cleanup()

    def events(self):
        with app.db() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT payload FROM events')]

    def test_fixture_exactly_ten_each_and_idempotent(self):
        captcha_timing.seed(app.db)
        captcha_timing.seed(app.db)
        rows = self.events()
        self.assertEqual(len(rows), 20)
        for kind in ('human', 'ai'):
            self.assertEqual(sum(r['actor_kind'] == kind for r in rows), 10)
        self.assertTrue(all(r['synthetic'] for r in rows))
        self.assertLess(max(r['duration_ms'] for r in rows if r['actor_kind']=='ai'),
                        min(r['duration_ms'] for r in rows if r['actor_kind']=='human'))
        points=captcha_timing.points(app.db)
        human=[p for p in points if p['actor_kind']=='human']
        ai=[p for p in points if p['actor_kind']=='ai']
        self.assertTrue(all(p['pattern_score']<60 for p in human))
        self.assertTrue(all(p['pattern_score']==100 for p in ai))
        self.assertGreater(max(p['pattern_score'] for p in human)-min(p['pattern_score'] for p in human),20)

    def test_other_actions_are_not_saved(self):
        for action in ['view','seat_select','reserve','area_view','captcha_verify','account_ban']:
            app.event('person','browser',action,'A1')
        self.assertEqual(self.events(), [])

    def test_measure_only_after_display_until_success_and_no_duplicate(self):
        with patch('practice.time.time', return_value=1000) as now:
            self.client.post('/api/practice/start',json={'mode':'relaxed'})
            now.return_value=1005
            self.client.post('/api/practice/queue',json={})
            now.return_value=1013
            state=self.client.get('/api/practice/state').json
            cid=state['captcha_id']
            self.assertEqual(self.events(), [])
            self.assertEqual(self.client.post('/api/practice/captcha/shown',json={'captcha_id':'stale'}).status_code,409)
            self.client.post('/api/practice/captcha/shown',json={'captcha_id':cid})
            self.client.post('/api/practice/captcha/verify',json={'answer':'WRONG','captcha_id':cid,'duration_ms':100})
            self.assertEqual(self.events(), [])
            with app.db() as c:
                run=json.loads(c.execute('SELECT payload FROM practice_runs').fetchone()[0])
            now.return_value=1017
            payload={'answer':run['answer'],'captcha_id':cid,'duration_ms':4000,'input_duration_ms':1500,
                     'input_event_offsets_ms':[0,100,600,750,1300,1500],'input_event_chars':[1]*6}
            self.assertEqual(self.client.post('/api/practice/captcha/verify',json=payload).status_code,200)
            self.client.post('/api/practice/captcha/verify',json=payload)
            rows=self.events()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['duration_ms'],1500)
            self.assertEqual(rows[0]['display_to_submit_ms'],4000)
            self.assertEqual(rows[0]['speed_cps'],4)
            self.assertFalse(rows[0]['synthetic'])
            self.assertNotIn('requests_60s',rows[0])
            self.assertNotIn('seat',rows[0])

    def test_browser_ai_completion_records_time_once_without_ban(self):
        run=self.client.post('/api/ai-demo/start',json={'scene':'captcha'}).json['run']
        self.assertEqual(self.events(),[])
        base={'run_id':run['id']}
        self.client.post('/api/ai-demo/action',json={**base,'action':'captcha_shown'})
        for _ in range(2):
            r=self.client.post('/api/ai-demo/action',json={**base,'action':'captcha_complete','duration_ms':3000,'input_duration_ms':1,
                              'input_event_offsets_ms':[0],'input_event_chars':[6]})
        self.assertEqual(r.status_code,200)
        self.assertFalse(r.json['run']['banned'])
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.events()[0]['duration_ms'],1)
        self.assertEqual(self.events()[0]['display_to_submit_ms'],3000)
        self.assertEqual(self.events()[0]['speed_cps'],6000)
        self.assertEqual(self.client.get('/api/behavior').json['points'][0]['pattern_score'],100)

    def test_api_excludes_old_events_and_flag_depends_on_duration(self):
        with app.db() as c:
            c.execute('INSERT INTO events VALUES(?,?,?,0)',('old','old',json.dumps({'action':'reserve'})))
        for kind in ('human','ai'):
            app.event(kind,'browser','captcha_duration',extra={'duration_ms':200,'input_duration_ms':200,'actor_kind':kind,'measurement_origin':'browser_input_span'})
        data=self.client.get('/api/behavior').json
        self.assertEqual(len(data['points']),2)
        self.assertTrue(all(p['fast'] for p in data['points']))
        self.assertEqual(len(self.client.get('/api/state').json['events']),2)

    def test_extreme_bulk_input_is_bounded_and_remains_near_fast_reference(self):
        reference=captcha_timing.pattern_metrics(50,[0],[6])
        live=captcha_timing.pattern_metrics(6000,[0],[6])
        self.assertLess(abs(reference['speed_score']-live['speed_score']),1)
        self.assertEqual(live['pattern_score'],100)
        self.assertLessEqual(live['speed_score'],100)

    def test_timing_variation_changes_pattern_without_changing_speed(self):
        regular=captcha_timing.pattern_metrics(2,[0,200,400,600,800,1000],[1]*6)
        irregular=captcha_timing.pattern_metrics(2,[0,50,700,730,900,1000],[1]*6)
        self.assertEqual(regular['speed_score'],irregular['speed_score'])
        self.assertGreater(regular['pattern_score'],irregular['pattern_score'])
        missing=captcha_timing.pattern_metrics(6000)
        self.assertIsNone(missing['pattern_score'])

    def test_replay_targets_change_by_ten_ms_and_keep_submillisecond_precision(self):
        targets=[]
        for _ in range(4):
            run=self.client.post('/api/ai-demo/start',json={'scene':'captcha'}).json['run']
            targets.append(run['input_target_ms'])
        self.assertEqual(targets,[220,230,240,250])
        self.client.post('/api/ai-demo/action',json={'run_id':run['id'],'action':'captcha_shown'})
        self.client.post('/api/ai-demo/action',json={'run_id':run['id'],'action':'captcha_complete',
            'duration_ms':3100,'input_duration_ms':250.125,'input_event_offsets_ms':[250.125],
            'input_event_chars':[6],'simulation_timing':'variable_bulk_processing'})
        item=self.events()[0]
        self.assertEqual(item['input_duration_ms'],250.125)
        self.assertEqual(item['input_duration_us'],250125)
        self.assertEqual(item['simulation_target_ms'],250)
        self.assertEqual(item['input_event_chars'],[6])
        a=captcha_timing.pattern_metrics(6000/250.125,[250.125],[6])
        b=captcha_timing.pattern_metrics(6000/260.125,[260.125],[6])
        self.assertNotEqual(a['speed_score'],b['speed_score'])
        self.assertEqual(a['pattern_score'],100)


if __name__=='__main__':
    unittest.main(verbosity=2)
