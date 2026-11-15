import os, json, time, uuid, sqlite3, threading, random, secrets
from datetime import datetime, timezone
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, g, has_request_context, redirect
import paho.mqtt.client as mqtt
from detector import Detector, VERSION
from behavior import build_points, WINDOW_SECONDS
import captcha_timing
import logging

BASE=Path(__file__).resolve().parent
load_dotenv(BASE/'.env')
app=Flask(__name__)
app.secret_key=os.getenv('APP_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax')
CAPTCHA_ONLY_LOGGING=os.getenv('CAPTCHA_ONLY_LOGGING','false').lower()=='true'
app.config['CAPTCHA_ONLY_LOGGING']=CAPTCHA_ONLY_LOGGING
if CAPTCHA_ONLY_LOGGING:logging.getLogger('werkzeug').setLevel(logging.ERROR)
DB=BASE/'demo.sqlite3'
lock=threading.RLock(); detector=Detector(); sessions=detector.sessions
state={'mqtt':'설정 필요', 'mqtt_detail':'', 'sim_running':False, 'sim_done':0, 'sim_total':0}
sim_stop=threading.Event()
@contextmanager
def db():
 c=sqlite3.connect(DB, timeout=10); c.row_factory=sqlite3.Row
 try:
  with c: yield c
 finally: c.close()
with db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, ts TEXT, payload TEXT, published INTEGER DEFAULT 0)')
 c.execute('CREATE TABLE IF NOT EXISTS seats (seat TEXT PRIMARY KEY, session TEXT)')
client=None

@app.before_request
def correlate_action_request():
 if request.method=='POST':
  g.behavior_request_id=uuid.uuid4().hex
  g.behavior_started_at=time.time()
def on_connect(c, u, flags, reason, props):
 state['mqtt']='연결됨' if reason == 0 else '연결 실패'; state['mqtt_detail']=str(reason)
def on_disconnect(c,u,flags,reason,props): state['mqtt']='연결 끊김'; state['mqtt_detail']=str(reason)
def init_mqtt():
 global client
 host=os.getenv('MQTT_HOST','').strip()
 if not host: return
 client_id=os.getenv('MQTT_WEB_CLIENT_ID','').strip() or 'ticket-web-'+uuid.uuid4().hex[:10]
 client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id); client.on_connect=on_connect; client.on_disconnect=on_disconnect
 if os.getenv('MQTT_USERNAME'): client.username_pw_set(os.getenv('MQTT_USERNAME'),os.getenv('MQTT_PASSWORD',''))
 if os.getenv('MQTT_TLS','true').lower()=='true': client.tls_set()
 try: state['mqtt']='연결 중'; client.connect_async(host,int(os.getenv('MQTT_PORT','8883')),60); client.loop_start()
 except Exception as e: state['mqtt']='연결 실패'; state['mqtt_detail']=str(e)
def worker_ready():
 try:
  w=json.loads((BASE/'worker_status.json').read_text(encoding='utf-8'))
  return w.get('subscribed',False) and (datetime.now(timezone.utc)-datetime.fromisoformat(w['heartbeat'])).total_seconds()<8
 except (OSError,ValueError,KeyError): return False

def publisher():
 while True:
  if client and client.is_connected() and worker_ready():
   with db() as c:
    condition=" AND json_extract(payload,'$.action') IN ('captcha_duration','booking_attempt','mouse_path','checkout_pattern')" if CAPTCHA_ONLY_LOGGING else ''
    rows=c.execute('SELECT id,payload FROM events WHERE published=0'+condition+' ORDER BY rowid LIMIT 20').fetchall()
   for row in rows:
    try:
     info=client.publish(os.getenv('MQTT_TOPIC','ticket-demo/events'),row['payload'],qos=1); info.wait_for_publish(timeout=5)
     if info.is_published():
      with db() as c: c.execute('UPDATE events SET published=1 WHERE id=?',(row['id'],))
    except Exception: break
  time.sleep(1)
