"""Deterministic, isolated presentation scenarios; never a production AI classifier."""
import json
import secrets
import statistics
import time
import uuid

from flask import Blueprint, jsonify, render_template, request, session

SCENES = ('captcha',)


def init_ai_schema(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS ai_demo_runs(id TEXT PRIMARY KEY, owner TEXT, payload TEXT)')


def register_ai_demo(app, db, lock, emit):
    bp = Blueprint('ai_demo', __name__)
    init_ai_schema(db)

    def save(run):
        with db() as c:
            c.execute('INSERT OR REPLACE INTO ai_demo_runs VALUES(?,?,?)',
                      (run['id'], run['owner'], json.dumps(run, ensure_ascii=False)))

    def current():
        with db() as c:
            row = c.execute('SELECT payload FROM ai_demo_runs WHERE id=? AND owner=?',
                            (session.get('ai_demo_id'), session.get('ai_demo_owner'))).fetchone()
        return json.loads(row[0]) if row else None

    def public(run):
        return {k: v for k, v in run.items() if k not in ('owner', 'reserve_times')}

    def log(run, action, outcome='ok', seat=None, **details):
        entry = {'seq': len(run['history']) + 1, 'action': action, 'outcome': outcome,
                 'at': round(time.time(), 3), **details}
        event = emit(run['owner'], 'simulated_bot', action, seat, outcome,
                     scenario='ai_demo_' + run['scene'],
                     extra={'demo_run': run['id'], 'account_id': run['account_id'],
                            'synthetic_demo': True, 'demo_policy': 'presentation-v1', **details})
        entry['event_id'] = event['event_id']
        run['history'].append(entry)
        return entry

    def ban(run, code, title, evidence):
        if run['banned']:
            return
        run.update(banned=True, phase='banned', ban={'code': code, 'title': title, 'evidence': evidence})
        log(run, 'ai_demo_ban', 'demo_ban', enforcement='ban', ban_code=code,
            demo_rules=evidence, ban_title=title)

    def response(run, status=200, **extra):
        save(run)
        return jsonify(run=public(run), **extra), status

    @bp.get('/practice/ai')
    def page():
        return render_template('practice.html')

    @bp.post('/api/ai-demo/start')
    def start():
        data = request.get_json(silent=True) or {}
        scene = data.get('scene', 'captcha')
        if scene not in SCENES:
            return jsonify(error='올바르지 않은 예매 방식입니다.'), 400
        with lock:
            ident = uuid.uuid4().hex
            with db() as c:
                ordinal = c.execute('SELECT count(*) FROM ai_demo_runs').fetchone()[0]
            position = ordinal % 40
            step = position if position <= 20 else 40-position
            run = {'id': ident, 'owner': 'ai-demo-' + secrets.token_hex(12),
                   'account_id': 'AI-' + ident[:6].upper(), 'scene': scene, 'phase': 'ready',
                   'started_at': time.time(), 'banned': False, 'ban': None, 'history': [],
                   'challenge': 'KRMXWA' if scene == 'captcha' else None,
                   'scanned': [], 'attempts': [], 'reserve_times': [], 'offered': None,
                   'picked': None, 'windows': [], 'parallel_requests': [], 'interval_cv': None,
                   'input_target_ms':220+step*10}
            session['ai_demo_id'] = ident
            session['ai_demo_owner'] = run['owner']
            log(run, 'view', demonstration=scene)
            return response(run)

    @bp.get('/api/ai-demo/state')
    def state():
        with lock:
            run = current()
            return jsonify(run=public(run) if run else None)

    @bp.post('/api/ai-demo/action')
    def action():
        data = request.get_json(silent=True) or {}
        with lock:
            run = current()
            if not run:
                return jsonify(error='예매를 먼저 시작하세요.'), 409
            if data.get('run_id') != run['id']:
                return jsonify(error='이전 예매의 요청입니다.'), 409
            if run['banned']:
                return response(run, 403, error='차단된 계정입니다.')
            action = data.get('action')
            scene = run['scene']
            if scene == 'captcha' and action == 'captcha_shown':
                run.setdefault('captcha_shown_at', time.time())
                return response(run)
            if scene == 'captcha' and action == 'captcha_complete':
                elapsed = data.get('duration_ms')
                if 'captcha_shown_at' not in run or not isinstance(elapsed, (int, float)) or not 1 <= elapsed <= 300000:
                    return jsonify(error='보안문자 표시 시점과 완료 시간이 필요합니다.'), 400
                if not run.get('captcha_duration_recorded'):
                    span = data.get('input_duration_ms')
                    span_valid = isinstance(span, (int, float)) and 1 <= span <= elapsed
                    emit(run['owner'], 'simulated_bot', 'captcha_duration', extra={
                        'duration_ms': span if span_valid else elapsed, 'actor_kind': 'ai', 'synthetic': True,
                        'challenge_id': run['id'],
                        **({'input_duration_ms': span, 'display_to_submit_ms': elapsed} if span_valid else {}),
                        **({'simulation_target_ms':run['input_target_ms']} if span_valid and data.get('simulation_timing')=='variable_bulk_processing' else {}),
                        **({'input_event_offsets_ms':data['input_event_offsets_ms'],'input_event_chars':data['input_event_chars']}
                           if data.get('input_event_offsets_ms') is not None and data.get('input_event_chars') is not None else {}),
                        'measurement_origin': 'scripted_browser_input_span' if span_valid else 'scripted_browser_display_to_submit'})
                    run['captcha_duration_recorded'] = True
                    run['duration_ms'] = round(elapsed)
                    if span_valid:run['input_duration_ms'] = round(span,3)
                    run['phase'] = 'completed'
                return response(run)
            if scene == 'captcha' and action == 'bulk_input':
                if (data.get('input_type') != 'insertFromPaste' or data.get('input_events') != 1
                        or data.get('key_events') != 0 or data.get('characters') != 6):
                    return jsonify(error='입력 정보가 일치하지 않습니다.'), 400
                elapsed = round((time.time() - run['started_at']) * 1000)
                log(run, 'captcha_bulk_input', 'demo_signal', input_type='insertFromPaste',
                    input_events=1, key_events=0, characters=6, elapsed_ms=elapsed)
                ban(run, 'bulk_captcha_input', '보안문자 일괄 입력 감지',
                    ['문자 6개를 한 번에 입력', '입력 이벤트 1회 · 키 입력 이벤트 0회',
                     '발표용 일괄 입력 차단 규칙 적용'])
                return response(run, 403)
            return jsonify(error='현재 단계에서 허용되지 않은 동작입니다.'), 400

    app.register_blueprint(bp)
