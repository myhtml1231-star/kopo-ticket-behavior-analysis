(() => {
  const context = window.LIVE_CONTEXT;
  const q = s => document.querySelector(s);
  let token = '', latest = null, ready = false, polling = false, automation = false, stopped = false;
  let x = 80, y = 80;
  const local = {active:!!context, launch, api:bookingAPI, poll};
  window.liveBooking = local;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, Math.max(0,ms)));
  const check = () => {if(stopped || latest?.banned || latest?.room_phase==='stopped')throw new DOMException('예매 중지','AbortError');};
  function notice(text) {if(q('#live-status'))q('#live-status').textContent=text;}
  async function launch(scene) {
    const r=await fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scene})});
    const v=await r.json();if(!r.ok)throw Error(v.error||'예매 환경을 시작할 수 없습니다.');
    location.assign(v.url);
  }
  async function raw(action,data) {
    const r=await fetch(`/api/live/${context.room}/${context.actor}/${action}`,data===undefined?{headers:{'X-Live-Token':token},cache:'no-store'}:{method:'POST',headers:{'X-Live-Token':token,'Content-Type':'application/json'},body:JSON.stringify(data)});
    const v=await r.json();return {v,status:r.status,ok:r.ok};
  }
  async function bookingAPI(path,data) {
    const result=await raw(path,data);
    if(result.v.run_id)apply(result.v);
    if(!result.ok)throw Error(result.v.error||'예매 요청이 거절되었습니다.');
    return result.v;
  }
  async function control(data) {
    const r=await fetch(`/api/live/${context.room}/control`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    if(!r.ok)throw Error('이 창에는 예매 제어 권한이 없습니다.');
  }
  function apply(state) {
    latest=state;render(state);
    if(q('#live-account'))q('#live-account').textContent=`${state.account_id} · ${state.role==='observer'?'관찰·제어':context.actor+'번 예매 창'}`;
    if(q('#live-metrics'))q('#live-metrics').textContent=state.scene==='parallel'?`준비 ${state.ready_windows}/5 · 처리 중 ${state.pending_requests}건`:`실제 예매 요청 ${state.attempts.length}회 · 충돌 ${state.attempts.filter(a=>a.outcome==='seat_taken').length}회`;
    if(q('#live-fire'))q('#live-fire').disabled=state.ready_windows!==5||state.room_phase!=='waiting';
    if(state.banned)showBan(state);
    else if(state.room_phase==='banned'&&state.role==='observer')notice('동일 계정의 예매 요청 차단 완료 · 실제 창 5개');
    if(state.room_phase==='stopped'){stopped=true;notice('중지됨');q('#ai-cursor').hidden=true;}
  }
  async function poll() {
    if(!ready||polling||latest?.banned||latest?.room_phase==='banned'||latest?.room_phase==='stopped')return;
    polling=true;
    try {const r=await raw('state');if(!r.ok)throw Error(r.v.error);apply(r.v);if(area&&Date.now()-refreshAt>700)await loadArea(false);}
    catch(e){notice(e.message);}finally{polling=false;}
  }
  function showBan(state) {
    stopped=true;q('#ai-cursor').hidden=true;
    if(context.embedded){notice('계정 차단 · 403');q('#confirm-seats').disabled=true;return;}
    q('#ai-ban-title').textContent='계정의 예매 요청을 차단했습니다';q('#ai-ban-reason').textContent=state.ban.title;
    q('#ai-ban-evidence').replaceChildren(...state.ban.evidence.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
    q('#ai-ban-account').textContent=state.account_id;q('#ai-ban-next').textContent=state.scene==='seats'?'동시 예매':'처음으로';q('#ai-ban-next').onclick=()=>state.scene==='seats'?launch('parallel'):location.assign('/practice/intro');
    q('#ai-ban-close').onclick=()=>q('#ai-ban').close();
    if(!q('#ai-ban').open&&!q('#ai-ban').dataset.dismissed)q('#ai-ban').showModal();
    q('#ai-ban-close').onclick=()=>{q('#ai-ban').dataset.dismissed='1';q('#ai-ban').close();};
    notice('계정 차단 · 예매 중단');
  }
  async function move(selector,duration=500,click=true) {
    check();const el=typeof selector==='string'?q(selector):selector;if(!el)throw Error('예매 버튼을 찾을 수 없습니다.');
    el.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
    const rect=el.getBoundingClientRect(),nx=rect.left+rect.width*.5,ny=rect.top+rect.height*.5;
    const cursor=q('#ai-cursor');cursor.hidden=false;
    const animation=cursor.animate([{transform:`translate(${x}px,${y}px)`},{transform:`translate(${x+(nx-x)*.45-5}px,${y+(ny-y)*.45+7}px)`,offset:.5},{transform:`translate(${nx}px,${ny}px)`}],{duration,easing:'ease-in-out',fill:'forwards'});
    await animation.finished;check();x=nx;y=ny;cursor.style.transform=`translate(${x}px,${y}px)`;animation.cancel();
    if(click){el.click();const ring=q('#ai-click-ring');ring.hidden=false;ring.style.left=x+'px';ring.style.top=y+'px';const a=ring.animate([{transform:'translate(-50%,-50%) scale(.5)',opacity:1},{transform:'translate(-50%,-50%) scale(1.4)',opacity:0}],{duration:350});a.finished.then(()=>ring.hidden=true);}
    await sleep(80);
  }
  async function waitFor(predicate,timeout=6000) {const until=Date.now()+timeout;while(!predicate()){check();if(Date.now()>until)throw Error('예매 페이지 응답 대기 시간을 초과했습니다.');await sleep(100);}}
  async function visit(a) {
    if(!q('#area-map').hidden){await move(`[data-area="${a}"]`,450);}
    else {await move('#overview',260);await sleep(120);await move(`[data-area="${a}"]`,450);}
    await waitFor(()=>area===a&&seatData?.area===a);
  }
  async function sequential() {
    notice('전체 예매 페이지에서 A–H 구역 탐색');
    for(const a of 'ABCDEFGH'){check();await visit(a);await sleep(300);}
    await raw('ready',{});await poll();
    const began=Date.now();let lastSeat=null;
    while(Date.now()-began<100000&&!latest.banned&&!latest.booked.length) {
      check();await poll();
      const released=[...latest.releases].reverse().find(r=>r.seat!==lastSeat&&latest.area_counts[r.seat[0]]>0);
      if(!released){await sleep(120);continue;}
      const a=released.seat[0];await visit(a);check();
      const button=q(`[data-seat="${released.seat}"]`);
      if(!button||button.disabled){lastSeat=released.seat;continue;}
      notice('실제 취소표 발견 · '+released.seat);await move(button,380);
      await waitFor(()=>latest.selected.includes(released.seat)||!q(`[data-seat="${released.seat}"]`)?.classList.contains('available'),2500).catch(()=>{});
      if(!latest.selected.includes(released.seat)){lastSeat=released.seat;continue;}
      await move('#confirm-seats',420,false);
      const until=released.at*1000+3350-Date.now();if(until>0)await sleep(until);
      check();const before=latest.attempts.length;await move('#confirm-seats',70);
      await waitFor(()=>latest.attempts.length>before||latest.booked.length||latest.banned,6500).catch(e=>{if(!latest.banned)throw e;});
      lastSeat=released.seat;
      if(latest.booked.length){notice('예매 성공 · 실제 재고 확보');break;}
      notice(`재고 선점 충돌 ${latest.attempts.filter(a=>a.outcome==='seat_taken').length}회 · 다음 취소표 탐색`);
    }
    q('#ai-cursor').hidden=true;
  }
  async function parallelActor() {
    await visit('A');const seat=`A-1-${context.actor}`;
    if(!latest.selected.includes(seat)){await move(`[data-seat="${seat}"]`,450);await waitFor(()=>latest.selected.includes(seat));}
    const result=await raw('ready',{});if(result.ok)apply(result.v);
    notice('동일 계정 · 다른 예매 창의 준비를 기다립니다.');
    await move('#confirm-seats',400,false);
    await waitFor(()=>latest.fire_at!==null,1800000);
    const fire=latest.fire_at*1000;notice('예매 요청 전송 대기');
    if(fire>Date.now())await sleep(fire-Date.now());
    check();await move('#confirm-seats',40);notice('예매 요청 처리 중');
    await waitFor(()=>latest.banned||latest.booked.length,10000).catch(e=>{if(!latest.banned)throw e;});q('#ai-cursor').hidden=true;
  }
  async function openWindows() {
    const r=await fetch(`/api/live/${context.room}/windows`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({width:screen.availWidth,height:screen.availHeight})});
    const v=await r.json();if(!r.ok)throw Error(v.error);notice('전체 예매 페이지를 Chrome/Edge 창 5개로 열었습니다.');
  }
  async function init() {
    const key=`live-token:${context.room}:${context.actor}`;
    token=new URLSearchParams(location.hash.slice(1)).get('access')||sessionStorage.getItem(key)||'';
    if(token){sessionStorage.setItem(key,token);history.replaceState(null,'',location.pathname+location.search);}
    document.title=`${context.actor==='controller'?'동시 예매 관제':context.actor+'번 전체 예매 창'} · 티켓팅`;
    ['#start-modal','#captcha-modal','#result-modal','#info-modal'].forEach(id=>{if(q(id).open)q(id).close();});
    q('#intro').hidden=true;q('#queue').hidden=true;q('#booking').hidden=false;q('#ai-demo').hidden=true;
    const bar=document.createElement('section');bar.className='live-bar';bar.innerHTML='<div><b>공유 좌석 예매</b><span id="live-account"></span></div><p id="live-status">예매 페이지 연결 중</p><div><span id="live-metrics"></span><label id="live-competitor-wrap"><input id="live-competitor" type="checkbox" checked> 경쟁 클라이언트</label><button id="live-open-windows">실제 예매 창 5개 열기</button><button id="live-fire" disabled>동시 예매 시작</button><button id="live-stop">중지</button><button id="live-home">처음으로</button></div>';
    q('#booking').before(bar);document.body.classList.add('live-page');
    q('#live-open-windows').onclick=()=>openWindows().catch(e=>notice(e.message));
    q('#live-fire').onclick=()=>control({action:'fire'}).then(poll).catch(e=>notice(e.message));
    q('#live-stop').onclick=async()=>{stopped=true;q('#ai-cursor').hidden=true;if(context.controls)await control({action:'stop'});notice('중지됨');};
    q('#live-home').onclick=()=>location.assign('/practice/intro');
    q('#settings-nav').onclick=q('#change-date').onclick=q('#previous').onclick=()=>location.assign('/practice/intro');
    q('#live-competitor').onchange=()=>control({action:'competitor',enabled:q('#live-competitor').checked}).catch(e=>notice(e.message));
    ready=true;await poll();if(!latest)return;
    q('#live-competitor-wrap').hidden=!context.controls||latest.scene!=='seats';q('#live-open-windows').hidden=!context.controls||latest.scene!=='parallel';
    q('#live-fire').hidden=latest.role!=='observer'||!context.controls;
    if(latest.role==='observer'){q('#confirm-seats').disabled=true;notice('실제 예매 창 5개의 요청을 관찰합니다.');await openWindows();}
    else if(latest.role==='ai'&&!latest.banned&&!latest.booked.length){automation=true;try{if(latest.scene==='seats')await sequential();else await parallelActor();}catch(e){if(e.name!=='AbortError')notice(e.message);}finally{automation=false;q('#ai-cursor').hidden=true;}}
  }
  if(context){if(context.embedded)document.documentElement.classList.add('live-embedded');document.addEventListener('DOMContentLoaded',()=>init().catch(e=>notice(e.message)));setInterval(poll,250);}
})();
