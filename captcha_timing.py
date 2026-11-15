"""Only one measurement: CAPTCHA image shown to completion-button click."""
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

VERSION = 'captcha-pattern-v3'
FAST_MS = 800


def pattern_metrics(speed_cps, offsets=None, event_chars=None):
    """Bounded display features from actual CAPTCHA input events, never actor labels."""
    speed_score = 100 * -math.expm1(-float(speed_cps)/6)
    if not offsets or not event_chars or len(offsets) != len(event_chars):
        return {'speed_score': speed_score, 'pattern_score': None, 'timing_cv': None, 'bulk_ratio': None}
    gaps = [b-a for a, b in zip(offsets, offsets[1:])]
    if any(g < 0 for g in gaps):
        raise ValueError('input event times must be ordered')
    total = sum(max(0, n) for n in event_chars)
    bulk = sum(n for n in event_chars if n > 1)/total if total else 0
    avg = mean(gaps) if gaps else 0
    cv = pstdev(gaps)/avg if len(gaps) >= 3 and avg > 0 else None
    regularity = math.exp(-3*cv) if cv is not None else 0
    return {'speed_score': speed_score, 'pattern_score': 100*max(bulk, regularity),
            'timing_cv': cv, 'bulk_ratio': bulk}


def make_item(session_id, duration_ms, actor_kind='human', synthetic=False,
              challenge_id=None, measurement_origin='browser_display_to_submit',
              input_duration_ms=None, display_to_submit_ms=None,
              input_event_offsets_ms=None, input_event_chars=None, simulation_target_ms=None):
    duration_ms = round(float(duration_ms),3)
    if not math.isfinite(duration_ms) or not 1 <= duration_ms <= 300000:
        raise ValueError('invalid CAPTCHA duration')
    if actor_kind not in ('human', 'ai'):
        raise ValueError('invalid actor kind')
    item = {'event_id': str(uuid.uuid4()), '@timestamp': datetime.now(timezone.utc).isoformat(),
            'session_id': session_id, 'action': 'captcha_duration', 'detector_version': VERSION,
            'actor_kind': actor_kind, 'synthetic': bool(synthetic), 'duration_ms': duration_ms,
            'characters': 6, 'speed_cps': round(6000/duration_ms, 8),
            'challenge_id': challenge_id or uuid.uuid4().hex,
            'measurement_origin': measurement_origin}
    if input_duration_ms is not None:
        item['input_duration_ms'] = duration_ms
        item['input_duration_us'] = round(duration_ms*1000)
    if display_to_submit_ms is not None:
        item['display_to_submit_ms'] = round(float(display_to_submit_ms))
    if simulation_target_ms is not None:
        item.update(simulation_target_ms=float(simulation_target_ms),simulation_timing='variable_bulk_processing')
    if input_event_offsets_ms is not None and input_event_chars is not None:
        if not isinstance(input_event_offsets_ms,list) or not isinstance(input_event_chars,list) or not 1<=len(input_event_offsets_ms)<=64 or len(input_event_offsets_ms)!=len(input_event_chars):
            raise ValueError('invalid input events')
        offsets = [round(float(v),3) for v in input_event_offsets_ms]
        counts = [int(v) for v in input_event_chars]
        if any(not math.isfinite(v) or v<0 or v>300000 for v in offsets) or any(v<0 or v>32 for v in counts):
            raise ValueError('invalid input event value')
        pattern_metrics(item['speed_cps'], offsets, counts)
        item.update(input_event_offsets_ms=offsets, input_event_chars=counts)
    return item


def seed(db):
    dataset = json.loads((Path(__file__).parent/'data/captcha-timing-demo.json').read_text(encoding='utf-8'))
    with db() as c:
        for kind in ('human', 'ai'):
            for n, duration in enumerate(dataset[kind+'_duration_ms'], 1):
                ident = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{dataset["dataset_id"]}/{kind}/{n}'))
                if kind == 'human':
                    weights = dataset['human_interval_weights'][n-1]
                    offsets = [0]
                    for weight in weights:offsets.append(offsets[-1]+duration*weight/sum(weights))
                    counts = [1]*6
                else:
                    offsets, counts = [0], [6]
                item = make_item(f'virtual-{kind}-{n:02}', duration, kind, True,
                                 f'{dataset["dataset_id"]}-{kind}-{n:02}', 'synthetic_fixture', input_duration_ms=duration,
                                 input_event_offsets_ms=offsets, input_event_chars=counts)
                item['event_id'] = ident
                old = c.execute('SELECT payload FROM events WHERE id=?', (ident,)).fetchone()
                if old:
                    previous = json.loads(old[0])
                    item['@timestamp'] = previous['@timestamp']
                    if previous == item:
                        continue
                c.execute('INSERT INTO events(id,ts,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,published=0',
                          (ident, item['@timestamp'], json.dumps(item, ensure_ascii=False)))


def points(db):
    with db() as c:
        rows = c.execute("SELECT payload FROM events WHERE json_extract(payload,'$.action')='captcha_duration' ORDER BY rowid").fetchall()
    result = []
    for row in rows:
        item = json.loads(row[0])
        if item['measurement_origin'] not in ('synthetic_fixture','browser_input_span','scripted_browser_input_span'):
            continue
        span = item.get('input_duration_ms', item['duration_ms'])
        result.append({**item, 'id': item['event_id'], 'speed': item['speed_cps'],
                       'input_seconds': span/1000, 'inverse_seconds': 1000/span,
                       'seconds': span/1000, 'reference': item['measurement_origin']=='synthetic_fixture',
                       'fast': span < FAST_MS,
                       **pattern_metrics(item['speed_cps'], item.get('input_event_offsets_ms'), item.get('input_event_chars'))})
    return result
