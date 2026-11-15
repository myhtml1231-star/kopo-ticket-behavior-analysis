(() => {
 const q=s=>document.querySelector(s),mouse=document.body.dataset.mode==='mouse';let points=[],summaries={},latestPath=null,selectedPath=null,busy=false,signature='';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const ref=p=>p.measurement_origin==='synthetic_fixture',pct=n=>(n*100).toFixed(1)+'%',sec=n=>(n/1000).toFixed(3)+'초';
 const cleanup=GraphCleanup.create('ticket-demo.graph-hidden.v1.'+(mouse?'mouse':'payment'),ref);
 const logView=GraphCleanup.mountLog({key:'ticket-demo.log-hidden.v1.'+(mouse?'mouse':'payment'),items:()=>points.filter(p=>!ref(p)),onChange:render});
 const actor=p=>ref(p)?'참고 '+(p.actor_kind==='ai'?'AI':'사람'):p.actor_kind==='ai'?'AI':'사람';
 const fieldName={name:'이름',phone:'연락처',email:'이메일',address:'주소'};
 const desc=p=>mouse?`${actor(p)} · ${p.seat||'참고 경로'}\n${Math.round(p.mean_speed_px_s)} px/s · 직선성 ${pct(p.straightness)}\n속도 CV ${pct(p.speed_cv)} · 직선 이탈 ${p.deviation_px.toFixed(1)}px\n${p.verdict}`:`${actor(p)} · ${fieldName[p.field]||'입력'}\n입력 ${sec(p.input_duration_ms)} · 이전 입력 간격 ${p.transition_ms==null?'첫 항목':sec(p.transition_ms)}\n${p.speed_cps.toFixed(1)} 문자/초 · 일괄 입력 ${pct(p.bulk_ratio)}\nAI 점수 ${p.risk_score.toFixed(1)}점 · ${p.verdict}`;
 if(!mouse){
  q('.chart-header p').textContent='항목별 입력 시간 · 항목 전환 간격 · 일괄 입력 비율';
  q('.interaction-comparison thead tr').innerHTML='<th>구분</th><th>총 입력 시간</th><th>문자/초</th><th>일괄 입력</th><th>AI 점수</th><th>판정</th>';
  const header=q('.log-panel thead tr');if(header)header.innerHTML='<th>구분</th><th>항목</th><th>입력 시간</th><th>이전 입력 간격</th><th>문자/초</th><th>일괄 입력</th><th>AI 점수</th><th>판정</th>';
  if(q('.log-panel h2'))q('.log-panel h2').textContent='개인정보 입력 기록';
  if(q('.log-panel footer'))q('.log-panel footer').textContent='입력칸 선택→마지막 입력 · 이전 항목 마지막 입력→현재 첫 입력 · 내용 저장 안 함';
  q('.timing-note').textContent='빠른 입력·짧은 전환·일괄 입력일수록 AI 점수 증가 · 0–100점의 규칙 기반 지표';
 }

 const visible=()=>points.filter(p=>q('#session-filter').value==='all'||p.actor_kind===q('#session-filter').value);
 const plot=PatternPlot.create({canvas:q('#behavior-chart'),controls:q('.chart-controls'),tip:q('#point-tip'),describe:desc,
  xLabel:mouse?'이동 속도 지수 (0–100)':'입력 속도 지수 (0–100)',yLabel:mouse?'직선·속도 일정함 (0–100)':'일괄 입력 비율 (0–100%)',
  onSelect:p=>{q('#selected-point').hidden=false;q('#selected-point').textContent=desc(p).replaceAll('\n',' · ');if(mouse){selectedPath=p;q('#path-view').hidden=false;q('#path-toggle').setAttribute('aria-pressed','true');drawPath(p);}}});
 const cleanButton=document.createElement('button');cleanButton.id='graph-clear';cleanButton.textContent='그래프 정리';cleanButton.title='기존 실시간 점 숨기기 · 저장 기록과 참고 점 유지';cleanButton.onclick=()=>{cleanup.clear(points);selectedPath=null;latestPath=null;q('#selected-point').hidden=true;if(mouse){q('#path-view').hidden=true;q('#path-toggle').setAttribute('aria-pressed','false');}plot.reset();render();};q('.chart-controls').append(cleanButton);
 function drawPath(p){
  if(!mouse||q('#path-view').hidden||!p?.path?.length)return;const canvas=q('#path-canvas'),ctx=canvas.getContext('2d'),r=canvas.getBoundingClientRect(),d=devicePixelRatio||1;canvas.width=r.width*d;canvas.height=r.height*d;ctx.setTransform(d,0,0,d,0,0);
  const path=p.path,xs=path.map(p=>p.x),ys=path.map(p=>p.y),minx=Math.min(...xs),miny=Math.min(...ys),scale=Math.min((r.width-32)/Math.max(1,Math.max(...xs)-minx),(r.height-24)/Math.max(1,Math.max(...ys)-miny));
  const xy=p=>[16+(p.x-minx)*scale,12+(p.y-miny)*scale];ctx.setLineDash([4,4]);ctx.strokeStyle='#aeb8c6';ctx.beginPath();ctx.moveTo(...xy(path[0]));ctx.lineTo(...xy(path.at(-1)));ctx.stroke();ctx.setLineDash([]);ctx.strokeStyle=p.actor_kind==='ai'?'#df3348':'#2676e8';ctx.lineWidth=1.8;ctx.beginPath();path.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](...xy(p)));ctx.stroke();for(const point of [path[0],path.at(-1)]){ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.arc(...xy(point),3,0,Math.PI*2);ctx.fill();}q('#path-detail').textContent=p.mean_speed_px_s?`${Math.round(p.mean_speed_px_s)} px/s · 직선성 ${pct(p.straightness)} · 속도 CV ${pct(p.speed_cv)}`:`${p.actor_kind==='ai'?'AI':'사람'} · 실시간 ${path.length}개 좌표`;
 }
 if(mouse){q('#path-toggle').onclick=()=>{const show=q('#path-view').hidden;q('#path-view').hidden=!show;q('#path-toggle').setAttribute('aria-pressed',String(show));selectedPath=null;if(show)drawPath(latestPath);};window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==q('#booking-frame')?.contentWindow||e.data?.type!=='mouse-path-preview')return;latestPath=e.data;if(!selectedPath)drawPath(latestPath);});new ResizeObserver(()=>drawPath(selectedPath||latestPath)).observe(q('#path-canvas'));}
 function render(){
  logView.sync();
  plot.set(visible().filter(p=>cleanup.keep(p)));const live=points.filter(p=>!ref(p)),shown=live.filter(p=>cleanup.keep(p));q('#point-count').textContent=`참고 20 · 사람 ${shown.filter(p=>p.actor_kind==='human').length} · AI ${shown.filter(p=>p.actor_kind==='ai').length}`;
  q('#comparison').innerHTML=['human','ai'].map(kind=>{const p=mouse?live.filter(p=>p.actor_kind===kind).at(-1):summaries[kind];return `<tr data-kind="${kind}"><td>${kind==='ai'?'AI':'사람'}</td><td>${p?(mouse?Math.round(p.mean_speed_px_s).toLocaleString():sec(p.fill_duration_ms)):'—'}</td><td>${p?(mouse?pct(p.straightness):p.speed_cps.toFixed(1)):'—'}</td><td>${p?pct(mouse?p.speed_cv:p.bulk_ratio):'—'}</td>${mouse?'':`<td>${p?p.risk_score.toFixed(1)+'점':'—'}</td>`}<td>${p?p.verdict:'측정 대기'}</td></tr>`;}).join('');
  if(q('#behavior-logs')){
   q('#behavior-logs').innerHTML=visible().filter(p=>!ref(p)&&logView.keep(p)).slice().reverse().map(p=>mouse?
    `<tr data-id="${p.id}" tabindex="0"><td>${actor(p)}</td><td>${esc(p.seat)}</td><td>${Math.round(p.mean_speed_px_s).toLocaleString()} px/s</td><td>${pct(p.straightness)}</td><td>${pct(p.speed_cv)}</td><td>${p.verdict}</td></tr>`:
    `<tr data-id="${p.id}" data-kind="${p.actor_kind}" tabindex="0"><td>${actor(p)}</td><td>${fieldName[p.field]||'입력'}<small class="field-compact field-actor">${actor(p)}</small></td><td>${sec(p.input_duration_ms)}<small class="field-compact">${p.transition_ms==null?'첫 항목':'전환 '+sec(p.transition_ms)}</small></td><td>${p.transition_ms==null?'첫 항목':sec(p.transition_ms)}</td><td>${p.speed_cps.toFixed(1)}</td><td>${pct(p.bulk_ratio)}<small class="field-compact">${p.speed_cps.toFixed(1)} 문자/초</small></td><td>${p.risk_score.toFixed(1)}점<small class="field-compact">${p.verdict}</small></td><td>${p.verdict}</td></tr>`).join('')||`<tr class="log-empty"><td colspan="${mouse?6:8}">새로운 로그를 기다리고 있습니다.</td></tr>`;
   q('#behavior-logs').querySelectorAll('tr[data-id]').forEach(el=>el.onclick=()=>{const p=points.find(p=>p.id===el.dataset.id);q('#selected-point').hidden=false;q('#selected-point').textContent=desc(p).replaceAll('\n',' · ');if(mouse){selectedPath=p;q('#path-view').hidden=false;drawPath(p);}});
  }

 }
 async function refresh(){if(busy)return;busy=true;try{const r=await fetch(mouse?'/api/retry/behavior':'/api/checkout/behavior',{cache:'no-store'});if(!r.ok)throw Error();const v=await r.json();points=v.points;summaries=v.summaries||{};const next=JSON.stringify(summaries)+points.map(p=>p.id).join(',');if(next!==signature){signature=next;render();}if(v.market&&mouse){q('#market-clock').textContent=v.market.sales_closed?'예매 마감':`마감까지 ${v.market.remaining_seconds.toFixed(1)}초`;q('#market-stock').textContent=`잔여 ${v.market.available_seats.toLocaleString()}석`;}if(q('#connection'))q('#connection').textContent='● 실시간 측정';if(q('#delivery'))q('#delivery').textContent=`EMQX ${v.mqtt} · 워커 ${v.worker_live?'연결':'확인 필요'}`;}catch(e){if(q('#connection'))q('#connection').textContent='연결 확인 필요';}finally{busy=false;}}
 const frame=q('#booking-frame');if(frame){const fit=()=>{const r=frame.parentElement.getBoundingClientRect(),w=Math.max(mouse?0:600,r.width),scale=r.width/w;frame.style.width=w+'px';frame.style.height=r.height/scale+'px';frame.style.transformOrigin='top left';frame.style.transform=`scale(${scale})`;};new ResizeObserver(fit).observe(frame.parentElement);fit();}
 q('#session-filter').onchange=render;refresh();setInterval(refresh,500);
})();

import('/static/pane_resize.js');
