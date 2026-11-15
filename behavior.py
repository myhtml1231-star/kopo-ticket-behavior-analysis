"""Scatter coordinates from correlated HTTP action logs, without simulated points."""
from collections import defaultdict, deque
from datetime import datetime, timezone
from statistics import median

WINDOW_SECONDS = 30
# Polls, observer controls, server inventory updates and result notifications are not actions.
ACTIONS = {'view', 'seat_select', 'reserve', 'reserve_received', 'area_view',
           'captcha_verify', 'captcha_refresh', 'captcha_bulk_input', 'queue_enter', 'ticket_cancel'}


def build_points(events, since=0, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    requests = {}
    for event in events:
        rid = event.get('http_request_id')
        if not rid or event.get('action') not in ACTIONS:
            continue
        try:
            at = float(event['http_started_at'])
        except (KeyError, TypeError, ValueError):
            continue
        if at > now or at < since - WINDOW_SECONDS:
            continue
        # Actor windows of one authenticated account share a single series.
        key = event.get('account_id') or event['session_id']
        identity = (key, rid)
        if identity not in requests:
            requests[identity] = {'id': rid, 'at': at, 'series': key, 'session_id': event['session_id'],
                                  'source': event.get('source'), 'action': event['action'],
                                  'seat': event.get('seat'), 'outcome': event.get('outcome'),
                                  'risk_score': 0, 'suspicious': False, 'blocked': False, 'rules': []}
        row = requests[identity]
        row.update(action=event['action'], seat=event.get('seat'), outcome=event.get('outcome'))
        row['risk_score'] = max(row['risk_score'], event.get('risk_score', 0))
        row['suspicious'] |= bool(event.get('suspicious'))
        row['rules'] = list(dict.fromkeys(row['rules'] + event.get('rules', [])))
    # An enforcement record can accompany a reserve request without being another request.
    for event in events:
        key = event.get('account_id') or event.get('session_id')
        row = requests.get((key, event.get('http_request_id')))
        if row is not None and event.get('enforcement') == 'ban':
            row['blocked'] = True
            row['rules'] = list(dict.fromkeys(row['rules'] + event.get('demo_rules', [])))
    queues = defaultdict(deque)
    points = []
    for row in sorted(requests.values(), key=lambda r: (r['at'], r['id'])):
        recent = queues[row['series']]
        while recent and recent[0] < row['at'] - WINDOW_SECONDS:
            recent.popleft()
        recent.append(row['at'])
        gaps = [b-a for a, b in zip(recent, list(recent)[1:])]
        interval = median(gaps) if gaps else None
        # First request has no measurable speed; it sits on the y axis.
        speed = 1 / interval if interval is not None and interval > 0 else 0
        row.update(speed=round(speed, 4), requests_30s=len(recent),
                   interval_ms=round(interval*1000, 3) if interval is not None else None,
                   decision='blocked' if row['blocked'] else 'review' if row['suspicious'] else
                            'watch' if row['risk_score'] else 'normal')
        if row['at'] >= since:
            points.append(row)
    return points
