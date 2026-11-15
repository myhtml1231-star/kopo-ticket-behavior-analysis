(() => {
 const q=s=>document.querySelector(s),canvas=q('canvas'),ctx=canvas.getContext('2d');
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const retry=document.body.dataset.scenario==='retry';
 let points=[],logPoints=[],drawn=[],selected=null,busy=false;
 const fullView={xmin:0,xmax:105,ymin:0,ymax:105};
 let view={...fullView},plot=null,drag=null,lastPointer=null,suppressClick=false,zoomFocus=null;
 const isReference=p=>p.measurement_origin==='synthetic_fixture';
 const cleanup=GraphCleanup.create('ticket-demo.graph-hidden.v1.captcha',isReference);
 const logView=GraphCleanup.mountLog({key:'ticket-demo.log-hidden.v1.captcha',items:()=>retry?logPoints:points,onChange:render});
 const label=p=>isReference(p)?'참고 '+(p.actor_kind==='ai'?'AI':'사람'):'실시간 '+(p.actor_kind==='ai'?'AI':'사람');
 const visible=()=>points.filter(p=>q('#session-filter').value==='all'||p.actor_kind===q('#session-filter').value);
 const logs=()=> (retry?logPoints.filter(p=>q('#session-filter').value==='all'||p.actor_kind===q('#session-filter').value):visible()).filter(p=>logView.keep(p));
 const seconds=v=>v==null?'—':(v/1000).toFixed(3)+'초';
 function description(p){if(retry)return `${label(p)} · ${p.attempt_no}번째 · ${p.outcome==='success'?'성공':'예매 실패'} · ${p.seat}\n선택→예매 ${seconds(p.selection_to_submit_ms)} · 시도 간격 ${seconds(p.last_interval_ms)}\n평균 ${seconds(p.avg_interval_ms)} · 표준편차 ${seconds(p.interval_std_ms)} · 간격 CV ${p.cadence_cv==null?'수집 중':(p.cadence_cv*100).toFixed(2)+'%'} · 선택 시간 CV ${p.selection_cv==null?'수집 중':(p.selection_cv*100).toFixed(2)+'%'}\n속도 ${p.speed_index??'—'} · 일정함 ${p.consistency_index??'—'} · 종합 ${p.risk_score??'수집 중'}`;return `${label(p)} · ${p.session_id}\n문자 입력 ${(p.duration_ms/1000).toFixed(4)}초 · ${p.speed_cps.toFixed(3)} 문자/초\n패턴 ${p.pattern_score==null?'간격 기록 없음':p.pattern_score.toFixed(1)+'점'}${p.bulk_ratio!=null?' · 일괄 입력 '+Math.round(p.bulk_ratio*100)+'%':''}${p.timing_cv!=null?' · 간격 변동 '+p.timing_cv.toFixed(2):''}${p.display_to_submit_ms!=null?'\n표시→완료 '+(p.display_to_submit_ms/1000).toFixed(3)+'초 (이동 포함)':''}`;}
 const num=(n,span=100)=>Number(n.toFixed(Math.min(8,Math.max(0,2-Math.floor(Math.log10(span)))))).toString();
 function setView(xmin,xmax,ymin,ymax){
  const bounds=(a,b)=>{const span=Math.min(105,Math.max(.000001,b-a)),lo=Math.max(0,Math.min(105-span,a));return [lo,lo+span];};
  [view.xmin,view.xmax]=bounds(xmin,xmax);[view.ymin,view.ymax]=bounds(ymin,ymax);
  q('#point-tip').hidden=true;paint();
 }
 function zoom(factor,anchor){
  const center=anchor||(zoomFocus&&zoomFocus.x>=view.xmin&&zoomFocus.x<=view.xmax&&zoomFocus.y>=view.ymin&&zoomFocus.y<=view.ymax?zoomFocus:null)||{x:(view.xmin+view.xmax)/2,y:(view.ymin+view.ymax)/2};zoomFocus=center;
  setView(center.x+(view.xmin-center.x)*factor,center.x+(view.xmax-center.x)*factor,
          center.y+(view.ymin-center.y)*factor,center.y+(view.ymax-center.y)*factor);
 }
 if(retry){q('.legend>span').remove();canvas.setAttribute('aria-label','예매 속도와 시도 간격 일정함의 실시간 산점도');}
 const controls=q('.chart-controls');
 for(const [id,label,title,handler] of [
  ['graph-clear','그래프 정리','기존 실시간 점 숨기기 · 저장 기록과 참고 점 유지',()=>{cleanup.clear(points);selected=null;view={...fullView};zoomFocus=null;q('#point-tip').hidden=true;q('#selected-point').hidden=true;paint();}],
  ['zoom-in','＋','그래프 확대',()=>zoom(.5)],
  ['zoom-out','−','그래프 축소',()=>zoom(2)],
  ['zoom-reset','전체','전체 보기',()=>{view={...fullView};zoomFocus=null;paint();}]
 ]){const button=document.createElement('button');button.id=id;button.textContent=label;button.title=title;button.setAttribute('aria-label',title);button.onclick=handler;controls.append(button);}
 function paint(){
  const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1,w=r.width,h=r.height;
  if(!w||!h)return;
  canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
  const data=visible().filter(p=>cleanup.keep(p)&&p.pattern_score!=null),m={l:62,r:25,t:h<220?24:32,b:h<220?34:46},pw=w-m.l-m.r,ph=h-m.t-m.b;
  const sx=view.xmax-view.xmin,sy=view.ymax-view.ymin;plot={...m,pw,ph};
  ctx.font='12px Arial,"Malgun Gothic",sans-serif';ctx.lineWidth=1;
  const ticks=ph<120?2:5;
  for(let i=0;i<=ticks;i++){
   const x=m.l+pw*i/ticks,y=m.t+ph-ph*i/ticks;
   ctx.strokeStyle='#edf0f5';ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+ph);ctx.stroke();ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(m.l+pw,y);ctx.stroke();
   ctx.fillStyle='#8794a5';ctx.textAlign='center';ctx.fillText(num(view.xmin+sx*i/ticks,sx),x,m.t+ph+18);ctx.textAlign='right';ctx.fillText(num(view.ymin+sy*i/ticks,sy),m.l-9,y+4);
  }
  ctx.strokeStyle='#9eacbc';ctx.beginPath();ctx.moveTo(m.l,m.t-5);ctx.lineTo(m.l,m.t+ph);ctx.lineTo(m.l+pw+6,m.t+ph);ctx.stroke();
  ctx.fillStyle='#596b82';ctx.textAlign='left';ctx.fillText(retry?'시도 일정함 점수 (0–100)':'입력 패턴 점수 (0–100)',m.l,m.t-15);ctx.textAlign='right';ctx.fillText(retry?'예매 속도 지수 (0–100)':'입력 속도 지수 (0–100)',m.l+pw,h-7);
  const groups=new Map();
  for(const p of data){if(p.speed_score<view.xmin||p.speed_score>view.xmax||p.pattern_score<view.ymin||p.pattern_score>view.ymax)continue;
   const key=p.speed_score+':'+p.pattern_score;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);}
  drawn=[...groups.values()].map(members=>{const p=members.find(p=>p.id===selected)||members.filter(p=>!isReference(p)).at(-1)||members.at(-1);return {...p,members,x:m.l+pw*(p.speed_score-view.xmin)/sx,y:m.t+ph-ph*(p.pattern_score-view.ymin)/sy};});
  for(const p of drawn){const reference=isReference(p);ctx.fillStyle=reference?'#111111':p.actor_kind==='ai'?'#df3348':'#2676e8';ctx.beginPath();ctx.arc(p.x,p.y,reference?1.3:2.6,0,Math.PI*2);ctx.fill();
   if(p.members.some(member=>member.id===selected)){ctx.strokeStyle=ctx.fillStyle;ctx.beginPath();ctx.arc(p.x,p.y,reference?3.5:5,0,Math.PI*2);ctx.stroke();}
  }
  q('#plot-empty').hidden=data.length>0;
  if(retry){q('#point-count').textContent=`사람 ${points.filter(p=>p.actor_kind==='human').length}회차 · AI ${points.filter(p=>p.actor_kind==='ai').length}회차`;q('.timing-note').textContent='CV가 작을수록 일정한 간격입니다. 점수 = 속도 40% + 일정함 60% · 실패 횟수 제외.';return;}
  const fixtures=data.filter(p=>p.measurement_origin==='synthetic_fixture'),real=data.filter(p=>!p.synthetic),scripted=data.filter(p=>p.measurement_origin==='scripted_browser_input_span');
  const missing=points.filter(p=>p.pattern_score==null).length;const note=q('.timing-note');note.textContent='속도가 빠를수록 오른쪽, 간격이 일정하거나 일괄 입력할수록 위쪽에 표시합니다.'+(missing?' 간격 정보 없는 이전 기록은 표에만 표시합니다.':'');
  q('#point-count').textContent=`참고 ${fixtures.length} · 사람 ${real.length} · AI ${scripted.length}`;
 }
 function choose(p){selected=p.id;q('#selected-point').hidden=false;q('#selected-point').textContent=description(p).replaceAll('\n',' / ')+(p.members?.length>1?' · 같은 좌표 '+p.members.length+'건: '+p.members.map(p=>p.session_id).join(', '):'');paint();}
 function nearest(e){const r=canvas.getBoundingClientRect();let p=null,d=12;for(const item of drawn){const delta=Math.hypot(item.x-(e.clientX-r.left),item.y-(e.clientY-r.top));if(delta<=d){p=item;d=delta;}}return p;}
 canvas.onpointermove=e=>{const rect=canvas.getBoundingClientRect();lastPointer={x:e.clientX-rect.left,y:e.clientY-rect.top};
  if(drag&&plot){const dx=(e.clientX-drag.x)/plot.pw*(drag.view.xmax-drag.view.xmin),dy=(e.clientY-drag.y)/plot.ph*(drag.view.ymax-drag.view.ymin);if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>3)drag.moved=true;setView(drag.view.xmin-dx,drag.view.xmax-dx,drag.view.ymin+dy,drag.view.ymax+dy);canvas.style.cursor='grabbing';return;}
  const p=nearest(e),tip=q('#point-tip');tip.hidden=!p;canvas.style.cursor=p?'pointer':'grab';if(p){tip.textContent=description(p)+(p.members.length>1?'\n동일 좌표 '+p.members.length+'건 · 클릭해 목록 확인':'');tip.style.left=Math.max(5,Math.min(p.x+10,canvas.clientWidth-245))+'px';tip.style.top=Math.max(2,Math.min(p.y+8,canvas.clientHeight-110))+'px';}};
 canvas.onpointerdown=e=>{if(e.button!==0||!plot)return;zoomFocus=null;drag={x:e.clientX,y:e.clientY,view:{...view},moved:false};canvas.setPointerCapture(e.pointerId);};
 canvas.onpointerup=e=>{suppressClick=!!drag?.moved;drag=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);};canvas.onpointercancel=()=>drag=null;
 canvas.onpointerleave=()=>{q('#point-tip').hidden=true;lastPointer=null;};canvas.onclick=e=>{if(suppressClick){suppressClick=false;return;}const p=nearest(e);if(p)choose(p);};
 canvas.addEventListener('wheel',e=>{if(!plot)return;const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;if(x<plot.l||x>plot.l+plot.pw||y<plot.t||y>plot.t+plot.ph)return;e.preventDefault();zoom(e.deltaY<0?.65:1/.65,{x:view.xmin+(x-plot.l)/plot.pw*(view.xmax-view.xmin),y:view.ymin+(plot.t+plot.ph-y)/plot.ph*(view.ymax-view.ymin)});},{passive:false});
 canvas.title='휠로 확대·축소, 드래그로 이동';
 function render(){
  logView.sync();
  if(retry&&q('#retry-comparison')){
   q('#retry-comparison').innerHTML=['human','ai'].map(kind=>{const p=logPoints.filter(p=>p.actor_kind===kind).at(-1);return `<tr data-kind="${kind}"><td>${kind==='ai'?'AI':'사람'}</td><td>${p?p.attempt_no+'회':'—'}</td><td>${seconds(p?.avg_interval_ms)}</td><td>${p?.cadence_cv==null?'—':(p.cadence_cv*100).toFixed(2)+'%'}</td><td>${p?.risk_score==null?'수집 중':p.risk_score.toFixed(1)}</td></tr>`;}).join('');
  }
  if(q('#behavior-logs')){
   q('#behavior-logs').innerHTML=logs().slice().reverse().map(p=>retry?`<tr data-id="${p.id}" tabindex="0"><td>${p.actor_kind==='ai'?'AI':'사람'} · ${p.attempt_no}회</td><td>${esc(p.seat)}</td><td>${p.outcome==='success'?'성공':'실패 ('+p.attempt_no+'/5)'}</td><td>${seconds(p.selection_to_submit_ms)}</td><td>${seconds(p.last_interval_ms)}</td><td>${p.risk_score==null?'수집 중':p.risk_score.toFixed(1)}</td></tr>`:`<tr data-id="${p.id}" tabindex="0"><td>${label(p)}</td><td>${esc(p.session_id.replace('virtual-',''))}</td><td>${(p.duration_ms/1000).toFixed(4)}초</td><td>${p.speed_cps.toFixed(3)}</td><td>${p.pattern_score==null?'간격 기록 없음':p.pattern_score.toFixed(1)+'점'}</td></tr>`).join('')||`<tr class="log-empty"><td colspan="${retry?6:5}">새로운 로그를 기다리고 있습니다.</td></tr>`;
   q('#behavior-logs').querySelectorAll('[data-id]').forEach(row=>{row.onclick=()=>choose((retry?logPoints:points).find(p=>p.id===row.dataset.id));row.onkeydown=e=>{if(e.key==='Enter')row.click();};});
  }paint();
 }
 async function refresh(){
  if(busy)return;busy=true;
  try{const r=await fetch(retry?'/api/retry/behavior':'/api/behavior',{cache:'no-store'});if(!r.ok)throw Error();const v=await r.json();
   if(retry){if(v.market&&q('#market-clock')){const m=v.market;q('#market-clock').textContent=m.sales_closed?'예매 마감':`마감까지 ${m.remaining_seconds.toFixed(1)}초`;q('#market-stock').textContent=`잔여 ${m.available_seats.toLocaleString()} / ${m.total_seats.toLocaleString()}석`;q('#market-bar').style.width=(m.available_seats/m.total_seats*100)+'%';}logPoints=v.points;const last=new Map();for(const p of logPoints)last.set(p.run_id,p);points=[...last.values()];}else points=v.points;
   render();if(q('#connection'))q('#connection').textContent=retry?'● 반복 예매 측정':'● 보안문자만 기록';if(q('#delivery'))q('#delivery').textContent=`EMQX ${v.mqtt} · 워커 ${v.worker_live?'연결':'확인 필요'}`;
  }catch(e){if(q('#connection'))q('#connection').textContent='서버 연결 확인 필요';}finally{busy=false;}
 }
 q('#session-filter').onchange=()=>{view={...fullView};zoomFocus=null;render();};new ResizeObserver(paint).observe(canvas.parentElement);
 const frame=q('#booking-frame');if(frame){const fit=()=>{const r=frame.parentElement.getBoundingClientRect(),w=Math.max(820,r.width),scale=r.width/w;frame.style.width=w+'px';frame.style.height=r.height/scale+'px';frame.style.transformOrigin='top left';frame.style.transform=`scale(${scale})`;};new ResizeObserver(fit).observe(frame.parentElement);fit();}
 refresh();setInterval(refresh,750);
})();

import('/static/pane_resize.js');
