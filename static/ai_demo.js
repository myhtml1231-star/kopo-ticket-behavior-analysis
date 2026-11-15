(() => {
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const scenes = ['captcha', 'seats', 'parallel'];
  const names = {captcha:'보안문자 일괄 입력', seats:'일정 간격 반복 예매', parallel:'브라우저 5개 동시 요청'};
  let run = null, generation = 0, playing = false, cursorX = 80, cursorY = 120;
  const controller = {active:false, start, exit, stop:cancel};
  window.aiDemo = controller;
  const interrupted = () => new DOMException('예매 중지', 'AbortError');
  function ensure(token) { if (token !== generation || !controller.active) throw interrupted(); }
  async function wait(ms, token) { if(ms>0)await new Promise(resolve => setTimeout(resolve,ms)); ensure(token); }
  async function api(path, data) {
    const r = await fetch('/api/ai-demo/' + path, data === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const v = await r.json();
    if (!v.run) throw Error(v.error || '예매 요청 실패');
    return {...v.run, response_status:r.status};
  }
  async function action(type, details, token) {
    ensure(token);
    const id = run.id;
    const next = await api('action', {run_id:id,action:type,...details});
    ensure(token);
    if (next.id !== id) throw interrupted();
    run = next; trace(); return next;
  }
  function status(text, count='') {q('#ai-live-text').textContent=text;q('#ai-live-count').textContent=count;}
  function trace() {
    const labels = {area_view:'구역 조회',demo_seat_release:'취소표 발생',seat_select:'좌석 선택',reserve:'예매 요청',captcha_bulk_input:'일괄 입력',ai_demo_ban:'계정 차단',demo_browser_open:'브라우저 실행',demo_inventory_competition:'좌석 선점'};
    q('#ai-event-trace').innerHTML = run.history.slice(-4).map(e => `<span class="${e.action==='ai_demo_ban'?'blocked':''}">${esc(labels[e.action]||e.action)}${e.area?' '+esc(e.area):''}${e.window_id?' #'+esc(e.window_id):''}${e.outcome==='seat_taken'?' · 마감':''}</span>`).join('');
    q('#ai-account').textContent = run.account_id;
  }
  function cancel() {
    generation++; playing=false;q('#ai-cursor').getAnimations().forEach(a=>a.cancel());q('#ai-cursor').hidden=true;q('#ai-click-ring').hidden=true;
    q('#ai-stop').disabled=true;q('#ai-replay').disabled=false;q('#ai-demo').classList.remove('is-playing');
    if(controller.active && run && !run.banned) status('재생 중지 · 다시 재생으로 처음부터 시작');
  }
  async function start(scene='captcha') {
    window.CaptchaHandoff.close();
    if(scene!=='captcha'){await window.liveBooking.launch(scene);return;}
    cancel();controller.active=true;const token=generation;
    for(const id of ['#start-modal','#captcha-modal','#result-modal','#info-modal','#ai-ban']) if(q(id)?.open) q(id).close();
    ['#intro','#queue','#booking'].forEach(id=>q(id).hidden=true);q('#ai-demo').hidden=false;
    history.replaceState(null,'','/practice/ai');
    qa('[data-ai-scene]').forEach(b=>b.classList.toggle('active',b.dataset.aiScene===scene));
    status('예매 준비 중');q('#ai-canvas').innerHTML='';
    try {
      const next=await api('start',{scene});ensure(token);run=next;trace();build(scene);
      playing=true;q('#ai-stop').disabled=false;q('#ai-replay').disabled=true;q('#ai-demo').classList.add('is-playing');
      if(!window.CAPTCHA_TIMING_ONLY)await wait(500,token);
      if(scene==='captcha') await captcha(token);
      
      ensure(token);playing=false;q('#ai-stop').disabled=true;q('#ai-replay').disabled=false;q('#ai-cursor').hidden=true;q('#ai-demo').classList.remove('is-playing');
      if(run.banned) showBan();
    } catch(e) {
      if(e.name!=='AbortError') {cancel();status('예매를 진행할 수 없습니다: '+e.message);}
    }
  }
  function exit() {
    window.CaptchaHandoff.close();
    cancel();controller.active=false;q('#ai-demo').hidden=true;
    if(q('#ai-ban').open)q('#ai-ban').close();
    q('#intro').hidden=false;q('#queue').hidden=true;q('#booking').hidden=true;
    history.replaceState(null,'','/practice/intro');q('#start-modal').showModal();
  }
  async function move(target, token, duration=650) {
    ensure(token);const el=typeof target==='string'?q(target):target;
    if(!el)throw Error('입력 항목을 찾을 수 없습니다.');
    const bounds=el.getBoundingClientRect();
    if(bounds.top<70||bounds.bottom>innerHeight-20) el.scrollIntoView({block:'center',behavior:'instant'});
    const r=el.getBoundingClientRect(),x=r.left+r.width*.48,y=r.top+r.height*.52;
    const cursor=q('#ai-cursor');cursor.hidden=false;
    const dx=x-cursorX,dy=y-cursorY;
    const animation=cursor.animate([
      {transform:`translate(${cursorX}px,${cursorY}px)`},
      {transform:`translate(${cursorX+dx*.44-dy*.035}px,${cursorY+dy*.44+dx*.025}px)`,offset:.5},
      {transform:`translate(${x}px,${y}px)`}
    ],{duration,easing:'cubic-bezier(.25,.08,.22,1)',fill:'forwards'});
    await animation.finished;ensure(token);cursorX=x;cursorY=y;
    cursor.style.transform=`translate(${x}px,${y}px)`;animation.cancel();
    return el;
  }
  async function click(target, token, duration=650) {
    const el=await move(target,token,duration);ensure(token);
    const ring=q('#ai-click-ring');ring.hidden=false;ring.style.left=cursorX+'px';ring.style.top=cursorY+'px';
    const a=ring.animate([{transform:'translate(-50%,-50%) scale(.4)',opacity:1},{transform:'translate(-50%,-50%) scale(1.7)',opacity:0}],{duration:400});
    a.finished.then(()=>{if(token===generation)ring.hidden=true;});
    el.click();ensure(token);return el;
  }
  function venue() {
    return `<div class="ai-venue area-map"><svg class="venue-outline" viewBox="0 0 600 500" aria-hidden="true"><path d="M90 80H510V350L435 460H165L90 350Z" fill="#f1f1f1" stroke="#d6d6d6" stroke-width="2"/></svg><div class="main-stage">STAGE</div><div class="center-stage">STAGE</div>${[...'ABCDEFGH'].map(a=>`<button class="zone zone-${a.toLowerCase()}" data-demo-area="${a}">${a}</button>`).join('')}<div class="console">CONSOLE</div></div>`;
  }
  function bookingHead() {return `<div class="ai-ticket-head"><span><i>02</i> 좌석 선택</span><b>KOPO</b><small>2026.02.08 · 19:00</small></div>`;}
  function build(scene) {
    const canvas=q('#ai-canvas');
    if(scene==='captcha') {
      canvas.innerHTML=`${bookingHead()}<div class="ai-captcha-backdrop">${venue()}<aside><h3>선택좌석</h3><p>선택된 좌석이 없습니다.</p><button class="ai-reserve-button" disabled>좌석선택완료</button></aside></div><div class="ai-captcha-sheet"><span class="secure-pill">✓ 안심예매 · 입력 재현</span><h2>문자를 입력해주세요</h2><p>보안문자 입력 방식 확인</p><canvas id="ai-challenge" width="400" height="110" aria-label="보안문자 KRMXWA"></canvas><input id="ai-captcha-input" placeholder="문자를 입력해주세요" aria-label="보안문자 입력" readonly><div class="ai-input-metrics"><span>입력 이벤트 <b id="ai-input-count">0</b></span><span>키 입력 <b>0</b></span></div><button id="ai-captcha-confirm">입력완료</button></div>`;
      const ctx=q('#ai-challenge').getContext('2d');ctx.fillStyle='#8f1920';ctx.fillRect(0,0,400,110);
      for(let i=0;i<450;i++){ctx.fillStyle=i%2?'#e5b7b76b':'#b8d89b77';ctx.fillRect((i*71)%400,(i*37)%110,1.7,1.7);}
      ctx.font='bold 43px monospace';ctx.fillStyle='#b4d987';[...run.challenge].forEach((c,i)=>{ctx.save();ctx.translate(35+i*57,72);ctx.rotate((i%3-1)*.1);ctx.fillText(c,0,0);ctx.restore();});
    }
  }

  async function captcha(token) {
    if(window.CAPTCHA_TIMING_ONLY){
      await new Promise(resolve=>requestAnimationFrame(resolve));const started=performance.now();
      await action('captcha_shown',{},token);
      status('입력창으로 이동');await click('#ai-captcha-input',token,1100);await wait(250,token);
      const timingResponse=await fetch('/api/behavior',{cache:'no-store'});
      if(!timingResponse.ok)throw Error('기존 입력 시간을 확인할 수 없습니다.');
      const timingSamples=await timingResponse.json();ensure(token);
      const usedTimes=new Set(timingSamples.points.map(p=>p.input_duration_us??Math.round(p.duration_ms*1000)));
      const inputStarted=performance.now();
      status('일괄 입력 처리 중');await wait(run.input_target_ms,token);
      q('#ai-captcha-input').value=run.challenge;q('#ai-input-count').textContent='1';
      q('#ai-captcha-input').dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',data:run.challenge,bubbles:true}));
      const insertOffset=Math.max(1,Math.round((performance.now()-inputStarted)*1000)/1000);
      let inputElapsed=insertOffset;
      while(usedTimes.has(Math.round(inputElapsed*1000))){await wait(1,token);inputElapsed=Math.round((performance.now()-inputStarted)*1000)/1000;}
      status('문자 6개를 한 번에 입력');await wait(400,token);
      await click('#ai-captcha-confirm',token,1100);
      const elapsed=Math.round(performance.now()-started);
      await action('captcha_complete',{duration_ms:elapsed,input_duration_ms:inputElapsed,input_event_offsets_ms:[insertOffset],input_event_chars:[6],simulation_timing:'variable_bulk_processing'},token);
      status(`한 번에 입력 · ${(inputElapsed/1000).toFixed(4)}초`,'입력 처리 시간 · 커서 이동 제외');
      q('#ai-captcha-confirm').onclick=()=>window.CaptchaHandoff.show('ai');
      window.CaptchaHandoff.show('ai');
      return;
    }
    status('AI가 보안문자를 확인하고 있습니다.');await wait(1000,token);
    await click('#ai-captcha-input',token,850);await wait(380,token);
    status('문자 6개를 한 번에 입력');q('#ai-captcha-input').value=run.challenge;q('#ai-input-count').textContent='1';
    q('#ai-captcha-input').dispatchEvent(new InputEvent('input',{inputType:'insertFromPaste',data:run.challenge,bubbles:true}));
    await action('bulk_input',{input_type:'insertFromPaste',input_events:1,key_events:0,characters:6},token);
    status('일괄 입력 감지 → 계정 즉시 차단','입력 1회 · 키 입력 0회');
    q('#ai-captcha-input').classList.add('input-blocked');
    await wait(600,token);
  }
  function showBan() {
    q('#ai-ban-reason').textContent=run.ban.title;q('#ai-ban-evidence').innerHTML=run.ban.evidence.map(e=>`<li>${esc(e)}</li>`).join('');q('#ai-ban-account').textContent=run.account_id;
    q('#ai-ban-next').textContent=run.scene==='parallel'?'처음으로':'다음 단계';q('#ai-ban').showModal();
  }
  function restoreBannedFrame(){q('#ai-captcha-input').value=run.challenge;q('#ai-captcha-input').classList.add('input-blocked');q('#ai-input-count').textContent='1';}

  qa('[data-ai-scene]').forEach(b=>b.onclick=()=>start(b.dataset.aiScene));
  q('#ai-replay').onclick=()=>start(run?.scene||'captcha');q('#ai-stop').onclick=cancel;q('#ai-exit').onclick=exit;
  q('#ai-ban-close').onclick=()=>q('#ai-ban').close();q('#ai-ban-next').onclick=()=>{const i=scenes.indexOf(run.scene);if(i===2)exit();else start(scenes[i+1]);};
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&playing)cancel();});
  if(location.pathname==='/practice/ai') {
    controller.active=true;q('#ai-demo').hidden=false;q('#intro').hidden=true;
    api('state').then(v=>{if(v.scene!=='captcha'){exit();return;}run=v;build(v.scene);trace();qa('[data-ai-scene]').forEach(b=>b.classList.toggle('active',b.dataset.aiScene===v.scene));if(v.phase==='completed'&&window.CAPTCHA_TIMING_ONLY){q('#ai-captcha-input').value=run.challenge;q('#ai-input-count').textContent='1';status('입력완료 · 문자 6개를 한 번에 입력','커서 이동 시간 제외');q('#ai-stop').disabled=true;q('#ai-captcha-confirm').onclick=()=>window.CaptchaHandoff.show('ai');window.CaptchaHandoff.show('ai');}else if(v.banned){restoreBannedFrame();status('계정이 차단되었습니다.');showBan();}else{status('다시 재생을 눌러 예매를 시작하세요.');q('#ai-stop').disabled=true;}}).catch(()=>exit());
  }
})();
