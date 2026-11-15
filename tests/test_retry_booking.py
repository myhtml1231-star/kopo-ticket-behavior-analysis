import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from retry_booking import init_schema, metrics, SALES_SECONDS


class RetryBookingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old_db=app.DB;app.DB=Path(self.tmp.name)/'test.db'
        with app.db() as c:
            c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
        init_schema(app.db);self.client=app.app.test_client()
        self.clock=patch('retry_booking.time.time',return_value=1000);self.now=self.clock.start()

    def tearDown(self):
        self.clock.stop();app.DB=self.old_db;self.tmp.cleanup()

    def post(self,route,**data):return self.client.post('/api/retry/'+route,json=data)
    def start(self,kind='human'):
        self.now.return_value=1000
        r=self.post('start',actor_kind=kind);self.assertEqual(r.status_code,200);self.run_id=r.json['run_id'];return r.json
    def safe_seat(self):
        with app.db() as c:return c.execute("SELECT seat FROM retry_inventory WHERE run_id=? AND status='available' ORDER BY sellout_rank DESC LIMIT 1",(self.run_id,)).fetchone()[0]
    def attempt(self,n,at):
        self.now.return_value=at-1
        self.last_seat=self.safe_seat();selected=self.post('select',seat=self.last_seat);self.assertEqual(selected.status_code,200)
        self.now.return_value=at
        return self.post('reserve',selection_token=selected.json['selection_token'])
    def rows(self):
        with app.db() as c:return [json.loads(r[0]) for r in c.execute('SELECT payload FROM events')]

    def test_both_modes_fail_five_then_really_reserve_sixth(self):
        for kind in ['human','ai']:
            run=self.start(kind)
            for n in range(1,7):
                r=self.attempt(n,1000+n*1.2)
                self.assertEqual(r.status_code,409 if n<=5 else 200)
                self.assertEqual(len(r.json['attempts']),n)
                self.assertEqual(r.json['result'],'success' if n==6 else None)
            self.assertTrue(r.json['reservation_id'])
            with app.db() as c:
                self.assertEqual(c.execute('SELECT status FROM retry_inventory WHERE run_id=? AND seat=?',(run['run_id'],self.last_seat)).fetchone()[0],'reserved')
        self.assertEqual(len(self.rows()),0)
        self.assertEqual(sum(a['forced_failure'] for a in r.json['attempts']),5)

    def test_empty_and_invalid_selections_do_not_count_as_attempts(self):
        self.start();self.assertEqual(self.post('reserve').status_code,409)
        self.assertEqual(self.post('select',seat='FORGED').status_code,409)
        self.assertEqual(self.client.get('/api/retry/state').json['metrics']['attempt_count'],0)
        self.assertEqual(self.rows(),[])

    def test_repeated_request_does_not_make_an_extra_attempt(self):
        self.start();self.now.return_value=1001
        token=self.post('select',seat=self.safe_seat()).json['selection_token']
        self.now.return_value=1002
        first=self.post('reserve',selection_token=token)
        again=self.post('reserve',selection_token=token)
        self.assertEqual(first.status_code,409);self.assertTrue(again.json['replayed'])
        self.assertEqual(again.json['metrics']['attempt_count'],1)
        self.assertEqual(len(self.rows()),0)

    def test_sessions_are_isolated_and_polling_is_not_logged(self):
        self.start();self.assertEqual(app.app.test_client().get('/api/retry/state').json['phase'],'intro')
        for _ in range(3):self.client.get('/api/retry/state');self.client.get('/api/retry/seats?area=A')
        self.assertEqual(self.rows(),[])
        seats=self.client.get('/api/retry/seats?area=A').json
        self.assertEqual(len(seats['seats']),450)
        self.assertEqual(self.client.get('/practice/retry').status_code,200)

    def test_metrics_use_server_time_and_wait_for_three_attempts(self):
        self.start()
        for n in range(1,4):
            r=self.attempt(n,1000+n*2.4)
            self.assertEqual(r.json['metrics']['sample_ready'],n>=3)
        e=r.json['metrics']
        self.assertAlmostEqual(e['avg_interval_ms'],2400,places=3)
        self.assertEqual(e['selection_avg_ms'],1000)
        self.assertEqual(e['cadence_cv'],0)
        self.assertEqual(e['consistency_index'],100)
        points=self.client.get('/api/retry/behavior').json['points']
        self.assertEqual(len(points),20)
        self.assertTrue(all(p['measurement_origin']=='synthetic_fixture' for p in points))
        self.assertGreater(points[-1]['pattern_score'],95)

    def test_same_behavior_has_same_score_for_human_and_ai(self):
        scores=[]
        for kind in ['human','ai']:
            self.start(kind)
            for n in range(1,7):r=self.attempt(n,1000+n*1.2)
            scores.append(r.json['metrics']['risk_score'])
        self.assertEqual(scores[0],scores[1])

    def test_irregular_timing_reduces_consistency_score(self):
        regular=[{'at':i*2.4,'selection_to_submit_ms':1000} for i in range(6)]
        irregular=[{'at':at,'selection_to_submit_ms':latency} for at,latency in zip([0,2,7,10,18,20],[400,1800,700,2300,1200,500])]
        a,b=metrics(regular),metrics(irregular)
        self.assertGreater(a['consistency_index'],b['consistency_index'])
        self.assertGreater(a['risk_score'],b['risk_score'])

    def test_fast_ai_has_clear_speed_separation_without_actor_bias(self):
        def measured(gap):
            return metrics([{'at':i*gap,'selection_to_submit_ms':gap*400} for i in range(6)])
        human,ai=measured(1.2),measured(.4)
        self.assertGreater(ai['speed_index']-human['speed_index'],35)
        self.assertGreater(ai['attempts_per_second'],human['attempts_per_second']*2.9)
        self.assertEqual(ai['consistency_index'],human['consistency_index'])

    def test_inventory_gives_time_to_book_then_progressively_closes(self):
        with patch('retry_booking.uuid.uuid4',return_value=SimpleNamespace(hex='spatial-inventory-regression')):
            self.assertEqual(self.start()['available_seats'],3600)
        self.assertEqual(SALES_SECONDS,20)
        self.now.return_value=1000+SALES_SECONDS*.25
        self.assertEqual(self.client.get('/api/retry/state').json['available_seats'],2700)
        seats=self.client.get('/api/retry/seats?area=A').json['seats']
        # Each row has sold and available seats; depletion is spatially mixed.
        for row in range(1,16):
            statuses=[s['available'] for s in seats if s['id'].split('-')[1]==str(row)]
            self.assertTrue(any(statuses));self.assertFalse(all(statuses))
        self.now.return_value=1000+SALES_SECONDS*.5
        self.assertEqual(self.client.get('/api/retry/state').json['available_seats'],1800)
        self.now.return_value=1010
        early=self.client.get('/api/retry/state').json
        self.assertEqual(early['remaining_seconds'],10)
        self.assertFalse(early['sales_closed'])
        self.now.return_value=1000+SALES_SECONDS
        state=self.client.get('/api/retry/state').json
        self.assertEqual((state['available_seats'],state['remaining_seconds'],state['result']),(0,0,'sold_out'))
        self.assertEqual(self.post('select',seat='A-1-1').status_code,410)
        self.assertEqual(self.post('reserve').status_code,410)
        self.assertEqual(self.rows(),[])

    def test_success_is_preserved_while_remaining_stock_sells_out(self):
        run=self.start('ai')
        for n in range(1,7):r=self.attempt(n,1000+n*1.2)
        self.assertEqual((r.json['result'],r.json['phase']),('success','seats'))
        self.now.return_value=1000+SALES_SECONDS
        state=self.client.get('/api/retry/state').json
        self.assertEqual((state['result'],state['phase'],state['available_seats']),('success','result',0))
        self.assertAlmostEqual(state['total_seconds'],7.2)
        with app.db() as c:
            self.assertEqual(c.execute('SELECT status FROM retry_inventory WHERE run_id=? AND seat=?',(run['run_id'],self.last_seat)).fetchone()[0],'reserved')

    def test_selected_seat_can_sell_before_submit_and_can_be_reselected(self):
        run=self.start()
        with app.db() as c:
            seat=c.execute('SELECT seat FROM retry_inventory WHERE run_id=? AND sellout_rank=1800',(run['run_id'],)).fetchone()[0]
        self.now.return_value=1001
        token=self.post('select',seat=seat).json['selection_token']
        self.now.return_value=1000+SALES_SECONDS*.6
        failed=self.post('reserve',selection_token=token)
        self.assertEqual(failed.status_code,409)
        self.assertEqual(failed.json['error_code'],'seat_sold_out')
        self.assertEqual(failed.json['conflict_seat'],seat)
        self.assertEqual(failed.json['selected'],[])
        self.assertEqual(failed.json['attempts'],[])
        already_sold=self.post('select',seat=seat)
        self.assertEqual(already_sold.json['error_code'],'seat_sold_out')
        self.assertEqual(self.post('select',seat=self.safe_seat()).status_code,200)

    def test_sixth_request_after_deadline_cannot_reserve(self):
        self.start()
        for n in range(1,6):self.attempt(n,1000+n*1.2)
        self.now.return_value=1006.5
        token=self.post('select',seat=self.safe_seat()).json['selection_token']
        self.now.return_value=1000+SALES_SECONDS
        self.assertEqual(self.post('reserve',selection_token=token).status_code,410)
        self.assertEqual(len(self.rows()),0)
        self.assertEqual(self.client.get('/api/retry/state').json['available_seats'],0)


if __name__=='__main__':unittest.main(verbosity=2)
