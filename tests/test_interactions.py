import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from retry_booking import init_schema,SALES_SECONDS
from interaction_metrics import mouse_metrics,payment_metrics,fixtures,FIELDS

def path(duration=100,bend=0):
    return [{'t':duration*i/20,'x':80+500*i/20,'y':100+200*i/20+bend*math.sin(math.pi*i/20)} for i in range(21)]

def form(duration=1100,bulk=True):
    fields=[]
    for i,name in enumerate(FIELDS):
        n=(5,13,17,12)[i];start=duration*(.1+i*.2)
        events=[{'t':start,'chars':n}] if bulk else [{'t':start+k*duration*.15/n,'chars':1} for k in range(n)]
        fields.append({'field':name,'length':n,'events':events,'focused_at':start-duration*.02})
    return {'duration_ms':duration,'fields':fields}

class MetricTests(unittest.TestCase):
    def test_straight_fast_path_flagged_but_slow_straight_not_flagged(self):
        fast,slow=mouse_metrics(path()),mouse_metrics(path(1500))
        self.assertTrue(fast['suspicious']);self.assertFalse(slow['suspicious'])
        self.assertAlmostEqual(fast['straightness'],1)
        self.assertGreater(fast['speed_score']-slow['speed_score'],60)

    def test_departure_and_varying_speed_lower_pattern_score(self):
        straight=mouse_metrics(path());curved=mouse_metrics(path(1200,190))
        self.assertGreater(curved['deviation_px'],30)
        self.assertLess(curved['straightness'],straight['straightness'])
        self.assertGreater(curved['speed_cv'],straight['speed_cv'])
        self.assertLess(curved['pattern_score'],straight['pattern_score'])

    def test_landing_frame_does_not_fabricate_uneven_travelling_speed(self):
        raw=[{'t':t,'x':6000*min(t,100)/1000,'y':120} for t in range(0,113,16)]
        measured=mouse_metrics(raw)
        self.assertAlmostEqual(measured['mean_speed_px_s'],6000,places=2)
        self.assertEqual(measured['speed_cv'],0)
        self.assertGreater(measured['overall_speed_cv'],.1)
        self.assertEqual(measured['path'][-1]['t'],112)
        self.assertEqual(measured['path'][-1]['x'],600)
        self.assertEqual(measured['speed_window'],'travel_without_arrival_segment')

    def test_invalid_or_zero_duration_paths_rejected(self):
        for bad in [[],path(0),[{'x':0,'y':0,'t':i*10} for i in range(5)],path(float('nan'))]:
            with self.assertRaises((ValueError,ZeroDivisionError)):mouse_metrics(bad)

    def test_bulk_completion_is_ai_pattern_slow_typing_is_human_pattern(self):
        self.assertTrue(payment_metrics(form(),1100)['suspicious'])
        self.assertFalse(payment_metrics(form(15000,False),15000)['suspicious'])
        self.assertFalse(payment_metrics(form(15000,True),15000)['suspicious'])

    def test_field_metrics_use_focus_time_and_actual_previous_field(self):
        data=form();m=payment_metrics(data,1100)
        self.assertEqual(len(m['field_metrics']),4)
        for i,f in enumerate(m['field_metrics']):
            self.assertAlmostEqual(f['input_duration_ms'],22,places=2)
            self.assertEqual(f['bulk_ratio'],1)
            self.assertEqual(f['previous_field'],FIELDS[i-1] if i else None)
            self.assertEqual(f['transition_ms'],220 if i else None)
        data['fields'].reverse()
        self.assertEqual(payment_metrics(data,1100)['field_metrics'],m['field_metrics'])

    def test_faster_transition_increases_ai_score_with_same_field_speed(self):
        def measured(gap):
            data={'duration_ms':8000,'fields':[]}
            for i,name in enumerate(FIELDS):
                t=200+i*gap
                data['fields'].append({'field':name,'length':12,'focused_at':t-45,'events':[{'t':t,'chars':12}]})
            return payment_metrics(data,8000)['field_metrics']
        fast,slow=measured(200),measured(2000)
        self.assertEqual(fast[1]['speed_cps'],slow[1]['speed_cps'])
        self.assertGreater(fast[1]['risk_score'],slow[1]['risk_score'])
        self.assertTrue(fast[1]['suspicious']);self.assertFalse(slow[1]['suspicious'])

    def test_faster_field_input_increases_ai_score_and_focus_must_precede_input(self):
        data=form();fast=payment_metrics(data,1100)['field_metrics'][1]
        data['fields'][1]['focused_at']-=80
        slow=payment_metrics(data,1100)['field_metrics'][1]
        self.assertGreater(fast['speed_cps'],slow['speed_cps'])
        self.assertGreater(fast['risk_score'],slow['risk_score'])
        data['fields'][1]['focused_at']=999
        with self.assertRaises(ValueError):payment_metrics(data,1100)

    def test_raw_values_and_impossible_times_rejected(self):
        for data in [{**form(),'name':'PRIVATE'},form()]:
            with self.assertRaises(ValueError):payment_metrics(data,15000)
        data=form();data['fields'][0]['value']='PRIVATE'
        with self.assertRaises(ValueError):payment_metrics(data,1100)

    def test_fixtures_derive_from_twenty_explicit_synthetic_records(self):
        for mode in ('mouse','payment'):
            points=fixtures(mode);self.assertEqual(len(points),20)
            self.assertEqual(sum(p['actor_kind']=='human' for p in points),10)
            self.assertTrue(all(p['measurement_origin']=='synthetic_fixture' for p in points))

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DB;app.DB=Path(self.tmp.name)/'test.db'
        with app.db() as c:
            c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
            c.execute('CREATE TABLE checkout_runs(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
        init_schema(app.db);self.client=app.app.test_client()
        self.clock=patch('checkout.time.time',return_value=1000);self.now=self.clock.start()
    def tearDown(self):self.clock.stop();app.DB=self.old;self.tmp.cleanup()
    def post(self,route,data):return self.client.post('/api/'+route,json=data)
    def events(self):
        with app.db() as c:return [json.loads(r[0]) for r in c.execute('SELECT payload FROM events')]
    def attempt(self,n):
        self.now.return_value=1000+n*.4-.2
        run_id=self.client.get('/api/retry/state').json['run_id']
        with app.db() as c:self.last_seat=c.execute("SELECT seat FROM retry_inventory WHERE run_id=? AND status='available' ORDER BY sellout_rank DESC LIMIT 1",(run_id,)).fetchone()[0]
        selected=self.post('retry/select',{'seat':self.last_seat,'movement':path()})
        self.assertEqual(selected.status_code,200)
        self.now.return_value=1000+n*.4
        return self.post('retry/reserve',{'selection_token':selected.json['selection_token']})
    def test_selection_records_only_mouse_metrics_not_booking_cadence(self):
        self.post('retry/start',{'actor_kind':'ai'})
        for n in range(1,7):r=self.attempt(n)
        self.assertEqual(r.json['result'],'success')
        events=self.events();self.assertEqual(len(events),6)
        self.assertTrue(all(e['action']=='mouse_path' for e in events))
        self.assertTrue(all('avg_interval_ms' not in e for e in events))
        self.assertEqual(len(self.client.get('/api/retry/behavior').json['points']),26)
    def test_bad_telemetry_does_not_fabricate_a_mouse_measurement(self):
        self.post('retry/start',{'actor_kind':'human'})
        self.post('retry/select',{'seat':'A-1-1','movement':[]})
        self.assertEqual(self.events(),[])
    def test_deadline_and_reserved_inventory_preserved(self):
        run=self.post('retry/start',{'actor_kind':'ai'}).json
        for n in range(1,7):self.attempt(n)
        self.now.return_value=1000+SALES_SECONDS
        state=self.client.get('/api/retry/state').json
        self.assertEqual((state['result'],state['available_seats']),('success',0))
        with app.db() as c:self.assertEqual(c.execute('SELECT status FROM retry_inventory WHERE run_id=? AND seat=?',(run['run_id'],self.last_seat)).fetchone()[0],'reserved')
        self.assertEqual(self.post('retry/select',{'seat':'A-1-7'}).status_code,410)
    def test_payment_continuation_requires_reserved_seat_and_preserves_mode(self):
        self.assertEqual(self.post('checkout/start',{'from_retry':True}).status_code,409)
        self.post('retry/start',{'actor_kind':'ai'})
        for n in range(1,7):self.attempt(n)
        result=self.post('checkout/start',{'from_retry':True}).json
        self.assertEqual((result['actor_kind'],result['seat']),('ai',self.last_seat))
        self.now.return_value=1001+SALES_SECONDS
        self.client.get('/api/retry/state')
        after_close=self.post('checkout/start',{'from_retry':True})
        self.assertEqual(after_close.status_code,200)
        self.assertEqual(after_close.json['seat'],self.last_seat)
    def test_payment_mode_is_not_used_for_classification_and_replay_idempotent(self):
        self.post('checkout/start',{'actor_kind':'human'});self.now.return_value=1001.1
        first=self.post('checkout/complete',form())
        self.assertEqual(first.status_code,200);self.assertEqual(first.json['result']['verdict'],'AI 패턴')
        self.assertTrue(self.post('checkout/complete',form()).json['replayed'])
        self.assertEqual(len(self.events()),4)
        self.assertEqual(self.events()[0]['action'],'checkout_pattern')
        self.assertEqual(len(self.client.get('/api/checkout/behavior').json['points']),24)
        self.assertEqual({e['field'] for e in self.events()},set(FIELDS))
        self.assertTrue(all(e['input_duration_ms']>0 and 'transition_ms' in e and 'risk_score' in e for e in self.events()))
    def test_checkout_ownership_and_privacy(self):
        self.post('checkout/start',{'actor_kind':'ai'});self.now.return_value=1001.1
        self.assertEqual(app.app.test_client().post('/api/checkout/complete',json=form()).status_code,409)
        self.assertEqual(self.post('checkout/complete',{**form(),'phone':'PRIVATE'}).status_code,400)
        self.assertEqual(self.events(),[])
        self.assertEqual(self.post('checkout/complete',form()).status_code,200)
        with app.db() as c:
            payload=c.execute('SELECT payload FROM checkout_runs').fetchone()[0]
            self.assertNotIn('fields',payload)
            self.assertNotIn('PRIVATE',payload)
    def test_stage_pages_are_separate_and_mouse_path_button_is_stage_two_only(self):
        mouse=self.client.get('/presentation?scenario=retry').text
        payment=self.client.get('/presentation?scenario=payment').text
        self.assertIn('id="path-toggle"',mouse);self.assertNotIn('id="path-toggle"',payment)
        self.assertIn('/practice/checkout',payment)
        self.assertEqual(self.client.get('/practice/checkout').status_code,200)

if __name__=='__main__':unittest.main(verbosity=2)