def event(session, source, action, seat=None, outcome='ok', scenario=None, extra=None):
 with lock:
  if action in ('booking_attempt','mouse_path','checkout_pattern'):
   item={'event_id':str(uuid.uuid4()),'@timestamp':datetime.now(timezone.utc).isoformat(),
         'session_id':session,'source':source,'action':action,'seat':seat,'outcome':outcome,'scenario':scenario,**(extra or {})}
   with db() as c:
    c.execute('INSERT INTO events(id,ts,payload) VALUES(?,?,?)',(item['event_id'],item['@timestamp'],json.dumps(item,ensure_ascii=False)))
   return item
  if action=='captcha_duration':
   item=captcha_timing.make_item(session,**(extra or {}))
   with db() as c:
    exists=c.execute("SELECT 1 FROM events WHERE json_extract(payload,'$.action')='captcha_duration' AND json_extract(payload,'$.challenge_id')=?",(item['challenge_id'],)).fetchone()
    if not exists:c.execute('INSERT INTO events(id,ts,payload) VALUES(?,?,?)',(item['event_id'],item['@timestamp'],json.dumps(item,ensure_ascii=False)))
   return item
  assessment=detector.observe(session,action,seat,outcome)
  item={'event_id':str(uuid.uuid4()),'@timestamp':datetime.now(timezone.utc).isoformat(),'session_id':session,'source':source,'action':action,'seat':seat,'outcome':outcome,'scenario':scenario,**assessment,**(extra or {})}
  if has_request_context() and hasattr(g,'behavior_request_id'):
   item.update(http_request_id=g.behavior_request_id,http_started_at=g.behavior_started_at)
  if action=='reserve' and item['suspicious'] and outcome=='ok': item['outcome']='review_hold'
  if not CAPTCHA_ONLY_LOGGING:
   with db() as c: c.execute('INSERT INTO events(id,ts,payload) VALUES(?,?,?)',(item['event_id'],item['@timestamp'],json.dumps(item,ensure_ascii=False)))
 return item
@app.get('/')
def index():
 if CAPTCHA_ONLY_LOGGING:return redirect('/presentation')
 return render_template('index.html', kibana=os.getenv('KIBANA_URL',''))

@app.get('/presentation')
@app.get('/behavior')
def presentation():
 retry=request.args.get('scenario')=='retry'
 payment=request.args.get('scenario')=='payment'
 if retry or payment:
  return render_template('interaction_presentation.html',mode='payment' if payment else 'mouse',chart_only=request.path=='/behavior',
      from_retry=request.args.get('from')=='retry',kibana=os.getenv('KIBANA_LOG_URL') or os.getenv('KIBANA_URL',''))
 return render_template('captcha_presentation.html' if CAPTCHA_ONLY_LOGGING or retry else 'presentation.html',
    scenario_retry=retry,chart_only=request.path=='/behavior',
    kibana=(os.getenv('KIBANA_RETRY_URL') or os.getenv('KIBANA_LOG_URL') or os.getenv('KIBANA_URL','')) if retry else (os.getenv('KIBANA_CAPTCHA_URL') or os.getenv('KIBANA_LOG_URL') or os.getenv('KIBANA_URL','')))

@app.get('/api/behavior')
def behavior_data():
 if CAPTCHA_ONLY_LOGGING:
  return jsonify(mode='captcha_only',points=captcha_timing.points(db),fast_ms=captcha_timing.FAST_MS,
                 mqtt=state['mqtt'],worker_live=worker_ready())
 now=time.time()
 try: since=float(request.args.get('since',now-900))
 except (TypeError,ValueError): return jsonify(error='invalid since'),400
 if not float('-inf')<since<float('inf'): return jsonify(error='invalid since'),400
 since=max(now-3600,min(now,since))
 with db() as c:
  rows=c.execute("SELECT payload FROM events WHERE ts>=? AND json_extract(payload,'$.http_request_id') IS NOT NULL ORDER BY rowid",(datetime.fromtimestamp(since-WINDOW_SECONDS,timezone.utc).isoformat(),)).fetchall()
 events=[json.loads(r[0]) for r in rows]
 return jsonify(points=build_points(events,since,now),window_seconds=WINDOW_SECONDS,server_now=now,
                mqtt=state['mqtt'],worker_live=worker_ready())
