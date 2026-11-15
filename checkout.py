import json
import secrets
import time
import uuid
from flask import Blueprint,jsonify,render_template,request,session
from interaction_metrics import payment_metrics,fixtures,PAYMENT_VERSION

def register_checkout(app,db,lock,emit,health):
    with db() as c:c.execute('CREATE TABLE IF NOT EXISTS checkout_runs(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
    bp=Blueprint('checkout',__name__)
    def current():
        with db() as c:row=c.execute('SELECT payload FROM checkout_runs WHERE id=? AND owner=?',(session.get('checkout_run'),session.get('checkout_owner'))).fetchone()
        return json.loads(row[0]) if row else None
    def save(run):
        with db() as c:c.execute('INSERT OR REPLACE INTO checkout_runs VALUES(?,?,?)',(run['id'],run['owner'],json.dumps(run)))
    def public(run):return {'run_id':run['id'],'actor_kind':run['actor_kind'],'seat':run['seat'],'completed':run.get('completed',False),'result':run.get('result')}
    @bp.get('/practice/checkout')
    def page():return render_template('checkout.html')
    @bp.post('/api/checkout/start')
    def start():
        data=request.get_json(silent=True) or {};kind=data.get('actor_kind','human');seat='A-1-6'
        with lock:
            if data.get('from_retry'):
                with db() as c:row=c.execute('SELECT payload FROM retry_runs WHERE id=? AND owner=?',(session.get('retry_run'),session.get('retry_owner'))).fetchone()
                previous=json.loads(row[0]) if row else None
                if not previous or previous['result']!='success':return jsonify(error='좌석 확보 후 결제할 수 있습니다.'),409
                kind=previous['actor_kind'];seat=previous['selected'][0]
            if kind not in ('human','ai'):return jsonify(error='예매 방식을 선택하세요.'),400
            run={'id':uuid.uuid4().hex,'owner':secrets.token_urlsafe(24),'actor_kind':kind,'seat':seat,'created':time.time()}
            save(run);session['checkout_run']=run['id'];session['checkout_owner']=run['owner']
        return jsonify(public(run))
    @bp.post('/api/checkout/complete')
    def complete():
        with lock:
            run=current()
            if not run:return jsonify(error='결제 화면을 먼저 여세요.'),409
            if run.get('completed'):return jsonify(**public(run),replayed=True)
            try:measured=payment_metrics(request.get_json(silent=True) or {},(time.time()-run['created'])*1000)
            except (ValueError,TypeError,KeyError,OverflowError) as e:return jsonify(error=str(e)),400
            # No field values are accepted or stored, including in the run payload.
            for field in measured['field_metrics']:
                emit('checkout-'+run['id'],'simulated_bot' if run['actor_kind']=='ai' else 'browser','checkout_pattern',run['seat'],'complete',
                     scenario='checkout',extra={**field,'run_id':run['id'],'actor_kind':run['actor_kind'],
                     'synthetic':run['actor_kind']=='ai','measurement_origin':'scripted_browser' if run['actor_kind']=='ai' else 'browser_input'})
            run.update(completed=True,result={k:measured[k] for k in ('verdict','duration_ms','fill_duration_ms','speed_cps','bulk_ratio','risk_score')});save(run)
            return jsonify(public(run))
    @bp.get('/api/checkout/behavior')
    def behavior():
        with db() as c:rows=c.execute("SELECT payload FROM events WHERE json_extract(payload,'$.action')='checkout_pattern' AND json_extract(payload,'$.detector_version')=? ORDER BY rowid DESC LIMIT 500",(PAYMENT_VERSION,)).fetchall()
        points=[dict(e,id=e['event_id']) for e in (json.loads(r[0]) for r in reversed(rows))]
        with db() as c:runs=c.execute("SELECT payload FROM checkout_runs WHERE json_extract(payload,'$.completed')=1 ORDER BY rowid DESC LIMIT 50").fetchall()
        summaries={}
        for row in runs:
            run=json.loads(row[0])
            if run['actor_kind'] not in summaries and 'fill_duration_ms' in run['result']:
                summaries[run['actor_kind']]={**run['result'],'run_id':run['id']}
        return jsonify(points=fixtures('payment')+points,summaries=summaries,**health())
    app.register_blueprint(bp)
