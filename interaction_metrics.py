"""Measured mouse paths and checkout timing; educational rules, not a trained model."""
import math
import random
from statistics import mean, pstdev

MOUSE_VERSION='mouse-path-v2'
PAYMENT_VERSION='checkout-fields-v2'
FIELDS=('name','phone','email','address')

def cv(values):
    average=mean(values) if values else 0
    return pstdev(values)/average if len(values)>1 and average>0 else 0

def clean_path(value):
    if not isinstance(value,list) or not 4<=len(value)<=2048:raise ValueError('마우스 이동 표본이 부족합니다.')
    points=[]
    for p in value:
        if not isinstance(p,dict):raise ValueError('잘못된 이동 표본입니다.')
        v={k:float(p[k]) for k in ('x','y','t')}
        if not all(math.isfinite(n) for n in v.values()) or not (-10000<=v['x']<=10000 and -10000<=v['y']<=10000):raise ValueError('잘못된 이동 좌표입니다.')
        if points and v['t']<=points[-1]['t']:raise ValueError('이동 시간이 순서대로 기록되지 않았습니다.')
        rounded={k:round(n,3) for k,n in v.items()}
        if points and rounded['t']<=points[-1]['t']:raise ValueError('이동 표본 시간이 중복됩니다.')
        points.append(rounded)
    start=points[0]['t']
    for p in points:p['t']=round(p['t']-start,3)
    if not 30<=points[-1]['t']<=60000:raise ValueError('이동 측정 시간 범위를 벗어났습니다.')
    return points

def mouse_metrics(value):
    points=clean_path(value)
    lengths=[math.hypot(b['x']-a['x'],b['y']-a['y']) for a,b in zip(points,points[1:])]
    distance=sum(lengths)
    if distance<20:raise ValueError('20px 이상 이동한 뒤 좌석을 선택하세요.')
    duration=points[-1]['t'];direct=math.hypot(points[-1]['x']-points[0]['x'],points[-1]['y']-points[0]['y'])
    speeds=[d*1000/(b['t']-a['t']) for d,a,b in zip(lengths,points,points[1:])]
    # Landing is a partial render frame, followed by a stop. Measure travelling
    # speed on the preceding segments for every actor; retain the full raw path.
    moving=speeds[:-1] if len(speeds)>=3 else speeds
    travel_lengths=lengths[:-1] if len(speeds)>=3 else lengths
    travel_ms=points[-2]['t'] if len(speeds)>=3 else duration
    speed=sum(travel_lengths)*1000/travel_ms;straightness=min(1,direct/distance);variation=cv(moving)
    # Distance-weighted departure from the start-to-end line.
    a,b=points[0],points[-1]
    deviations=[abs((b['x']-a['x'])*(p['y']-a['y'])-(b['y']-a['y'])*(p['x']-a['x']))/direct if direct else math.hypot(p['x']-a['x'],p['y']-a['y']) for p in points]
    speed_score=100*-math.expm1(-speed/2400)
    steady=100*math.exp(-3*variation);pattern=.6*100*straightness**4+.4*steady
    suspicious=speed>=1800 and (straightness>=.97 or variation<=.18)
    return dict(duration_ms=round(duration,3),distance_px=round(distance,3),mean_speed_px_s=round(speed,3),
                straightness=round(straightness,5),speed_cv=round(variation,5),deviation_px=round(mean(deviations),3),
                speed_score=round(speed_score,5),pattern_score=round(pattern,5),risk_score=round(.45*speed_score+.55*pattern,3),
                verdict='AI 패턴' if suspicious else '사람 패턴',suspicious=suspicious,
                overall_speed_px_s=round(distance*1000/duration,3),overall_speed_cv=round(cv(speeds),5),
                speed_window='travel_without_arrival_segment' if len(speeds)>=3 else 'full_path',speed_samples=len(moving),
                sample_count=len(points),path=points,detector_version=MOUSE_VERSION)

