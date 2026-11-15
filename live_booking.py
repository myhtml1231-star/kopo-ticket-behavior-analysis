"""Shared booking inventory used by full booking pages and independent HTTP clients."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import statistics
import subprocess
import threading
import time
import uuid

import requests
from flask import Blueprint, jsonify, render_template, request, session


def init_live_schema(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS live_rooms(id TEXT PRIMARY KEY,owner TEXT,payload TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS live_actors(room TEXT,id TEXT,token_hash TEXT,account TEXT,role TEXT,payload TEXT,PRIMARY KEY(room,id))')
        c.execute('CREATE TABLE IF NOT EXISTS live_inventory(room TEXT,seat TEXT,status TEXT,account TEXT,actor TEXT,version INTEGER,PRIMARY KEY(room,seat))')
        c.execute('CREATE TABLE IF NOT EXISTS live_requests(id TEXT PRIMARY KEY,room TEXT,account TEXT,actor TEXT,seat TEXT,started REAL,finished REAL,outcome TEXT)')


class BookingService:
    def __init__(self, db, lock, emit):
        self.db, self.lock, self.emit = db, lock, emit
        self.private = {}
        init_live_schema(db)

    def room(self, rid):
        with self.db() as c:
            row = c.execute('SELECT payload FROM live_rooms WHERE id=?', (rid,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, room):
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO live_rooms VALUES(?,?,?)', (room['id'], room['owner'], json.dumps(room, ensure_ascii=False)))

    def actor(self, rid, aid):
        with self.db() as c:
            row = c.execute('SELECT * FROM live_actors WHERE room=? AND id=?', (rid, aid)).fetchone()
        return dict(row) if row else None

    def actor_state(self, actor):
        return json.loads(actor['payload'])

    def save_actor(self, actor, state):
        with self.db() as c:
            c.execute('UPDATE live_actors SET payload=? WHERE room=? AND id=?', (json.dumps(state), actor['room'], actor['id']))

    def log(self, room, actor, action, outcome='ok', seat=None, **extra):
        item = self.emit('live-' + room['id'] + '-' + actor['id'],
                         'simulated_bot' if actor['role'] == 'ai' else 'simulated_normal' if actor['role'] == 'competitor' else 'browser',
                         action, seat, outcome, scenario='live_' + room['scene'],
                         extra={'local_lab': True, 'live_room': room['id'], 'account_id': actor['account'],
                                'window_id': actor['id'], **extra})
        return item['event_id']

    def create(self, scene, owner, competitor=True):
        rid = uuid.uuid4().hex
        room = {'id': rid, 'owner': owner, 'scene': scene, 'account': 'AI-' + rid[:6].upper(),
                'phase': 'scanning' if scene == 'seats' else 'waiting', 'created': time.time(),
                'competitor_enabled': bool(competitor), 'market_started': None, 'releases': [],
                'attempts': [], 'banned': False, 'ban': None, 'fire_at': None, 'launched': False}
        actors = [('1', room['account'], 'ai')] if scene == 'seats' else [(str(i), room['account'], 'ai') for i in range(1, 6)]
        actors += [('competitor', 'CROWD-' + rid[:6], 'competitor'), ('controller', 'CONTROL-' + rid[:6], 'observer')]
        tokens = {}
        with self.lock:
            self.save(room)
            with self.db() as c:
                for aid, account, role in actors:
                    token = secrets.token_urlsafe(32)
                    tokens[aid] = token
                    c.execute('INSERT INTO live_actors VALUES(?,?,?,?,?,?)', (rid, aid, self.digest(token), account, role,
                              json.dumps({'selected': [], 'ready': False, 'scanned': [], 'booked': [], 'joined': False})))
                for area in 'ABCDEFGH':
                    for row in range(1, 16):
                        for n in range(1, 31):
                            c.execute('INSERT INTO live_inventory VALUES(?,?,?,?,?,?)', (rid, f'{area}-{row}-{n}',
                                      'reserved' if scene == 'seats' else 'available',
                                      'CROWD-' + rid[:6] if scene == 'seats' else None,
                                      'competitor' if scene == 'seats' else None, 1))
            self.private[rid] = tokens
        return room, tokens

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, rid, aid, token):
        actor = self.actor(rid, aid)
        return actor if actor and token and secrets.compare_digest(actor['token_hash'], self.digest(token)) else None

    def snapshot(self, room, actor):
        actor = self.actor(room['id'], actor['id'])
        state = self.actor_state(actor)
        with self.db() as c:
            counts = {a: 0 for a in 'ABCDEFGH'}
            for row in c.execute("SELECT substr(seat,1,1),count(*) FROM live_inventory WHERE room=? AND status='available' GROUP BY substr(seat,1,1)", (room['id'],)):
                counts[row[0]] = row[1]
            ready = c.execute("SELECT count(*) FROM live_actors WHERE room=? AND role='ai' AND json_extract(payload,'$.ready')=1", (room['id'],)).fetchone()[0]
            pending = c.execute('SELECT count(*) FROM live_requests WHERE room=? AND finished IS NULL', (room['id'],)).fetchone()[0]
        banned = room['banned'] and actor['account'] == room['account']
        return {'run_id': room['id'], 'phase': 'banned' if banned else 'result' if state['booked'] else 'seats',
                'nickname': actor['account'], 'date': '2026-02-08', 'time': '19:00', 'verified': True,
                'selected': state['selected'], 'remaining_seconds': max(0, 300 - (time.time() - room['created'])),
                'result': 'success' if state['booked'] else None, 'reservation_id': state.get('reservation_id'),
                'segments': {'반응': 0, '대기열': 0, '보안문자': 0, '좌석': round(time.time() - room['created'], 2)},
                'total_seconds': round(time.time() - room['created'], 2), 'duration': 300,
                'room_phase': room['phase'], 'scene': room['scene'], 'account_id': actor['account'], 'actor_id': actor['id'],
                'role': actor['role'], 'server_now': time.time(), 'area_counts': counts, 'attempts': room['attempts'],
                'releases': room['releases'], 'banned': banned, 'ban': room['ban'] if banned else None,
                'competitor_enabled': room['competitor_enabled'], 'ready_windows': ready, 'pending_requests': pending,
                'fire_at': room['fire_at'], 'scanned': state['scanned'], 'booked': state['booked']}

    def ban(self, room, actor, code, title, evidence):
        if room['banned']:
            return
        room.update(banned=True, phase='banned', ban={'code': code, 'title': title, 'evidence': evidence})
        self.log(room, actor, 'account_ban', 'blocked', enforcement='ban', ban_code=code, demo_rules=evidence)
        self.save(room)

    def dashboard(self, room):
        now = time.time()
        with self.db() as c:
            actors = [dict(r) for r in c.execute("SELECT id,payload FROM live_actors WHERE room=? AND role='ai' ORDER BY id", (room['id'],))]
            rows = [dict(r) for r in c.execute('SELECT id,actor,seat,started,finished,outcome FROM live_requests WHERE room=? ORDER BY started', (room['id'],))]
        clients = [{'id': a['id'], **json.loads(a['payload'])} for a in actors]
        intervals = [(r['started'], r['finished'] if r['finished'] is not None else now) for r in rows]
        sweep = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals])
        active = peak = 0
        for _, delta in sweep:
            active += delta
            peak = max(peak, active)
        latest = {}
        for row in rows:
            latest[row['actor']] = row
        five = [latest[str(i)] for i in range(1, 6) if str(i) in latest]
        common_start = max((r['started'] for r in five), default=None)
        common_end = min((r['finished'] if r['finished'] is not None else now for r in five), default=None)
        overlap = max(0, common_end - common_start) if len(five) == 5 else 0
        return {'room': room['id'], 'account': room['account'], 'phase': room['phase'], 'server_now': now,
                'fire_at': room['fire_at'], 'banned': room['banned'], 'ban': room['ban'], 'clients': clients,
                'requests': rows, 'ready': sum(a['ready'] for a in clients),
                'pending': sum(r['finished'] is None for r in rows), 'peak_inflight': peak,
                'overlap_ms': round(overlap * 1000),
                'common_start': common_start if overlap else None, 'common_end': common_end if overlap else None}

    def area(self, room, actor, area):
        if area not in 'ABCDEFGH' or len(area) != 1:
            return {'error': '잘못된 구역입니다.'}, 400
        state = self.actor_state(actor)
        if area not in state['scanned']:
            state['scanned'].append(area)
        self.save_actor(actor, state)
        self.log(room, actor, 'area_view', area=area)
        return self.snapshot(room, actor), 200

    def seats(self, room, actor, area):
        if area not in 'ABCDEFGH' or len(area) != 1:
            return {'error': '잘못된 구역입니다.'}, 400
        state = self.actor_state(actor)
        with self.db() as c:
            rows = c.execute('SELECT seat,status,version,actor FROM live_inventory WHERE room=? AND seat LIKE ?', (room['id'], area + '-%')).fetchall()
        return {'area': area, 'rows': 15, 'cols': 30, 'phase': 'banned' if room['banned'] else 'seats',
                'remaining_seconds': 300, 'seats': [{'id': r['seat'], 'available': r['status'] == 'available',
                'selected': r['seat'] in state['selected'], 'version': r['version']} for r in rows]}, 200

    def select(self, room, actor, seat):
        if room['banned'] and actor['account'] == room['account']:
            return {**self.snapshot(room, actor), 'error': '계정이 차단되었습니다.'}, 403
        if actor['role'] == 'observer':
            return {'error': '관찰 창에서는 예매할 수 없습니다.'}, 403
        state = self.actor_state(actor)
        if seat in state['selected']:
            state['selected'].remove(seat)
        else:
            with self.db() as c:
                row = c.execute('SELECT status FROM live_inventory WHERE room=? AND seat=?', (room['id'], seat)).fetchone()
            if not row or row[0] != 'available':
                self.log(room, actor, 'seat_select', 'seat_taken', seat)
                return {**self.snapshot(room, actor), 'error': '이미 예매된 좌석입니다.'}, 409
            if len(state['selected']) >= 2:
                return {'error': '최대 2석까지 선택하세요.'}, 409
            state['selected'].append(seat)
        self.save_actor(actor, state)
        self.log(room, actor, 'seat_select', seat=seat)
        return self.snapshot(room, actor), 200

    def release(self, room, actor, seat):
        # Only the actual ticket owner may cancel. The bot does not choose the outcome.
        with self.db() as c:
            changed = c.execute("UPDATE live_inventory SET status='available',account=NULL,actor=NULL,version=version+1 WHERE room=? AND seat=? AND status='reserved' AND account=?",
                                (room['id'], seat, actor['account'])).rowcount
        if not changed:
            return {'error': '취소할 수 있는 본인 좌석이 아닙니다.'}, 409
        room['releases'].append({'seat': seat, 'at': time.time()})
        self.log(room, actor, 'ticket_cancel', seat=seat)
        self.save(room)
        return {'released': seat}, 200

    def reserve(self, rid, aid, delay=None):
        with self.lock:
            room, actor = self.room(rid), self.actor(rid, aid)
            state = self.actor_state(actor)
            if room['banned'] and actor['account'] == room['account']:
                return {**self.snapshot(room, actor), 'error': '계정이 차단되었습니다.'}, 403
            chosen = list(state['selected'])
            if not chosen or actor['role'] == 'observer':
                return {'error': '좌석을 먼저 선택하세요.'}, 409
            if len(chosen) == 2:
                a, b = [s.split('-') for s in chosen]
                if a[:2] != b[:2] or abs(int(a[2]) - int(b[2])) != 1:
                    return {'error': '2석은 같은 열에서 나란히 선택하세요.'}, 409
            ident, started = uuid.uuid4().hex, time.time()
            with self.db() as c:
                c.execute('INSERT INTO live_requests VALUES(?,?,?,?,?,?,NULL,?)', (ident, rid, actor['account'], aid, ','.join(chosen), started, 'pending'))
                pending = c.execute('SELECT count(DISTINCT actor) FROM live_requests WHERE room=? AND account=? AND finished IS NULL AND started>?',
                                    (rid, actor['account'], started - 10)).fetchone()[0]
            self.log(room, actor, 'reserve_received', seat=chosen[0], request_id=ident, inflight_requests=pending)
            if actor['account'] == room['account'] and pending >= 5:
                self.ban(room, actor, 'same_account_inflight', '동일 계정의 동시 예매 요청 감지',
                         [f'인증된 예매 창 {pending}개에서 요청 처리 중', '서버에서 아직 완료되지 않은 요청이 실제로 겹침', '계정 단위 차단 · 전체 창의 예매 중단'])
        # A real processing interval allows requests from separate clients to overlap.
        wait = (1.6 if room['scene'] == 'parallel' and actor['role'] == 'ai' else .03) if delay is None else delay
        if wait:
            time.sleep(wait)
        with self.lock:
            room, actor = self.room(rid), self.actor(rid, aid)
            state = self.actor_state(actor)
            blocked = room['banned'] and actor['account'] == room['account']
            with self.db() as c:
                rows = [c.execute('SELECT status,actor,version FROM live_inventory WHERE room=? AND seat=?', (rid, s)).fetchone() for s in chosen]
                available = all(r and r['status'] == 'available' for r in rows)
                outcome = 'account_blocked' if blocked else 'ok' if available else 'seat_taken'
                if outcome == 'ok':
                    for seat in chosen:
                        c.execute("UPDATE live_inventory SET status='reserved',account=?,actor=?,version=version+1 WHERE room=? AND seat=? AND status='available'",
                                  (actor['account'], aid, rid, seat))
                    state['booked'] += chosen
                    state['reservation_id'] = 'L' + secrets.token_hex(5).upper()
                c.execute('UPDATE live_requests SET finished=?,outcome=? WHERE id=?', (time.time(), outcome, ident))
            winner = next((r['actor'] for r in rows if r and r['status'] != 'available'), None)
            self.log(room, actor, 'reserve', outcome, chosen[0], request_id=ident, inventory_winner=winner, inflight_at_entry=pending)
            if actor['role'] == 'ai' and room['scene'] == 'seats':
                room['attempts'].append({'n': len(room['attempts']) + 1, 'seat': chosen[0], 'at': started, 'outcome': outcome,
                                         'winner': winner, 'request_id': ident})
                recent = room['attempts'][-5:]
                if len(recent) == 5 and all(a['outcome'] == 'seat_taken' for a in recent):
                    gaps = [b['at'] - a['at'] for a, b in zip(recent, recent[1:])]
                    avg = statistics.mean(gaps)
                    cv = statistics.pstdev(gaps) / avg if avg else 1
                    if 1 <= avg <= 20 and cv <= .25:
                        self.ban(room, actor, 'periodic_inventory_conflicts', '일정 간격의 반복 예매 실패 감지',
                                 ['공유 재고의 실제 선점 충돌 5회', f'평균 {avg:.2f}초 간격 · 변동계수 {cv:.3f}', '각 요청의 선점 클라이언트와 요청 ID 기록'])
            if outcome != 'ok':
                state['selected'] = []
            elif actor['role'] == 'competitor':
                state['selected'] = []
            self.save_actor(actor, state)
            self.save(room)
            snap = self.snapshot(room, actor)
            snap.update(request_id=ident, outcome=outcome, inventory_winner=winner)
            if outcome != 'ok':
                snap['error'] = '계정이 차단되었습니다.' if outcome == 'account_blocked' else '다른 이용자가 먼저 예매한 좌석입니다.'
            return snap, 403 if blocked or snap['banned'] else 200 if outcome == 'ok' else 409

    def start_market(self, rid):
        tokens = self.private[rid]
        def market():
            with requests.Session() as http:
                http.trust_env = False
                headers = {'X-Live-Token': tokens['competitor']}
                base = f'http://127.0.0.1:5050/api/live/{rid}/competitor/'
                for _ in range(20):
                    began = time.monotonic()
                    room = self.room(rid)
                    if room['phase'] in ('banned', 'stopped'):
                        return
                    with self.db() as c:
                        candidates = [r[0] for r in c.execute("SELECT seat FROM live_inventory WHERE room=? AND account=? AND status='reserved'", (rid, 'CROWD-' + rid[:6]))]
                    if not candidates:
                        return
                    seat = secrets.choice(candidates)
                    try:
                        released = http.post(base + 'cancel', json={'seat': seat}, headers=headers, timeout=5)
                        if released.ok:
                            time.sleep(2)
                            room = self.room(rid)
                            if room['phase'] in ('banned', 'stopped'):
                                return
                            if room['competitor_enabled']:
                                picked = http.post(base + 'select', json={'seat': seat}, headers=headers, timeout=5)
                                if picked.ok:
                                    http.post(base + 'reserve', json={}, headers=headers, timeout=5)
                    except requests.RequestException:
                        return
                    time.sleep(max(0, 4.5 - (time.monotonic() - began)))
        threading.Thread(target=market, daemon=True).start()


def open_browser_windows(urls, width=1920, height=1080):
    candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('LOCALAPPDATA', '')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe']
    exe = next((p for p in candidates if p.is_file()), None)
    if exe is None:
        raise RuntimeError('Chrome 또는 Edge 설치를 찾을 수 없습니다.')
    tile_w, tile_h = max(500, width // 3), max(350, (height - 60) // 2)
    for i, url in enumerate(urls):
        x = i * tile_w if i < 3 else (i - 3) * tile_w + tile_w // 2
        y = 0 if i < 3 else tile_h
        subprocess.Popen([str(exe), '--new-window', f'--window-size={tile_w},{tile_h}', f'--window-position={x},{y}', url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return exe.name


def register_live_booking(app, db, lock, emit):
    service = BookingService(db, lock, emit)
    app.extensions['live_booking'] = service
    bp = Blueprint('live_booking', __name__)

    def owner(rid):
        room = service.room(rid)
        actor = service.authenticate(rid, 'controller', request.headers.get('X-Live-Token', ''))
        return room if room and (room['owner'] == session.get('live_owner') or actor) else None

    def actor_auth(rid, aid):
        return service.authenticate(rid, aid, request.headers.get('X-Live-Token', ''))

    def url(room, aid, token):
        return f'http://127.0.0.1:5050/practice/live/{room["id"]}/{aid}#access={token}'

    @bp.post('/api/live/start')
    def start():
        data = request.get_json(silent=True) or {}
        if data.get('scene') not in ('seats', 'parallel'):
            return jsonify(error='잘못된 시나리오입니다.'), 400
        session.setdefault('live_owner', secrets.token_urlsafe(24))
        room, tokens = service.create(data['scene'], session['live_owner'], data.get('competitor', True))
        if room['scene'] == 'parallel':
            target = f'http://127.0.0.1:5050/practice/multiview/{room["id"]}#access={tokens["controller"]}'
        else:
            target = url(room, '1', tokens['1'])
        return jsonify(room=room['id'], url=target)

    @bp.get('/practice/multiview/<rid>')
    def multiview(rid):
        room = service.room(rid)
        if not room or room['scene'] != 'parallel':
            return '동시 예매 회차를 찾을 수 없습니다.', 404
        return render_template('parallel.html', room_id=rid)

    @bp.get('/api/live/<rid>/dashboard')
    def dashboard(rid):
        with lock:
            room = owner(rid)
            if not room:
                return jsonify(error='관제 권한이 없습니다.'), 403
            return jsonify(service.dashboard(room))

    @bp.get('/api/live/<rid>/clients')
    def clients(rid):
        with lock:
            room = owner(rid)
            if not room:
                return jsonify(error='관제 권한이 없습니다.'), 403
            tokens = service.private.get(rid)
            if not tokens:
                return jsonify(error='서버가 재시작되었습니다. 새 회차를 시작하세요.'), 409
            return jsonify(items=[{'id': str(i), 'url': f'/practice/live/{rid}/{i}?embedded=1#access={tokens[str(i)]}'} for i in range(1, 6)])

    @bp.get('/practice/live/<rid>/<aid>')
    def page(rid, aid):
        if not service.actor(rid, aid):
            return '예매 창을 찾을 수 없습니다.', 404
        room = service.room(rid)
        return render_template('practice.html', live_context={'room': rid, 'actor': aid,
                               'controls': room['owner'] == session.get('live_owner'),
                               'embedded': request.args.get('embedded') == '1'})

    @bp.post('/api/live/<rid>/windows')
    def windows(rid):
        with lock:
            room = owner(rid)
            if not room or room['scene'] != 'parallel':
                return jsonify(error='권한이 없습니다.'), 403
            if room['launched']:
                return jsonify(opened=True, count=5)
            tokens = service.private.get(rid)
            if not tokens:
                return jsonify(error='서버가 재시작되었습니다. 새로 시작하세요.'), 409
            data = request.get_json(silent=True) or {}
            try:
                w, h = max(1000, min(7680, int(data.get('width', 1920)))), max(700, min(4320, int(data.get('height', 1080))))
                browser = open_browser_windows([url(room, str(i), tokens[str(i)]) for i in range(1, 6)], w, h)
            except (OSError, RuntimeError, ValueError) as exc:
                return jsonify(error=str(exc)), 503
            room['launched'] = True
            service.save(room)
            return jsonify(opened=True, count=5, browser=browser)

    @bp.post('/api/live/<rid>/control')
    def control(rid):
        with lock:
            room = owner(rid)
            if not room:
                return jsonify(error='권한이 없습니다.'), 403
            data = request.get_json(silent=True) or {}
            if data.get('action') == 'stop':
                room['phase'] = 'stopped'
            elif data.get('action') == 'competitor':
                room['competitor_enabled'] = bool(data.get('enabled'))
            elif data.get('action') == 'fire':
                snapshot = service.dashboard(room)
                if room['scene'] != 'parallel' or room['phase'] != 'waiting' or snapshot['ready'] != 5:
                    return jsonify(error='다섯 예매 화면이 모두 준비된 뒤 시작하세요.'), 409
                room.update(fire_at=time.time() + 3, phase='parallel_fire')
            else:
                return jsonify(error='잘못된 제어 요청입니다.'), 400
            service.save(room)
            return jsonify(ok=True)

    @bp.route('/api/live/<rid>/<aid>/<action>', methods=['GET', 'POST'])
    def action(rid, aid, action):
        actor = actor_auth(rid, aid)
        if not actor:
            return jsonify(error='예매 창 인증에 실패했습니다.'), 403
        data = request.get_json(silent=True) or {}
        if action == 'reserve' and request.method == 'POST':
            body, status = service.reserve(rid, aid)
            return jsonify(body), status
        with lock:
            room = service.room(rid)
            actor = service.actor(rid, aid)
            state = service.actor_state(actor)
            if action == 'state' and request.method == 'GET':
                if not state['joined']:
                    state['joined'] = True
                    service.save_actor(actor, state)
                    service.log(room, actor, 'view')
                return jsonify(service.snapshot(room, actor))
            if action == 'seats' and request.method == 'GET':
                result, code = service.seats(room, actor, request.args.get('area', 'A'))
            elif action == 'area' and request.method == 'POST':
                result, code = service.area(room, actor, str(data.get('area', '')))
            elif action == 'select' and request.method == 'POST':
                result, code = service.select(room, actor, str(data.get('seat', '')))
            elif action == 'cancel' and request.method == 'POST':
                result, code = service.release(room, actor, str(data.get('seat', '')))
            elif action == 'ready' and request.method == 'POST' and actor['role'] == 'ai':
                if room['scene'] == 'parallel' and not state['selected']:
                    return jsonify(error='이 예매 화면에서 좌석을 먼저 선택하세요.'), 409
                state['ready'] = True
                service.save_actor(actor, state)
                if room['scene'] == 'seats' and room['market_started'] is None:
                    room.update(market_started=time.time(), phase='running')
                    service.save(room)
                    if not app.config.get('TESTING'):
                        service.start_market(rid)
                result, code = service.snapshot(room, actor), 200
            else:
                return jsonify(error='허용되지 않은 요청입니다.'), 400
            return jsonify(result), code

    app.register_blueprint(bp)
