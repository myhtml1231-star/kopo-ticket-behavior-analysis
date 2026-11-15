import io,json,random,secrets,time,uuid,wave,threading
import requests
from pathlib import Path
from flask import Blueprint,request,jsonify,session,render_template,redirect,Response

AREAS='ABCDEFGH'; ROWS=15; COLS=30
TITLE='KOPO'

def register_practice(app,db,lock,emit):
 bp=Blueprint('practice',__name__)
 bot_token=secrets.token_urlsafe(32)
 bot_state={'running':False,'requests':0,'rejected':0,'review':0,'risk_score':0,'error':None}
 with db() as c:
  c.execute('CREATE TABLE IF NOT EXISTS practice_runs(id TEXT PRIMARY KEY, owner TEXT, payload TEXT)')
  c.execute('CREATE TABLE IF NOT EXISTS practice_inventory(run_id TEXT, seat TEXT, status TEXT, PRIMARY KEY(run_id,seat))')
 def save(run):
  with db() as c:c.execute('INSERT OR REPLACE INTO practice_runs VALUES(?,?,?)',(run['id'],run['owner'],json.dumps(run,ensure_ascii=False)))
 def log(run,action,seat=None,outcome='ok',source=None,**extra):
  return emit(run['owner'],source or run.get('source','browser'),action,seat,outcome,scenario='practice',extra={'practice_run':run['id'],'practice_phase':run['phase'],**extra})
 def current():
  rid=session.get('practice_run');owner=session.get('practice_owner')
  with db() as c:r=c.execute('SELECT payload FROM practice_runs WHERE id=? AND owner=?',(rid,owner)).fetchone()
  return json.loads(r[0]) if r else None
 def challenge(run):
  run['answer']=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(6));run['captcha_created']=time.time()
  run['captcha_id']=uuid.uuid4().hex;run['captcha_shown_at']=None;run['captcha_duration_recorded']=False
 def finish(run,result,now=None):
  if run.get('result'):return
  now=time.time() if now is None else now
  opened=run['opens_at'];q=run.get('queued_at',now);admitted=run.get('admitted_at',now);verified=run.get('verified_at',now)
  values={'반응':max(0,q-opened),'대기열':max(0,min(admitted,now)-q),'보안문자':max(0,min(verified,now)-admitted),'좌석':max(0,now-verified)}
  run.update(phase='result',finished_at=now,result=result,segments={k:round(v,2) for k,v in values.items()},total_seconds=round(max(0,now-opened),2))
  log(run,'practice_result',outcome=result,result=result,total_seconds=run['total_seconds']);save(run)
 def tick(run):
  now=time.time()
  if run['phase'] in ('opening','queue') and now>=run['opens_at']+run['duration']:
   finish(run,'sold_out',run['opens_at']+run['duration']);return run
  if run['phase']=='queue' and now>=run['queue_until']:
   run.update(phase='captcha',admitted_at=run['queue_until']);challenge(run);log(run,'queue_admit');save(run)
  if run['phase'] in ('captcha','seats'):
   elapsed=max(0,now-run['opens_at']);target=min(len(run['available_order']),int(elapsed/run['duration']*len(run['available_order'])))
   consumed=run.get('consumed',0)
   if target>consumed:
    with db() as c:
     for seat in run['available_order'][consumed:target]:c.execute("UPDATE practice_inventory SET status='taken' WHERE run_id=? AND seat=? AND status='available'",(run['id'],seat))
    run['consumed']=target;save(run)
    emit('crowd-'+run['id'],'simulated_normal','inventory_competition',scenario='practice',extra={'practice_run':run['id'],'consumed_seats':target-consumed})
   if elapsed>=run['duration']:finish(run,'sold_out',run['opens_at']+run['duration'])
  return run
 def public(run):
  now=time.time();phase=run['phase'];admitted=run.get('admitted_at')
  return {'run_id':run['id'],'captcha_id':run.get('captcha_id'),'phase':phase,'nickname':run['nickname'],'date':run['date'],'time':run['time'],'title':TITLE,'opens_in':max(0,run['opens_at']-now),'queue_rank':max(0,int(run.get('rank',200000)*max(0,run.get('queue_until',now)-now)/run['queue_seconds'])) if phase=='queue' else 0,'queue_left':max(0,run.get('queue_until',now)-now) if phase=='queue' else 0,'remaining_seconds':max(0,run['duration']-(now-run['opens_at'])) if admitted and phase!='result' else 0,'verified':bool(run.get('verified_at')),'selected':run.get('selected',[]),'result':run.get('result'),'segments':run.get('segments'),'total_seconds':run.get('total_seconds'),'reservation_id':run.get('reservation_id'),'duration':run['duration'],'last_decision':run.get('last_decision'),'last_risk_score':run.get('last_risk_score',0)}
 def gate(run):
  if run['phase']!='seats' or not run.get('verified_at'):
   assessment=log(run,'reserve',outcome='gate_violation')
   run.update(last_decision=assessment['decision'],last_risk_score=assessment['risk_score']);save(run);return False
  return True
 @bp.get('/practice')
 def entry():return redirect('/practice/intro')
 @bp.get('/practice/intro')
 @bp.get('/practice/booking')
 def page():return render_template('practice.html')
 @bp.post('/api/practice/start')
 def start():
  data=request.get_json(silent=True) or {};mode=data.get('mode','standard')
  if mode not in ('standard','relaxed'):return jsonify(error='잘못된 모드입니다.'),400
  nickname=str(data.get('nickname','예매자')).strip()[:20] or '예매자'
  owner='practice-'+secrets.token_hex(12);rid=uuid.uuid4().hex;now=time.time();rng=random.Random(rid)
  all_seats=[f'{a}-{r}-{n}' for a in AREAS for r in range(1,ROWS+1) for n in range(1,COLS+1)]
  available=rng.sample(all_seats,400 if mode=='relaxed' else 240);rng.shuffle(available)
  run={'id':rid,'owner':owner,'nickname':nickname,'date':'2026-02-08','time':'19:00','phase':'opening','opens_at':now+5,'queue_seconds':8,'rank':200000,'duration':120 if mode=='relaxed' else 30,'available_order':available,'consumed':0,'selected':[],'captcha_attempts':0,'result':None}
  if secrets.compare_digest(request.headers.get('X-Ticket-Demo-Bot',''),bot_token):run['source']='simulated_bot'
  with lock:
   old=current()
   if old and not old.get('result'):finish(old,'cancelled')
   session['practice_run']=rid;session['practice_owner']=owner;save(run)
   with db() as c:c.executemany('INSERT INTO practice_inventory VALUES(?,?,?)',[(rid,s,'available' if s in available else 'taken') for s in all_seats])
   log(run,'view');log(run,'practice_start')
  return jsonify(public(run))
 @bp.get('/api/practice/state')
 def get_state():
  with lock:
   run=current()
   if not run:return jsonify(phase='intro',bot=dict(bot_state))
   return jsonify(**public(tick(run)),bot=dict(bot_state))
 @bp.post('/api/practice/bot')
 def start_bot():
  with lock:
   if bot_state['running']:return jsonify(error='자동 예매이 실행 중입니다.'),409
   bot_state.update(running=True,requests=0,rejected=0,review=0,risk_score=0,error=None)
  def run_bot():
   # Fixed loopback destination: this demonstrator cannot target external sites.
   try:
    with requests.Session() as http:
     http.trust_env=False
     r=http.post('http://127.0.0.1:5050/api/practice/start',json={'nickname':'절차 우회 봇','mode':'relaxed'},headers={'X-Ticket-Demo-Bot':bot_token},timeout=5);r.raise_for_status()
     deadline=time.monotonic()
     for n in range(24):
      time.sleep(max(0,deadline+n*.2-time.monotonic()))
      r=http.post('http://127.0.0.1:5050/api/practice/reserve',json={'verified':True,'selected':['D-1-1'],'skip_queue':True},timeout=5)
      data=r.json()
      with lock:bot_state.update(requests=n+1,rejected=bot_state['rejected']+int(r.status_code==403),review=bot_state['review']+int(data.get('decision')=='review'),risk_score=data.get('risk_score',0))
   except (requests.RequestException,ValueError) as e:
    with lock:bot_state['error']='로컬 예매 API에 연결할 수 없습니다.'
   finally:
    with lock:bot_state['running']=False
  threading.Thread(target=run_bot,daemon=True).start()
  return jsonify(dict(bot_state))
 @bp.post('/api/practice/queue')
 def queue():
  with lock:
   run=current()
   if not run:return jsonify(error='예매를 먼저 시작하세요.'),409
   tick(run)
   if run['phase']!='opening':return jsonify(public(run))
   if time.time()<run['opens_at']:
    log(run,'reserve',outcome='gate_violation');return jsonify(error='예매 오픈 전입니다.'),409
   now=time.time();run.update(phase='queue',queued_at=now,queue_until=now+run['queue_seconds']);log(run,'queue_enter');save(run)
   return jsonify(public(run))
 @bp.get('/api/practice/captcha.svg')
 def captcha_image():
  with lock:
   run=current()
   if not run or run['phase'] not in ('captcha','seats'):return '',403
   answer=run['answer'];rng=random.Random(answer)
   dots=''.join(f'<circle cx="{rng.randrange(400)}" cy="{rng.randrange(140)}" r="{rng.choice([.5,1,1.5])}" fill="{rng.choice(["#aaa","#bbb","#cfb2b2"])}"/>' for _ in range(900))
   chars=''.join(f'<text x="{65+i*45}" y="{83+rng.randrange(-8,8)}" transform="rotate({rng.randrange(-15,15)} {65+i*45} 78)" font-family="monospace" font-weight="bold" font-size="42" fill="#a4dc78">{ch}</text>' for i,ch in enumerate(answer))
   svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="140" viewBox="0 0 400 140"><rect width="400" height="140" fill="#f9f9f9"/><rect x="40" y="28" width="325" height="85" fill="#8e171d"/>{dots}{chars}<path d="M35 100 Q160 20 370 80" fill="none" stroke="#ffffff66" stroke-width="2"/></svg>'
   return Response(svg,mimetype='image/svg+xml',headers={'Cache-Control':'no-store'})
 @bp.get('/api/practice/captcha.wav')
 def captcha_audio():
  with lock:
   run=current()
   if not run or run['phase'] not in ('captcha','seats'):return '',403
   answer=run['answer']
  output=io.BytesIO();params=None
  try:
   with wave.open(output,'wb') as out:
    for ch in answer:
     with wave.open(str(Path(__file__).parent/'static'/'audio'/(ch+'.wav')),'rb') as src:
      if params is None:params=src.getparams();out.setparams(params)
      out.writeframes(src.readframes(src.getnframes()));out.writeframes(b'\0'*(int(params.framerate*.25)*params.sampwidth*params.nchannels))
   return Response(output.getvalue(),mimetype='audio/wav',headers={'Cache-Control':'no-store'})
  except (OSError,wave.Error):return jsonify(error='음성 파일을 사용할 수 없습니다.'),503
 @bp.post('/api/practice/captcha/refresh')
 def refresh():
  with lock:
   run=current()
   if not run:return jsonify(error='예매 세션이 없습니다.'),409
   tick(run)
   if run['phase'] not in ('captcha','seats'):return jsonify(error='인증 단계가 아닙니다.'),409
   challenge(run);log(run,'captcha_refresh');save(run)
   return jsonify(ok=True,captcha_id=run['captcha_id'])
 @bp.post('/api/practice/captcha/shown')
 def captcha_shown():
  with lock:
   run=current();data=request.get_json(silent=True) or {}
   if not run or run['phase']!='captcha' or data.get('captcha_id')!=run.get('captcha_id'):
    return jsonify(error='현재 보안문자가 아닙니다.'),409
   if run.get('captcha_shown_at') is None:
    run['captcha_shown_at']=time.time();save(run)
   return jsonify(ok=True)
 @bp.post('/api/practice/captcha/verify')
 def verify():
  with lock:
   run=current()
   if not run:return jsonify(error='예매 세션이 없습니다.'),409
   tick(run)
   if run['phase'] not in ('captcha','seats'):return jsonify(error='인증 가능 시간이 끝났습니다.'),409
   data=request.get_json(silent=True) or {}
   answer=str(data.get('answer','')).strip().upper()
   if time.time()-run['captcha_created']>90 or not secrets.compare_digest(answer,run['answer']):
    run['captcha_attempts']+=1;log(run,'captcha_verify',outcome='captcha_wrong');save(run);return jsonify(error='문자가 일치하지 않습니다. 다시 입력하세요.'),422
   if run.get('captcha_shown_at') is not None and not run.get('captcha_duration_recorded') and data.get('captcha_id')==run.get('captcha_id'):
    elapsed=data.get('duration_ms')
    if isinstance(elapsed,(int,float)) and 1<=elapsed<=300000:
     span=data.get('input_duration_ms')
     span_valid=isinstance(span,(int,float)) and 1<=span<=elapsed
     detail={'duration_ms':span if span_valid else elapsed,'actor_kind':'human',
          'synthetic':False,'challenge_id':run['captcha_id'],'measurement_origin':'browser_input_span' if span_valid else 'browser_display_to_submit'}
     if span_valid:detail.update(input_duration_ms=span,display_to_submit_ms=elapsed)
     if data.get('input_event_offsets_ms') is not None and data.get('input_event_chars') is not None:
      detail.update(input_event_offsets_ms=data['input_event_offsets_ms'],input_event_chars=data['input_event_chars'])
     emit(run['owner'],'browser','captcha_duration',extra=detail)
     run['captcha_duration_recorded']=True
   run.update(phase='seats',verified_at=run.get('verified_at') or time.time());log(run,'captcha_verify');save(run)
   return jsonify(public(run))
 @bp.get('/api/practice/seats')
 def seats():
  with lock:
   run=current()
   if not run:return jsonify(error='예매 세션이 없습니다.'),409
   tick(run);area=request.args.get('area','A')
   if area not in AREAS:return jsonify(error='잘못된 구역입니다.'),400
   # Map can be previewed before verification, but selection stays server-gated.
   with db() as c:rows=c.execute('SELECT seat,status FROM practice_inventory WHERE run_id=? AND seat LIKE ?',(run['id'],area+'-%')).fetchall()
   return jsonify(area=area,rows=ROWS,cols=COLS,seats=[{'id':r['seat'],'available':r['status']=='available','selected':r['seat'] in run['selected']} for r in rows],remaining_seconds=public(run)['remaining_seconds'],phase=run['phase'])
 @bp.post('/api/practice/area')
 def area_view():
  with lock:
   run=current();area=(request.get_json(silent=True) or {}).get('area','')
   if not run or area not in AREAS:return jsonify(error='잘못된 구역입니다.'),400
   tick(run);log(run,'area_view',area=area);return jsonify(ok=True)
 @bp.post('/api/practice/select')
 def select():
  with lock:
   run=current()
   if not run:return jsonify(error='예매 세션이 없습니다.'),409
   tick(run)
   if not gate(run):return jsonify(error='대기열과 보안문자 인증을 완료하세요.'),403
   seat=str((request.get_json(silent=True) or {}).get('seat',''))
   selected=run['selected']
   if seat in selected:selected.remove(seat)
   else:
    with db() as c:r=c.execute('SELECT status FROM practice_inventory WHERE run_id=? AND seat=?',(run['id'],seat)).fetchone()
    if not r or r['status']!='available':log(run,'seat_select',seat,'seat_taken' if r else 'invalid_seat');return jsonify(error='이미 선택된 좌석입니다. 다른 좌석을 선택하세요.'),409
    if len(selected)>=2:return jsonify(error='최대 2석까지 선택할 수 있습니다.'),409
    selected.append(seat)
   log(run,'seat_select',seat);save(run);return jsonify(public(run))
 @bp.post('/api/practice/reserve')
 def reserve():
  with lock:
   run=current()
   if not run:return jsonify(error='예매 세션이 없습니다.'),409
   tick(run)
   if not gate(run):return jsonify(error='정상 예매 절차를 먼저 완료하세요.',decision=run['last_decision'],risk_score=run['last_risk_score']),403
   selected=run['selected']
   if not selected:return jsonify(error='좌석을 먼저 선택하세요.'),409
   if len(selected)==2:
    a,b=[x.split('-') for x in selected]
    if a[:2]!=b[:2] or abs(int(a[2])-int(b[2]))!=1:return jsonify(error='2석은 같은 열에서 나란히 선택하세요.'),409
   with db() as c:valid=all(c.execute("SELECT 1 FROM practice_inventory WHERE run_id=? AND seat=? AND status='available'",(run['id'],s)).fetchone() for s in selected)
   if not valid:
    for seat in selected:log(run,'reserve',seat,'seat_taken')
    run['selected']=[];save(run);return jsonify(error='다른 이용자가 먼저 선택했습니다. 좌석을 다시 선택하세요.'),409
   for seat in selected:
    # Reassert the selected seat for multi-seat workflow assessment.
    log(run,'seat_select',seat);assessment=log(run,'reserve',seat)
    run.update(last_decision=assessment['decision'],last_risk_score=assessment['risk_score'])
    if assessment['suspicious']:finish(run,'review');return jsonify(public(run))
   with db() as c:
    for seat in selected:c.execute("UPDATE practice_inventory SET status='reserved' WHERE run_id=? AND seat=?",(run['id'],seat))
   run['reservation_id']='T'+secrets.token_hex(5).upper();finish(run,'success');return jsonify(public(run))
 @bp.get('/api/practice/ranking')
 def ranking():
  with db() as c:runs=[json.loads(r[0]) for r in c.execute('SELECT payload FROM practice_runs')]
  done=sorted((r for r in runs if r.get('result')=='success'),key=lambda r:r['total_seconds'])[:20]
  return jsonify(items=[{'rank':i+1,'nickname':r['nickname'],'seconds':r['total_seconds'],'seats':len(r['selected'])} for i,r in enumerate(done)])
 app.register_blueprint(bp)
