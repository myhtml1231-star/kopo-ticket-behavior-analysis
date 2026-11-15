"""Explainable demo detector. Ground-truth source labels are never detector inputs."""
from collections import defaultdict, deque
from statistics import mean, pstdev
import time

VERSION='behavior-v3'

class Detector:
 def __init__(self):
  self.sessions=defaultdict(lambda:{'events':deque(),'last':None,'intervals':deque(maxlen=16),'viewed':False,'selected':None})

 def observe(self,session,action,seat=None,outcome='ok',now=None):
  now=time.monotonic() if now is None else now
  s=self.sessions[session]
  while s['events'] and s['events'][0]['time']<now-60: s['events'].popleft()
  interval=None
  if s['last'] is not None:
   interval=max(0,now-s['last']); s['intervals'].append((now,interval))
  s['last']=now
  # A selection must follow a page view; a reservation must match that selection.
  flow_bad=action=='reserve' and (not s['viewed'] or s['selected']!=seat)
  if action=='view': s['viewed']=True
  if action=='seat_select' and outcome=='ok': s['selected']=seat
  if action=='reserve' and outcome=='ok' and not flow_bad: s['selected']=None
  s['events'].append({'time':now,'action':action,'seat':seat,'outcome':outcome,'flow_bad':flow_bad})
  recent=list(s['events']); burst=[e for e in recent if e['time']>=now-10]
  intervals=[v for t,v in s['intervals'] if t>=now-15]
  avg=mean(intervals) if intervals else None
  cv=pstdev(intervals)/avg if len(intervals)>1 and avg else None
  flow_count=sum(e['flow_bad'] or e['outcome']=='gate_violation' for e in recent)
  # Do not count a rejected workflow again as a failure signal.
  attempts=[e for e in recent if e['action']=='reserve' and not e['flow_bad']]
  failures=sum(e['outcome'] in ('seat_taken','invalid_seat') for e in attempts)
  failure_rate=failures/len(attempts) if attempts else 0
  signals=[]
  def add(code,group,weight,reason): signals.append({'code':code,'group':group,'weight':weight,'reason':reason})
  if len(intervals)>=12 and avg is not None and avg<1 and cv is not None and cv<.12:
   add('regular_timing','timing',30,f'요청 간격 {len(intervals)}개가 일정함 (평균 {avg*1000:.0f}ms, 변동계수 {cv:.2f})')
  if len(burst)>=30:
   add('request_burst','rate',15,f'10초 동안 요청 {len(burst)}회')
  if flow_count>=3:
   add('invalid_workflow','flow',35,f'대기·인증·좌석 선택 절차를 위반한 요청 {flow_count}회/1분')
  if len(attempts)>=6 and failures>=6 and failure_rate>=.8:
   add('failure_concentration','failure',35,f'예매 실패 {failures}/{len(attempts)}회 ({failure_rate:.0%}, 좌석 충돌·잘못된 좌석)')
  score=min(100,sum(x['weight'] for x in signals))
  strong_groups={x['group'] for x in signals if x['group']!='rate'}
  suspicious=score>=60 and len(strong_groups)>=2
  return {'detector_version':VERSION,'risk_score':score,'decision':'review' if suspicious else 'watch' if signals else 'normal','suspicious':suspicious,'rules':[x['reason'] for x in signals],'signals':signals,'interval_ms':round(interval*1000) if interval is not None else None,'requests_60s':len(recent),'selections_10s':sum(e['action']=='seat_select' for e in burst),'timing_cv':round(cv,3) if cv is not None else None,'flow_violations':flow_count,'failure_rate':round(failure_rate,3),'failure_attempts':len(attempts)}