@app.get('/api/state')
def status():
 if CAPTCHA_ONLY_LOGGING:
  items=captcha_timing.points(db)
  with db() as c:pending=c.execute("SELECT count(*) FROM events WHERE published=0 AND json_extract(payload,'$.action')='captcha_duration'").fetchone()[0]
  return jsonify(mode='captcha_only',events=items,total=len(items),pending=pending)
 with db() as c:
  rows=c.execute("SELECT payload,published FROM events WHERE json_extract(payload,'$.detector_version')=? ORDER BY rowid DESC LIMIT 60",(VERSION,)).fetchall(); total=c.execute('SELECT count(*) FROM events').fetchone()[0]; pending=c.execute('SELECT count(*) FROM events WHERE published=0').fetchone()[0]; booked=[r[0] for r in c.execute('SELECT seat FROM seats')]
  all_events=[json.loads(r[0]) for r in c.execute('SELECT payload FROM events')]
 events=[dict(json.loads(r['payload']),published=bool(r['published'])) for r in rows]
 worker={}
 try:
  worker=json.loads((BASE/'worker_status.json').read_text(encoding='utf-8'))
  worker['live']=(datetime.now(timezone.utc)-datetime.fromisoformat(worker['heartbeat'])).total_seconds()<8
  if not worker['live']: worker['elastic']='워커 미실행'
 except (OSError, ValueError, KeyError): worker={'live':False,'elastic':'워커 미실행'}
 sources={key:sum(e['source']==key for e in all_events) for key in ('browser','simulated_normal','simulated_bot')}
 risk=sum(e['suspicious'] or e.get('enforcement')=='ban' for e in all_events if e.get('detector_version')==VERSION)
 version_count=sum(e.get('detector_version')==VERSION for e in all_events)
 latest_bot=next((e for e in reversed(all_events) if e['source']==('simulated_normal' if state.get('sim_scenario')=='fast_normal' else 'simulated_bot') and e.get('detector_version')==VERSION),None)
 return jsonify(state=state,events=events,total=total,pending=pending,booked=booked,worker=worker,sources=sources,risk=risk,session_count=len({e['session_id'] for e in all_events}),latest_bot=latest_bot,detector_version=VERSION,version_count=version_count,cloud_configured=bool(os.getenv('ELASTIC_URL')))
@app.post('/api/action')
def action():
 data=request.get_json() or {}; session=str(data.get('session',''))[:80]; a=data.get('action'); seat=str(data.get('seat',''))[:10]
 if not session or a not in ('view','seat_select','reserve'): return jsonify(error='invalid request'),400
 valid=seat in [f'{r}{n}' for r in 'ABCDEF' for n in range(1,9)]
 with lock:
  outcome='ok'
  if a in ('seat_select','reserve') and not valid: outcome='invalid_seat'
  if a=='reserve':
   flow=detector.sessions[session]
   if not flow['viewed'] or flow['selected']!=seat: outcome='invalid_flow'
   elif valid:
    with db() as c:
     if c.execute('SELECT 1 FROM seats WHERE seat=?',(seat,)).fetchone(): outcome='seat_taken'
  item=event(session,'browser',a,seat or None,outcome)
  if outcome!='ok':
   messages={'invalid_seat':'올바르지 않은 좌석입니다.','invalid_flow':'공연 방문과 좌석 선택 후 예매해 주세요.','seat_taken':'이미 예매된 좌석입니다.'}
   return jsonify(event=item,message=messages[outcome]),409
  if a=='reserve':
   if item['suspicious']: return jsonify(event=item,message='여러 이상 신호가 겹쳐 예매를 검토 대상으로 보류했습니다.')
   with db() as c: c.execute('INSERT INTO seats(seat,session) VALUES(?,?)',(seat,session))
   return jsonify(event=item,message=f'{seat} 좌석 예매 완료')
 return jsonify(event=item)
