(() => {
  'use strict';
  const q = s => document.querySelector(s), canvas=q('#behavior-chart'), ctx=canvas.getContext('2d');
  const names={view:'예매 시작',seat_select:'좌석 선택',reserve:'예매',reserve_received:'예매 접수',area_view:'구역 조회',captcha_verify:'보안문자 확인',captcha_refresh:'보안문자 갱신',captcha_bulk_input:'보안문자 입력',queue_enter:'대기열 진입',ticket_cancel:'예매 취소'};
  const decisions={normal:'일반',watch:'주의',review:'검토 필요',blocked:'차단'};
  const colors={normal:'#357fe5',watch:'#d69827',review:'#db4959',blocked:'#db4959'};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let points=[], drawn=[], selected=null, since=Date.now()/1000-900, busy=false, chartW=0, chartH=0, offline=false;
  const filter=q('#session-filter');let logView=null;
  import('/static/graph_cleanup.js').then(()=>{logView=GraphCleanup.mountLog({key:'ticket-demo.log-hidden.v1.behavior',items:()=>points,onChange:render});render();});
  q('.chart-header p').textContent='계정별 최신 점 1개 · 동일 계정은 합산';
  const number=n=>n>=1000?Math.round(n).toLocaleString('ko-KR'):Number(n.toFixed(n<1?2:1)).toString();
  const clock=at=>new Date(at*1000).toLocaleTimeString('ko-KR',{hour12:false});
  const label=s=>s.startsWith('practice-')?'사람 · '+s.slice(-6):s.startsWith('ai-demo-')?'AI · '+s.slice(-6):s.length>24?s.slice(0,9)+'…'+s.slice(-6):s;
  function visible(){return filter.value==='all'?points:points.filter(p=>p.series===filter.value);}
  function niceMax(value,integer=false){
    if(!value)return integer?10:2;
    const rough=value*1.15/5,base=10**Math.floor(Math.log10(rough));
    const step=[1,2,2.5,5,10].map(n=>n*base).find(n=>n>=rough)||base*10;
    return Math.max(integer?5:1,Math.ceil(value*1.12/step)*step);
  }
  function paint(){
    const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
    chartW=rect.width;chartH=rect.height;
    if(!chartW||!chartH)return;
    if(canvas.width!==Math.round(chartW*dpr)||canvas.height!==Math.round(chartH*dpr)){
      canvas.width=Math.round(chartW*dpr);canvas.height=Math.round(chartH*dpr);
    }
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,chartW,chartH);
    const latest=new Map();for(const p of visible())latest.set(p.series,p);
    const data=[...latest.values()],m={l:62,r:25,t:34,b:48},w=chartW-m.l-m.r,h=chartH-m.t-m.b;
    if(w<=0||h<=0)return;
    const xmax=niceMax(Math.max(0,...data.map(p=>p.speed))),ymax=niceMax(Math.max(0,...data.map(p=>p.requests_30s)),true);
    ctx.font='12px Arial,"Malgun Gothic",sans-serif';ctx.lineWidth=1;
    for(let i=0;i<=5;i++){
      const x=m.l+w*i/5,y=m.t+h-h*i/5;
      ctx.strokeStyle='#edf0f5';ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+h);ctx.stroke();
      ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(m.l+w,y);ctx.stroke();
      ctx.fillStyle='#8794a5';ctx.textAlign='center';ctx.fillText(number(xmax*i/5),x,m.t+h+18);
      ctx.textAlign='right';ctx.fillText(number(ymax*i/5),m.l-9,y+4);
    }
    ctx.strokeStyle='#9eacbc';ctx.beginPath();ctx.moveTo(m.l,m.t-6);ctx.lineTo(m.l,m.t+h);ctx.lineTo(m.l+w+7,m.t+h);ctx.stroke();
    ctx.fillStyle='#596b82';ctx.textAlign='left';ctx.fillText('요청 수 (최근 30초)',m.l,m.t-17);
    ctx.textAlign='right';ctx.fillText('속도 (회/초)',m.l+w,chartH-8);
    drawn=data.map(p=>({...p,x:m.l+w*p.speed/xmax,y:m.t+h-h*p.requests_30s/ymax}));
    for(const p of drawn){
      const active=selected===p.id;
      ctx.fillStyle=colors[p.decision];ctx.beginPath();ctx.arc(p.x,p.y,active?7:5.5,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle=colors[p.decision];ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(p.x,p.y,active?10:8,0,Math.PI*2);ctx.stroke();
    }
    ctx.globalAlpha=1;q('#plot-empty').hidden=data.length>0;
    q('#point-count').textContent=`${data.length.toLocaleString('ko-KR')}점 · ${new Set(data.map(p=>p.series)).size}계정`;
  }
  function describe(p){return `${label(p.series)} · ${clock(p.at)}\n${names[p.action]||p.action}${p.seat?' · '+p.seat:''}\n속도 ${p.interval_ms===null?'측정 대기':number(p.speed)+' 회/초'} · 30초 요청 ${p.requests_30s}회\n${decisions[p.decision]}`;}
  function choose(p){
    selected=p.id;const box=q('#selected-point');box.hidden=false;
    box.textContent=describe(p).replaceAll('\n',' / ')+(p.rules.length?' · 근거: '+p.rules.join(' / '):'')+' · 요청 ID '+p.id;paint();
  }
  function nearest(e){const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=null,distance=14;
    for(const p of drawn){const d=Math.hypot(p.x-x,p.y-y);if(d<=distance){distance=d;best=p;}}return best;}
  canvas.addEventListener('pointermove',e=>{
    const p=nearest(e),tip=q('#point-tip');tip.hidden=!p;canvas.style.cursor=p?'pointer':'default';
    if(p){tip.textContent=describe(p);tip.style.left=Math.min(Math.max(5,p.x+12),Math.max(5,chartW-245))+'px';tip.style.top=Math.max(3,Math.min(p.y+10,chartH-115))+'px';}
  });
  canvas.addEventListener('pointerleave',()=>q('#point-tip').hidden=true);
  canvas.addEventListener('click',e=>{const p=nearest(e);if(p)choose(p);});
  function render(){
    const previous=filter.value,series=[...new Set(points.map(p=>p.series))];
    const options='<option value="all">전체 계정</option>'+series.map(s=>`<option value="${esc(s)}">${esc(label(s))}</option>`).join('');
    if(filter.innerHTML!==options){filter.innerHTML=options;filter.value=series.includes(previous)?previous:'all';}
    const logs=q('#behavior-logs');
    if(logs){if(logView)logView.sync();logs.innerHTML=visible().filter(p=>!logView||logView.keep(p)).slice(-60).reverse().map(p=>`<tr data-id="${esc(p.id)}" tabindex="0"><td>${clock(p.at)}</td><td title="${esc(p.series)}">${esc(label(p.series))}</td><td>${esc(names[p.action]||p.action)}${p.seat?' · '+esc(p.seat):''}</td><td>${p.interval_ms===null?'—':number(p.speed)}</td><td>${p.requests_30s}</td><td class="decision-${p.decision}">${decisions[p.decision]}</td></tr>`).join('')||'<tr><td colspan="6">예매 행동을 기다리고 있습니다.</td></tr>';
      logs.querySelectorAll('[data-id]').forEach(row=>{const select=()=>choose(points.find(p=>p.id===row.dataset.id));row.onclick=select;row.onkeydown=e=>{if(e.key==='Enter')select();};});}
    paint();
  }
  async function refresh(){
    if(busy)return;busy=true;
    try{const r=await fetch('/api/behavior?since='+since,{cache:'no-store'});if(!r.ok)throw Error();const v=await r.json();points=v.points;offline=false;render();
      if(q('#connection'))q('#connection').textContent='● 실시간 연결';
      if(q('#delivery'))q('#delivery').textContent=`EMQX ${v.mqtt} · 저장 워커 ${v.worker_live?'연결':'확인 필요'}`;
    }catch(e){offline=true;if(q('#connection'))q('#connection').textContent='서버 연결 끊김';q('#plot-empty').textContent='서버 연결을 확인하세요.';q('#plot-empty').hidden=false;}finally{busy=false;}
  }
  filter.onchange=render;
  q('#clear-view').onclick=()=>{since=Date.now()/1000;points=[];selected=null;q('#selected-point').hidden=true;filter.value='all';render();refresh();};
  q('#formula').onclick=()=>{const text=q('#formula-text');text.hidden=!text.hidden;q('#formula').setAttribute('aria-expanded',String(!text.hidden));paint();};
  new ResizeObserver(paint).observe(canvas.parentElement);
  const frame=q('#booking-frame');
  if(frame){const fit=()=>{const r=frame.parentElement.getBoundingClientRect(),width=Math.max(820,r.width),scale=r.width/width;
    frame.style.width=width+'px';frame.style.height=(r.height/scale)+'px';frame.style.transformOrigin='top left';frame.style.transform=`scale(${scale})`;};new ResizeObserver(fit).observe(frame.parentElement);fit();}
  refresh();setInterval(refresh,750);
})();

import('/static/pane_resize.js');
