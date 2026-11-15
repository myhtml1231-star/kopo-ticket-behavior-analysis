import sys,tempfile,json,unittest,wave,io
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from detector import Detector

class PracticeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=Path(self.tmp.name)/'test.db';app.detector=Detector();app.sessions=app.detector.sessions
  with app.db() as c:
   c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
   c.execute('CREATE TABLE seats(seat TEXT PRIMARY KEY,session TEXT)')
   c.execute('CREATE TABLE practice_runs(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
   c.execute('CREATE TABLE practice_inventory(run_id TEXT,seat TEXT,status TEXT,PRIMARY KEY(run_id,seat))')
  self.client=app.app.test_client();self.clock=patch('practice.time.time',return_value=1000);self.now=self.clock.start()
 def tearDown(self):self.clock.stop();self.tmp.cleanup()
 def post(self,path,**data):return self.client.post('/api/practice/'+path,json=data)
 def get(self,path):return self.client.get('/api/practice/'+path)
 def run_data(self):
  with app.db() as c:return json.loads(c.execute('SELECT payload FROM practice_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0])
 def start(self,mode='relaxed'):
  r=self.post('start',mode=mode,nickname='tester');self.assertEqual(r.status_code,200);return r.json
 def admit(self,mode='relaxed'):
  self.start(mode);self.now.return_value=1005;self.post('queue');self.now.return_value=1013;return self.get('state').json
 def verify(self):
  self.admit();answer=self.run_data()['answer'];return self.post('captcha/verify',answer=answer)
 def available(self,area='C'):return [s['id'] for s in self.get('seats?area='+area).json['seats'] if s['available']]
 def test_open_queue_resume_and_session_isolation(self):
  s=self.start();self.assertEqual(self.post('queue').status_code,409)
  self.now.return_value=1005;self.assertEqual(self.post('queue').json['phase'],'queue')
  self.now.return_value=1009;v=self.get('state').json;self.assertGreater(v['queue_rank'],0);self.assertLess(v['queue_rank'],200000)
  self.assertEqual(v['run_id'],s['run_id']);self.assertEqual(app.app.test_client().get('/api/practice/state').json['phase'],'intro')
  self.now.return_value=1013;self.assertEqual(self.get('state').json['phase'],'captcha')
 def test_gates_captcha_refresh_image_and_audio(self):
  self.admit();self.assertEqual(self.post('select',seat='C-1-1').status_code,403)
  self.assertEqual(self.post('reserve').status_code,403)
  self.assertEqual(self.post('captcha/verify',answer='WRONG').status_code,422)
  self.assertEqual(self.post('captcha/refresh').status_code,200)
  image=self.get('captcha.svg');self.assertEqual(image.mimetype,'image/svg+xml')
  sound=self.get('captcha.wav');self.assertEqual(sound.mimetype,'audio/wav')
  with wave.open(io.BytesIO(sound.data)) as w:self.assertGreater(w.getnframes(),0)
  answer=self.run_data()['answer'];self.assertEqual(self.post('captcha/verify',answer=answer).json['phase'],'seats')
 def test_success_and_record(self):
  self.verify();seat=self.available()[-1];self.post('select',seat=seat);self.now.return_value=1014
  r=self.post('reserve');self.assertEqual(r.json['result'],'success');self.assertTrue(r.json['reservation_id']);self.assertAlmostEqual(sum(r.json['segments'].values()),r.json['total_seconds'],places=1)
  self.assertEqual(len(self.get('ranking').json['items']),1)
  with app.db() as c:
   events=[json.loads(r[0]) for r in c.execute('SELECT payload FROM events')]
  self.assertTrue(any(e['action']=='reserve' and 'practice_run' in e for e in events))
 def test_competitor_takes_selected_seat_and_recovery(self):
  self.verify();seat=self.available()[-1];self.post('select',seat=seat)
  with app.db() as c:c.execute("UPDATE practice_inventory SET status='taken' WHERE seat=?",(seat,))
  r=self.post('reserve');self.assertEqual(r.status_code,409);self.assertEqual(self.get('state').json['selected'],[])
  seat=self.available()[-1];self.post('select',seat=seat);self.assertEqual(self.post('reserve').json['result'],'success')
 def test_max_two_and_adjacency(self):
  self.verify();available=self.available();a=available[0];b=next(s for s in available if s.split('-')[1]!=a.split('-')[1]);self.post('select',seat=a);self.post('select',seat=b)
  self.assertEqual(self.post('select',seat=available[-1]).status_code,409);self.assertEqual(self.post('reserve').status_code,409)
 def test_sellout_and_forged_selection(self):
  self.admit('standard');self.now.return_value=1036;s=self.get('state').json;self.assertEqual(s['result'],'sold_out');self.assertEqual(s['total_seconds'],30)
  self.assertEqual(self.post('reserve',selected=['A-1-1'],verified=True).status_code,403)
 def test_sellout_without_joining_queue(self):
  self.start('standard');self.now.return_value=1036
  s=self.get('state').json;self.assertEqual(s['result'],'sold_out');self.assertEqual(s['total_seconds'],30)
 def test_deselect_lost_seat(self):
  self.verify();seat=self.available()[-1];self.post('select',seat=seat)
  with app.db() as c:c.execute("UPDATE practice_inventory SET status='taken' WHERE seat=?",(seat,))
  r=self.post('select',seat=seat);self.assertEqual(r.status_code,200);self.assertEqual(r.json['selected'],[])
 def test_forged_gate_requests_raise_multiple_evidence(self):
  self.start()
  for i in range(20):self.post('reserve',verified=True,selected=['C-1-1'])
  with app.db() as c:events=[json.loads(r[0]) for r in c.execute('SELECT payload FROM events')]
  self.assertTrue(all(e['outcome']=='gate_violation' for e in events if e['action']=='reserve'))
  self.assertTrue(any(s['code']=='invalid_workflow' for e in events for s in e['signals']))

if __name__=='__main__':unittest.main(verbosity=2)