def payment_metrics(data,server_elapsed_ms):
    """Four field timings; values and clipboard contents are never accepted."""
    if set(data)-{'duration_ms','fields'}:raise ValueError('입력 내용은 전송하지 않습니다.')
    duration=float(data.get('duration_ms',0))
    if not math.isfinite(duration) or not 100<=duration<=600000 or abs(duration-server_elapsed_ms)>1500:raise ValueError('결제 화면 측정 시간을 확인하세요.')
    fields=data.get('fields')
    if not isinstance(fields,list) or len(fields)!=4:raise ValueError('네 가지 항목을 입력하세요.')
    cleaned=[];names=set()
    labels={'name':'이름','phone':'연락처','email':'이메일','address':'주소'}
    for f in fields:
        if not isinstance(f,dict) or set(f)-{'field','length','events','focused_at'}:raise ValueError('입력 내용은 전송하지 않습니다.')
        name=f.get('field');length=f.get('length')
        if name not in FIELDS or name in names or type(length)!=int or not 1<=length<=160:raise ValueError('입력 항목을 확인하세요.')
        names.add(name);events=f.get('events')
        if not isinstance(events,list) or not 1<=len(events)<=400:raise ValueError('입력 이벤트 기록이 필요합니다.')
        safe=[]
        for e in events:
            if not isinstance(e,dict) or set(e)-{'t','chars'}:raise ValueError('입력 내용은 전송하지 않습니다.')
            t=float(e.get('t',-1));n=e.get('chars')
            if not math.isfinite(t) or not 0<=t<=duration or type(n)!=int or not 0<=n<=160 or (safe and t<safe[-1]['t']):raise ValueError('입력 시간 기록이 잘못되었습니다.')
            safe.append({'t':round(t,3),'chars':n})
        entered=[e for e in safe if e['chars']>0]
        if not entered or sum(e['chars'] for e in safe)<length:raise ValueError('입력 이벤트가 누락되었습니다.')
        focus=round(float(f.get('focused_at',-1)),3)
        if not math.isfinite(focus) or not 0<=focus<=entered[0]['t']:raise ValueError('입력칸 선택 시간이 필요합니다. 화면을 새로 열어주세요.')
        cleaned.append({'field':name,'length':length,'events':safe,'focused_at':round(focus,3)})
    measured=[]
    for f in sorted(cleaned,key=lambda f:next(e['t'] for e in f['events'] if e['chars']>0)):
        entered=[e for e in f['events'] if e['chars']>0];first=entered[0]['t'];last=entered[-1]['t']
        earlier=[(e['t'],other['field']) for other in cleaned if other['field']!=f['field'] for e in other['events'] if e['chars']>0 and e['t']<first]
        previous=max(earlier,default=None);transition=first-previous[0] if previous else None
        active_ms=max(1,last-f['focused_at']);chars=sum(e['chars'] for e in entered);bulk=sum(e['chars'] for e in entered if e['chars']>1)/chars
        cps=chars*1000/active_ms;speed=100*cps/(cps+20);transition_score=100*math.exp(-transition/1200) if transition is not None else None
        score=.45*speed+.30*100*bulk+.25*transition_score if transition_score is not None else .60*speed+.40*100*bulk
        suspicious=score>=75 and cps>=15 and bulk>=.8 and active_ms<=250 and (transition is None or transition<=1200)
        gaps=[b['t']-a['t'] for a,b in zip(entered,entered[1:]) if b['t']>a['t']]
        measured.append(dict(field=f['field'],field_label=labels[f['field']],length=f['length'],input_chars=chars,
            duration_ms=round(active_ms,3),input_duration_ms=round(active_ms,3),typing_span_ms=round(last-first,3),
            focused_at=f['focused_at'],first_input_ms=first,last_input_ms=last,
            previous_field=previous[1] if previous else None,transition_ms=round(transition,3) if transition is not None else None,
            speed_cps=round(cps,3),bulk_ratio=round(bulk,5),timing_cv=round(cv(gaps),5),
            speed_score=round(speed,5),pattern_score=round(100*bulk,5),risk_score=round(score,3),
            suspicious=suspicious,verdict='AI 패턴' if suspicious else '사람 패턴',events=f['events'],
            detector_version=PAYMENT_VERSION,checkout_duration_ms=round(duration,3)))
    total_ms=sum(f['duration_ms'] for f in measured);chars=sum(f['input_chars'] for f in measured)
    bulk=sum(f['input_chars']*f['bulk_ratio'] for f in measured)/chars
    suspicious=sum(f['suspicious'] for f in measured)>=3
    return dict(duration_ms=round(duration,3),fill_duration_ms=round(total_ms,3),speed_cps=round(chars*1000/total_ms,3),
                bulk_ratio=round(bulk,5),speed_score=round(mean(f['speed_score'] for f in measured),5),
                pattern_score=round(100*bulk,5),risk_score=round(mean(f['risk_score'] for f in measured),3),
                suspicious=suspicious,verdict='AI 패턴' if suspicious else '사람 패턴',fields=cleaned,
                field_metrics=measured,detector_version=PAYMENT_VERSION)


def fixtures(mode):
    rng=random.Random(537);out=[]
    for kind in ('human','ai'):
        for i in range(10):
            if mode=='mouse':
                duration=rng.uniform(85,145) if kind=='ai' else rng.uniform(650,1700)
                bend=rng.uniform(0,1.5) if kind=='ai' else rng.uniform(35,160)
                points=[]
                for n in range(25):
                    u=n/24;progress=u if kind=='ai' else u**rng.uniform(.8,1.0) if n in (0,24) else (1-math.cos(math.pi*u))/2
                    points.append({'t':duration*u,'x':80+480*progress,'y':90+250*progress+bend*math.sin(math.pi*u)})
                measured=mouse_metrics(points)
            else:
                duration=rng.uniform(750,1400) if kind=='ai' else rng.uniform(9000,22000)
                fs=[]
                for j,name in enumerate(FIELDS):
                    length=(5,13,17,12)[j];start=duration*(.12+j*.18)
                    events=[{'t':start,'chars':length}] if kind=='ai' else [{'t':start+k*duration*.12/length*rng.uniform(.98,1.02),'chars':1} for k in range(length)]
                    fs.append({'field':name,'length':length,'events':events,'focused_at':start-(45 if kind=='ai' else 120)})
                measured=payment_metrics({'duration_ms':duration,'fields':fs},duration)['field_metrics'][i%4]
            out.append(dict(measured,id=f'{mode}-fixture-{kind}-{i}',session_id=f'{mode}-fixture-{kind}-{i}',
                            actor_kind=kind,measurement_origin='synthetic_fixture',synthetic=True))
    return out
