(() => {
 if(!window.RETRY_CONTEXT)return;
 const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
 let latest=null,ready=false,polling=false,epoch=0,x=80,y=100,successShown=null;
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,Math.max(0,ms)));
 const check=t=>{if(t!==epoch||latest?.sales_closed||latest?.result)throw new DOMException('중지됨','AbortError');};
 const notice=t=>{if(q('#retry-notice'))q('#retry-notice').textContent=t;};
 const ms=v=>v==null?'—':(v/1000).toFixed(3)+'초';
 function conflictDialog(){
  let dialog=q('#seat-conflict');if(dialog)return dialog;
  dialog=document.createElement('dialog');dialog.id='seat-conflict';dialog.className='seat-conflict';dialog.setAttribute('aria-labelledby','seat-conflict-title');
  dialog.innerHTML='<span class="seat-conflict-icon" aria-hidden="true">!</span><h2 id="seat-conflict-title">이미 판매된 좌석입니다</h2><p id="seat-conflict-seat"></p><p>다른 좌석을 선택해주세요.</p><button id="seat-conflict-reselect">다른 좌석 선택</button>';
  document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{for(const id of ['#ai-cursor','#ai-click-ring']){const el=q(id);if(el)document.body.append(el);}window.mouseCapture.reset();if(ready&&area)loadArea(false).catch(()=>{});});return dialog;
 }
 function soldOut(seat){const dialog=conflictDialog();q('#seat-conflict-seat').textContent=seat?seatName(seat):'';if(!dialog.open)dialog.showModal();q('#seat-conflict-reselect').focus();}
 function closeConflict(){if(q('#seat-conflict')?.open)q('#seat-conflict').close();}
 function showSuccess(s){
  if(successShown===s.run_id||q('#start-modal').open)return;
  successShown=s.run_id;closeConflict();window.mouseCapture.stop();q('#ai-cursor').hidden=true;
  let dialog=q('#seat-success');
  if(!dialog){
   dialog=document.createElement('dialog');dialog.id='seat-success';dialog.className='seat-conflict seat-success';dialog.setAttribute('aria-labelledby','seat-success-title');
   dialog.innerHTML='<button id="seat-success-close" aria-label="닫기">×</button><span class="seat-conflict-icon" aria-hidden="true">✓</span><h2 id="seat-success-title">예매 성공</h2><p>선택하신 좌석이 확보되었습니다.</p><p id="seat-success-detail"></p><button id="seat-success-checkout">주문·결제하기</button>';
   document.body.append(dialog);q('#seat-success-close').onclick=()=>dialog.close();q('#seat-success-checkout').onclick=checkout;
  }
  q('#seat-success-detail').textContent='KOPO · '+s.selected.map(seatName).join(', ');
  dialog.showModal();q('#seat-success-checkout').focus();
 }
 function closeSuccess(){if(q('#seat-success')?.open)q('#seat-success').close();}
 function checkout(){if(latest?.result!=='success')return;epoch++;ready=false;window.mouseCapture.stop();if(parent!==window)parent.location.href='/presentation?scenario=payment&from=retry';else location.href='/practice/checkout?from=retry';}
 function apply(s){
  if(!s.run_id)return;latest=s;if(s.sales_closed)closeConflict();render(s.result==='success'?{...s,phase:'seats'}:s);
  const m=s.mouse_metrics;q('#retry-kind').textContent=(s.actor_kind==='ai'?'AI':'사람')+' · '+s.attempts.length+'회 시도';
  q('#retry-latency').textContent=m?Math.round(m.mean_speed_px_s).toLocaleString()+' px/s':'—';
  q('#retry-interval').textContent=m?(m.straightness*100).toFixed(1)+'%':'—';
  q('#retry-cv').textContent=m?(m.speed_cv*100).toFixed(1)+'%':'수집 중';
  q('#retry-score').textContent=m?m.verdict:'마우스를 움직여 좌석 선택';
  let next=q('#retry-checkout');if(!next){next=document.createElement('button');next.id='retry-checkout';next.textContent='03 결제창으로';q('#result-modal .result-actions').append(next);next.onclick=checkout;}next.hidden=s.result!=='success';
  q('#confirm-seats').innerHTML=(s.result==='success'?'주문·결제하기':'좌석선택완료')+' <span>〉</span>';
  q('#confirm-seats').disabled=s.result?s.result!=='success':!s.selected.length;
  q('#retry-market').textContent=s.sales_closed?'예매 마감':`마감까지 ${s.remaining_seconds.toFixed(1)}초`;
  q('#retry-stock').textContent=`잔여 ${s.available_seats.toLocaleString()} / ${s.total_seats.toLocaleString()}석`;
  q('#retry-stock-bar').style.width=(s.available_seats/s.total_seats*100)+'%';
  if(s.result==='success'){notice('좌석 확보 완료 · 주문·결제를 진행하세요.');clearTimeout(messageTimer);q('#booking-message').classList.remove('visible');showSuccess(s);}
  else if(s.sales_closed)notice('모든 좌석이 소진되었습니다.');
  else if(s.last_outcome==='scenario_failure'&&!s.selected.length)notice(`선택한 좌석이 판매되었습니다. 다른 좌석을 선택해주세요.`);
 }
 async function raw(path,data){
  const run=latest?.run_id;
  const r=await fetch('/api/retry/'+path,data===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const v=await r.json();if(path==='start'||!run||latest?.run_id===run){if(v.run_id)apply(v);}
  return {r,v};
 }
 async function bookingAPI(path,data){
  if(path==='select')data={...data,movement:window.mouseCapture.consume()};
  if(path==='reserve')data={...data,selection_token:latest?.selection_token};
  if(path==='ranking')return {items:[]};
  const run=latest?.run_id;const {r,v}=await raw(path,data);if(!r.ok){const e=Error(v.error||'예매 요청 실패');if(v.error_code==='seat_sold_out'&&run===latest?.run_id&&!latest?.sales_closed){soldOut(v.conflict_seat);e.seatConflict=true;}throw e;}return v;
 }
 async function poll(){if(!ready||polling)return;polling=true;try{await raw('state');if(area&&Date.now()-refreshAt>700)await loadArea(false);}catch(e){notice(e.message);}finally{polling=false;}}
 window.liveBooking={active:true,api:bookingAPI,poll};
 async function waitFor(predicate,t,timeout=8000){const end=performance.now()+timeout;while(!predicate()){check(t);if(performance.now()>end)throw Error('좌석 화면 응답을 기다리는 중입니다.');await sleep(30);}}
 async function move(el,t){
  check(t);el.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});const b=el.getBoundingClientRect(),nx=b.left+b.width/2,ny=b.top+b.height/2,cursor=q('#ai-cursor');cursor.hidden=false;
  const host=el.closest('dialog[open]')||document.body;host.append(cursor,q('#ai-click-ring'));
  const recording=el.matches('[data-seat]');if(recording)window.mouseCapture.reset();const start=performance.now(),sx=x,sy=y;
  // Fixed travelling velocity, with enough visible frames for short movements.
  const duration=Math.max(recording?45:70,Math.hypot(nx-sx,ny-sy)/3500*1000);if(recording)window.mouseCapture.point(sx,sy,start);
  await new Promise(resolve=>{function frame(now){const u=Math.min(1,(now-start)/duration);x=sx+(nx-sx)*u;y=sy+(ny-sy)*u;cursor.style.transform=`translate(${x}px,${y}px)`;if(recording)window.mouseCapture.point(x,y,now);if(u<1)requestAnimationFrame(frame);else resolve();}requestAnimationFrame(frame);});check(t);

 }
 function click(el,t){
  check(t);el.click();const ring=q('#ai-click-ring');ring.hidden=false;ring.style.left=x+'px';ring.style.top=y+'px';
  ring.animate([{opacity:1,transform:'translate(-50%,-50%) scale(.5)'},{opacity:0,transform:'translate(-50%,-50%) scale(1.5)'}],{duration:300}).finished.then(()=>ring.hidden=true);
 }
 async function automate(t){
  async function acknowledge(){if(!q('#seat-conflict')?.open)return;await sleep(320);check(t);if(q('#seat-conflict')?.open){await move(q('#seat-conflict-reselect'),t);click(q('#seat-conflict-reselect'),t);}}
  try{
   for(let i=0;i<35&&!latest.result;i++){
    check(t);await acknowledge();const cycle=performance.now();
    if(area!=='A')await openArea('A');await loadArea(true);check(t);
    const seat=q('#sector-seats .seat-dot.available:not(:disabled)');if(!seat)throw Error('선택 가능한 좌석이 없습니다.');
    notice(`AI ${latest.attempts.length+1}번째 시도 · 좌석 상태 확인`);await move(seat,t);click(seat,t);
    await waitFor(()=>latest.selected.includes(seat.dataset.seat)||q('#seat-conflict')?.open,t);if(q('#seat-conflict')?.open){await acknowledge();continue;}
    const submit=q('#confirm-seats');await move(submit,t);
    await sleep(cycle+300-performance.now());check(t);const before=latest.attempts.length;click(submit,t);
    await waitFor(()=>latest.attempts.length>before||q('#seat-conflict')?.open,t);
    if(latest.result)break;
    await acknowledge();await sleep(cycle+latest.ai_cycle_ms-performance.now());
   }
  }catch(e){if(e.name!=='AbortError')notice(e.message);}finally{if(t===epoch){q('#ai-cursor').hidden=true;q('#retry-stop').disabled=true;}}
 }
 function role(){const ai=q('input[name="booking-role"]:checked').value==='ai';q('#start').textContent=ai?'AI 예매 시작':'직접 예매 시작';q('#ai-start-settings').hidden=true;qa('.human-setting').forEach(el=>el.hidden=ai);q('#practice-mode').closest('label').hidden=true;q('.start-steps').hidden=true;}
 function chooser(){epoch++;closeConflict();closeSuccess();window.mouseCapture.stop();q('#ai-cursor').hidden=true;for(const id of ['#result-modal','#info-modal'])if(q(id).open)q(id).close();q('#start-modal').showModal();role();}
 async function start(){
  const button=q('#start');button.disabled=true;ready=false;closeConflict();closeSuccess();const t=++epoch;
  try{
   const kind=q('input[name="booking-role"]:checked').value;
   const {r,v}=await raw('start',{actor_kind:kind,nickname:kind==='ai'?'AI':q('#nickname').value});if(!r.ok)throw Error(v.error);
   latest=v;window.mouseCapture.start(kind);area=null;seatData=null;resultShown=null;overview();q('#start-modal').close();apply(v);ready=true;
   notice('선택한 좌석을 확인하고 주문·결제로 진행해주세요.');await openArea('A');
   q('#retry-stop').disabled=kind!=='ai';if(kind==='ai')automate(t);
  }catch(e){notice(e.message);}finally{button.disabled=false;}
 }
 document.addEventListener('DOMContentLoaded',()=>{
  document.documentElement.classList.add('retry-booking');
  q('#intro').hidden=true;q('#queue').hidden=true;q('#booking').hidden=false;q('#ai-demo').hidden=true;
  const bar=document.createElement('section');bar.className='retry-toolbar';bar.innerHTML='<header><b>02 마우스 경로</b><span id="retry-kind">예매 방식 선택</span><button id="retry-stop" disabled>중지</button><button id="retry-new">다시 예매</button></header><p id="retry-notice">선택한 좌석을 확인하고 예매를 진행해주세요.</p><div class="retry-readings"><div>이동 속도<strong id="retry-latency">—</strong></div><div>직선성<strong id="retry-interval">—</strong></div><div>속도 변동(CV)<strong id="retry-cv">—</strong></div><div>패턴 판정<strong id="retry-score">—</strong></div></div>';
  bar.insertAdjacentHTML('beforeend','<div class="retry-market"><b id="retry-market">예매 대기</b><span id="retry-stock">잔여 3,600석</span><div class="retry-stock-track"><i id="retry-stock-bar"></i></div></div>');
  q('#booking').before(bar);
  q('.wordmark').innerHTML='I-Ticket <span>티켓 예매</span>';
  q('#booking').insertAdjacentHTML('afterbegin','<div class="booking-flow" aria-label="예매 단계"><span class="done"><i>✓</i> 날짜·회차</span><em>›</em><span class="current"><i>2</i> 좌석 선택</span><em>›</em><span><i>3</i> 주문·결제</span></div>');
  q('.instructions>div').textContent='원하는 좌석을 선택한 후 좌석선택완료를 눌러주세요.';
  q('.booking-heading>div>span').textContent='2026 KOPO CONCERT';
  q('.seat-sidebar').insertAdjacentHTML('afterbegin','<section class="ticket-summary"><div class="ticket-cover" aria-label="KOPO 콘서트 포스터"><b>KOPO</b><small>LIVE</small><em>2026</em></div><div><b>KOPO</b><p>2026 KOPO CONCERT</p><p>02.08 SUN · 19:00<br>KOPO홀</p></div></section>');
  q('.seat-workspace').insertAdjacentHTML('beforeend','<div class="seat-legend"><span><i class="available"></i>선택 가능</span><span><i class="chosen"></i>선택 좌석</span><span><i></i>선택 불가</span></div>');
  q('#all-seats').innerHTML='전체 좌석도 보기';

  q('#start-modal h2').textContent='KOPO 예매 방식 선택';q('#start-modal .modal-kicker').textContent='KOPO CONCERT';
  q('#start').onclick=start;qa('input[name="booking-role"]').forEach(el=>el.onchange=role);
  let reserving=false;q('#confirm-seats').onclick=async()=>{if(latest?.result==='success'){checkout();return;}if(reserving||!latest?.selected.length)return;reserving=true;q('#confirm-seats').disabled=true;try{await bookingAPI('reserve',{});}catch(e){if(!e.seatConflict)tell(e.message);await poll();if(area)await loadArea(false);}finally{reserving=false;if(latest)apply(latest);}};
  for(const id of ['#settings-nav','#change-date','#previous','#retry','#retry-new'])q(id).onclick=chooser;
  q('#retry-stop').onclick=()=>{epoch++;q('#ai-cursor').hidden=true;q('#retry-stop').disabled=true;notice('자동 예매가 중지되었습니다.');};
  q('#records-nav').onclick=q('#ranking').onclick=()=>info('반복 예매 기록',latest?`<p>시도 ${latest.attempts.length}회 · 실패 ${latest.attempts.filter(a=>a.forced_failure).length}회 · ${latest.result==='success'?'성공':'진행 중'}</p>`:'<p>예매 방식을 선택하세요.</p>');
  q('.wordmark').href='/practice/retry';role();
  let arrival=new URLSearchParams(location.search);try{if(parent!==window&&parent.location.pathname==='/presentation')arrival=new URLSearchParams(parent.location.search);}catch(e){}
  if(arrival.get('from')==='captcha'){q('input[name="booking-role"][value="'+(arrival.get('actor')==='ai'?'ai':'human')+'"]').checked=true;role();start();}else q('#start-modal').showModal();
  setInterval(poll,250);
 });
})();
