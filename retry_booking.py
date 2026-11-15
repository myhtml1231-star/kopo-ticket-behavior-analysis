"""Scenario 2: real seat-selection requests, five declared lab failures, then success."""
import json
import math
import random
import secrets
import time
import uuid
from statistics import mean, pstdev

from flask import Blueprint, jsonify, render_template, request, session
from interaction_metrics import mouse_metrics,fixtures,MOUSE_VERSION

VERSION = 'booking-retry-v2'
FAILURES = 5
SALES_SECONDS = 20
AI_CYCLE_MS = 400
SPEED_SCALE = 2.0


def init_schema(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS retry_runs(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS retry_inventory(run_id TEXT,seat TEXT,status TEXT,PRIMARY KEY(run_id,seat))')
        if 'sellout_rank' not in {r[1] for r in c.execute('PRAGMA table_info(retry_inventory)')}:
            c.execute('ALTER TABLE retry_inventory ADD COLUMN sellout_rank INTEGER')


def metrics(attempts):
    gaps = [(b['at']-a['at'])*1000 for a,b in zip(attempts,attempts[1:])]
    latencies = [a['selection_to_submit_ms'] for a in attempts]
    average = mean(gaps) if gaps else None
    gap_std = pstdev(gaps) if len(gaps)>=2 else None
    cadence_cv = gap_std/average if gap_std is not None and average>0 else None
    latency_avg = mean(latencies) if latencies else None
    latency_std = pstdev(latencies) if len(latencies)>=2 else None
    latency_cv = latency_std/latency_avg if latency_std is not None and latency_avg>0 else None
    ready = len(attempts)>=3 and cadence_cv is not None and latency_cv is not None
    rate = 1000/average if average is not None and average>0 else None
    speed = 100*-math.expm1(-rate/SPEED_SCALE) if rate is not None else None
    consistency = 100*math.exp(-4*max(cadence_cv,latency_cv)) if ready else None
    score = .4*speed+.6*consistency if ready else None
    r = lambda x:round(x,5) if x is not None else None
    return {'sample_ready':ready, 'attempt_count':len(attempts),
            'last_interval_ms':r(gaps[-1] if gaps else None), 'avg_interval_ms':r(average),
            'interval_std_ms':r(gap_std), 'cadence_cv':r(cadence_cv),
            'selection_avg_ms':r(latency_avg), 'selection_std_ms':r(latency_std),
            'selection_cv':r(latency_cv), 'attempts_per_second':r(rate),
            'speed_index':r(speed), 'consistency_index':r(consistency), 'risk_score':r(score)}


def register_retry(app, db, lock, emit, health):
    init_schema(db)
    bp=Blueprint('retry_booking',__name__)

    def save(run):
        with db() as c:
            c.execute('INSERT OR REPLACE INTO retry_runs VALUES(?,?,?)',(run['id'],run['owner'],json.dumps(run,ensure_ascii=False)))

    def current():
        with db() as c:
            row=c.execute('SELECT payload FROM retry_runs WHERE id=? AND owner=?',
                          (session.get('retry_run'),session.get('retry_owner'))).fetchone()
        return json.loads(row[0]) if row else None

    def tick(run):
        now=time.time();deadline=run.get('closes_at',run['created']+SALES_SECONDS)
        fraction=max(0,min(1,(now-run['created'])/(deadline-run['created'])))
        target=int(3600*fraction);closed=now>=deadline
        with db() as c:
            c.execute("UPDATE retry_inventory SET status='taken' WHERE run_id=? AND status='available' AND sellout_rank<?",
                      (run['id'],target))
        if closed and not run['result']:
            run.update(result='sold_out',selected=[],selection_token=None,selected_at=None,finished_at=deadline)
            save(run)
        return closed

    def public(run):
        closed=tick(run);now=time.time();elapsed=max(0,run.get('finished_at',now)-run['created'])
        with db() as c:
            available=c.execute("SELECT count(*) FROM retry_inventory WHERE run_id=? AND status='available'",(run['id'],)).fetchone()[0]
        return {'run_id':run['id'],'phase':'result' if run['result'] and closed else 'seats',
                'actor_kind':run['actor_kind'],'nickname':run['nickname'],'date':'2026-02-08','time':'19:00',
                'verified':True,'selected':run['selected'],'selection_token':run.get('selection_token'),
                'result':run['result'],'reservation_id':run.get('reservation_id'),
                'remaining_seconds':max(0,run.get('closes_at',run['created']+SALES_SECONDS)-now),
                'duration':run.get('closes_at',run['created']+SALES_SECONDS)-run['created'],'sales_closed':closed,'available_seats':available,'total_seats':3600,
                'segments':{'좌석':round(elapsed,3)},
                'total_seconds':round(elapsed,3),'attempts':[{k:v for k,v in a.items() if k!='token'} for a in run['attempts']],
                'metrics':metrics(run['attempts']),'failures_required':FAILURES,'ai_cycle_ms':AI_CYCLE_MS,
                'mouse_metrics':run.get('mouse_metrics'),
                'last_outcome':run['attempts'][-1]['outcome'] if run['attempts'] else None}

    @bp.get('/practice/retry')
    def page():
        return render_template('practice.html',retry_context=True)

    @bp.post('/api/retry/start')
    def start():
        data=request.get_json(silent=True) or {}
        kind=data.get('actor_kind','human')
        if kind not in ('human','ai'):return jsonify(error='예매 방식을 선택하세요.'),400
        rid,owner=uuid.uuid4().hex,secrets.token_urlsafe(24)
        run={'id':rid,'owner':owner,'actor_kind':kind,'nickname':str(data.get('nickname') or ('AI' if kind=='ai' else '사람'))[:20],
             'created':time.time(),'selected':[],'selection_token':None,'selected_at':None,'attempts':[],'result':None}
        run['closes_at']=run['created']+SALES_SECONDS
        # One shuffled inventory across all areas and rows, shared by both modes.
        order=[f'{a}-{row}-{n}' for a in 'ABCDEFGH' for row in range(1,16) for n in range(1,31)]
        random.Random(rid).shuffle(order)
        with lock:
            save(run)
            with db() as c:
                c.executemany('INSERT INTO retry_inventory(run_id,seat,status,sellout_rank) VALUES(?,?,?,?)',
                    [(rid,seat,'available',rank) for rank,seat in enumerate(order)])
            session['retry_run'],session['retry_owner']=rid,owner
        return jsonify(public(run))

    @bp.get('/api/retry/state')
    def state():
        with lock:
            run=current()
            return jsonify(public(run) if run else {'phase':'intro'})

    @bp.get('/api/retry/seats')
    def seats():
        with lock:
            run=current();area=request.args.get('area','A')
            if not run:return jsonify(error='예매를 시작하세요.'),409
            if area not in 'ABCDEFGH' or len(area)!=1:return jsonify(error='잘못된 구역입니다.'),400
            tick(run)
            with db() as c:
                rows=c.execute('SELECT seat,status FROM retry_inventory WHERE run_id=? AND seat LIKE ?',
                               (run['id'],area+'-%')).fetchall()
            return jsonify(area=area,rows=15,cols=30,phase='result' if run['result'] and time.time()>=run['closes_at'] else 'seats',
                remaining_seconds=max(0,run['closes_at']-time.time()),
                seats=[{'id':r['seat'],'available':r['status']=='available','selected':r['seat'] in run['selected']} for r in rows])

    @bp.post('/api/retry/area')
    def area():
        if not current():return jsonify(error='예매를 시작하세요.'),409
        return jsonify(ok=True)

    @bp.post('/api/retry/select')
    def select():
        with lock:
            data=request.get_json(silent=True) or {};run=current();seat=str(data.get('seat',''))
            if not run:return jsonify(error='예매를 시작하세요.'),409
            if tick(run):return jsonify(**public(run),error='예매 시간이 지나 마감되었습니다.'),410
            if run['result']:return jsonify(error='이미 예매가 완료되었습니다.'),409
            if seat in run['selected']:
                run.update(selected=[],selection_token=None,selected_at=None)
            else:
                with db() as c:
                    row=c.execute("SELECT status FROM retry_inventory WHERE run_id=? AND seat=?",(run['id'],seat)).fetchone()
                if not row:return jsonify(error='선택할 수 없는 좌석입니다.'),409
                if row['status']!='available':return jsonify(**public(run),error='선택한 좌석이 이미 판매되었습니다.',error_code='seat_sold_out',conflict_seat=seat),409
                run.update(selected=[seat],selection_token=secrets.token_urlsafe(24),selected_at=time.time())
                if data.get('movement'):
                    try:measured=mouse_metrics(data['movement'])
                    except (ValueError,TypeError,KeyError,OverflowError):measured=None
                    if measured:
                        run['mouse_samples']=run.get('mouse_samples',0)+1
                        run['mouse_metrics']=measured
                        emit('mouse-'+run['id'],'simulated_bot' if run['actor_kind']=='ai' else 'browser','mouse_path',seat,'selected',
                             scenario='mouse_selection',extra={**measured,'run_id':run['id'],'sample_no':run['mouse_samples'],
                             'actor_kind':run['actor_kind'],'synthetic':run['actor_kind']=='ai',
                             'measurement_origin':'scripted_browser' if run['actor_kind']=='ai' else 'browser_pointer'})
            save(run)
            return jsonify(public(run))

    @bp.post('/api/retry/reserve')
    def reserve():
        with lock:
            run=current();data=request.get_json(silent=True) or {}
            if not run:return jsonify(error='예매를 시작하세요.'),409
            closed=tick(run)
            token=data.get('selection_token')
            previous=next((a for a in run['attempts'] if token and a['token']==token),None)
            if previous:
                body=public(run);body['replayed']=True
                if previous['outcome']!='success':body.update(error='선택한 좌석이 이미 판매되었습니다.',error_code='seat_sold_out',conflict_seat=previous['seat'])
                return jsonify(body),200 if previous['outcome']=='success' else 409
            if closed:return jsonify(**public(run),error='예매 시간이 지나 마감되었습니다.'),410
            if run['result'] or not run['selected'] or not token or token!=run['selection_token']:
                return jsonify(error='새 좌석을 선택한 뒤 예매하세요.'),409
            seat=run['selected'][0]
            with db() as c:
                available=c.execute("SELECT 1 FROM retry_inventory WHERE run_id=? AND seat=? AND status='available'",(run['id'],seat)).fetchone()
            if not available:
                run.update(selected=[],selection_token=None,selected_at=None);save(run)
                return jsonify(**public(run),error='선택한 좌석이 이미 판매되었습니다.',error_code='seat_sold_out',conflict_seat=seat),409
            now=time.time();n=len(run['attempts'])+1;forced=n<=FAILURES
            if now>=run['closes_at']:
                tick(run);return jsonify(**public(run),error='예매 시간이 지나 마감되었습니다.'),410
            attempt={'attempt_id':str(uuid.uuid4()),'attempt_no':n,'seat':seat,'at':now,
                     'selection_to_submit_ms':round(max(0,now-run['selected_at'])*1000,3),
                     'outcome':'scenario_failure' if forced else 'success','forced_failure':forced,'token':token}
            run['attempts'].append(attempt)
            measured=metrics(run['attempts'])
            with db() as c:
                c.execute('UPDATE retry_inventory SET status=? WHERE run_id=? AND seat=?',
                          ('taken' if forced else 'reserved',run['id'],seat))
            if forced:run.update(selected=[],selection_token=None,selected_at=None)
            else:run.update(result='success',reservation_id='R'+secrets.token_hex(5).upper(),finished_at=now)
            save(run)
            body=public(run)
            if forced:body.update(error='선택한 좌석이 이미 판매되었습니다. 다른 좌석을 선택해주세요.',error_code='seat_sold_out',conflict_seat=seat)
            return jsonify(body),409 if forced else 200

    @bp.get('/api/retry/behavior')
    def behavior():
        with lock:
            run=current();market=None
            if run:
                snapshot=public(run)
                market={k:snapshot[k] for k in ['run_id','remaining_seconds','sales_closed','available_seats','total_seats']}
        with db() as c:
            rows=c.execute("SELECT payload FROM events WHERE json_extract(payload,'$.action')='mouse_path' AND json_extract(payload,'$.detector_version')=? ORDER BY rowid DESC LIMIT 500",(MOUSE_VERSION,)).fetchall()
        points=[dict(e,id=e['event_id']) for e in (json.loads(r[0]) for r in reversed(rows))]
        return jsonify(mode='mouse_selection',market=market,points=fixtures('mouse')+points,**health())

    app.register_blueprint(bp)