def simulate(count,delay,scenario='mixed'):
 state.update(sim_running=True,sim_done=0,sim_total=count,sim_scenario=scenario)
 try:
  # Labels and scenario names are evaluation data only. They do not enter Detector.
  normal=[{'id':'sim-human-'+uuid.uuid4().hex[:8],'step':0,'seat':random.choice('ABCDEF')+str(random.randint(1,8))} for _ in range(24)]
  agent='sim-bot-'+uuid.uuid4().hex[:8]; n=0; bot_n=0
  profile=random.choice(['flow','failures']) if scenario=='mixed' else scenario
  for i in range(count):
   if sim_stop.is_set(): break
   isbot=i%5==4 if scenario=='mixed' else scenario!='fast_normal'
   if not isbot:
    person=normal[0] if scenario=='fast_normal' else normal[n%len(normal)]
    step=person['step']%3; action=['view','seat_select','reserve'][step]
    if scenario=='fast_normal':
     action='view' if n==0 else 'seat_select'; step=0 if n==0 else 1
     person['seat']=random.choice('ABCDEF')+str(random.randint(1,8))
    event(person['id'],'simulated_normal',action,person['seat'] if step else None,scenario='fast_normal' if scenario=='fast_normal' else 'normal')
    person['step']+=1; n+=1
   else:
    seat='C4'
    if profile=='flow':
     # Synthetic direct reservation attempts: exercise flow validation locally.
     event(agent,'simulated_bot','reserve',seat,'invalid_flow',scenario=profile)
    elif profile=='failures':
     step=bot_n%3; action=['view','seat_select','reserve'][step]
     event(agent,'simulated_bot',action,seat if step else None,'seat_taken' if step==2 else 'ok',scenario=profile)
    else:
     # Periodic activity alone must remain a weak signal.
     event(agent,'simulated_bot','seat_select',seat,scenario='periodic')
    bot_n+=1
   state['sim_done']=i+1
   time.sleep(delay*(random.uniform(.45,1.8) if scenario=='fast_normal' else 1))
 finally: state['sim_running']=False
@app.post('/api/simulate')
def start_sim():
 if state['sim_running']: return jsonify(error='이미 실행 중입니다.'),409
 d=request.get_json() or {}
 try: count=max(1,min(500,int(d.get('count',500)))); delay=max(0.02,min(2,float(d.get('delay',0.05))))
 except (TypeError,ValueError): return jsonify(error='invalid input'),400
 if d.get('scenario','mixed') not in ('mixed','fast_normal','periodic','flow','failures'): return jsonify(error='invalid scenario'),400
 with lock:
  if state['sim_running']: return jsonify(error='이미 실행 중입니다.'),409
  sim_stop.clear(); state['sim_running']=True
 threading.Thread(target=simulate,args=(count,delay,d.get('scenario','mixed')),daemon=True).start(); return jsonify(ok=True)
@app.post('/api/simulate/stop')
def stop_sim():
 sim_stop.set(); return jsonify(ok=True)
@app.post('/api/reset')
def reset():
 if state['sim_running']: return jsonify(error='생성 중에는 초기화할 수 없습니다.'),409
 with lock:
  with db() as c: c.execute('DELETE FROM events'); c.execute('DELETE FROM seats')
  sessions.clear()
 return jsonify(ok=True)
from practice import register_practice
register_practice(app,db,lock,event)
from ai_demo import register_ai_demo
register_ai_demo(app,db,lock,event)
from live_booking import register_live_booking
register_live_booking(app,db,lock,event)
from retry_booking import register_retry
register_retry(app,db,lock,event,lambda:{'mqtt':state['mqtt'],'worker_live':worker_ready()})
from checkout import register_checkout
register_checkout(app,db,lock,event,lambda:{'mqtt':state['mqtt'],'worker_live':worker_ready()})

if __name__=='__main__':
 if CAPTCHA_ONLY_LOGGING:captcha_timing.seed(db)
 init_mqtt(); threading.Thread(target=publisher,daemon=True).start(); app.run(host='127.0.0.1',port=5050,debug=False,threaded=True)

