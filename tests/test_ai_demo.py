import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from ai_demo import init_ai_schema
from detector import Detector

class CaptchaPresentationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=Path(self.tmp.name)/'test.db';app.detector=Detector()
  with app.db() as c:c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,ts TEXT,payload TEXT,published INTEGER DEFAULT 0)')
  init_ai_schema(app.db);self.client=app.app.test_client()
 def tearDown(self):self.tmp.cleanup()
 def start(self):return self.client.post('/api/ai-demo/start',json={'scene':'captcha'}).json['run']
 def test_bulk_input_ban_and_enforcement(self):
  run=self.start();data={'run_id':run['id'],'action':'bulk_input','input_type':'insertFromPaste','input_events':1,'key_events':0,'characters':6}
  r=self.client.post('/api/ai-demo/action',json=data);self.assertEqual(r.status_code,403);self.assertTrue(r.json['run']['banned'])
  count=len(r.json['run']['history']);again=self.client.post('/api/ai-demo/action',json=data);self.assertEqual(len(again.json['run']['history']),count)
 def test_normal_input_is_not_bulk_input(self):
  run=self.start();r=self.client.post('/api/ai-demo/action',json={'run_id':run['id'],'action':'bulk_input','input_type':'insertText','input_events':6,'key_events':6,'characters':6})
  self.assertEqual(r.status_code,400);self.assertFalse(self.client.get('/api/ai-demo/state').json['run']['banned'])
 def test_session_and_stale_run_isolation(self):
  old=self.start();self.start();self.assertIsNone(app.app.test_client().get('/api/ai-demo/state').json['run'])
  self.assertEqual(self.client.post('/api/ai-demo/action',json={'run_id':old['id'],'action':'bulk_input'}).status_code,409)
 def test_fake_seat_and_window_apis_removed(self):
  for scene in ['seats','parallel']:self.assertEqual(self.client.post('/api/ai-demo/start',json={'scene':scene}).status_code,400)

if __name__=='__main__':unittest.main(verbosity=2)
