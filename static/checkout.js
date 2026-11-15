(() => {
 const q=s=>document.querySelector(s),inputs=[...document.querySelectorAll('[data-field]')];let run=null,started=0,events={},focusTimes={},epoch=0,active=false,cursorX=60,cursorY=100;
 const clickRing=document.createElement('div');clickRing.id='checkout-click-ring';clickRing.hidden=true;document.body.append(clickRing);let ringAnimation=null;
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 async function api(route,data){const r=await fetch('/api/checkout/'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||'요청 실패');return v;}
 function record(el,chars){if(active){const t=performance.now()-started;if(focusTimes[el.dataset.field]==null)focusTimes[el.dataset.field]=t;events[el.dataset.field].push({t,chars});}}
 for(const el of inputs){el.addEventListener('focus',()=>{if(active&&focusTimes[el.dataset.field]==null)focusTimes[el.dataset.field]=performance.now()-started;});let before=0;el.addEventListener('beforeinput',()=>before=el.value.length);el.addEventListener('input',()=>record(el,Math.max(0,el.value.length-before)));}
 function ensure(t){if(t!==epoch||!active)throw new DOMException('중지됨','AbortError');}
 function chooser(){epoch++;active=false;q('#checkout-cursor').hidden=true;clickRing.hidden=true;inputs.forEach(el=>el.classList.remove('ai-target'));if(q('#checkout-result').open)q('#checkout-result').close();q('#checkout-start').showModal();}
 async function move(el,t,duration=280){
  ensure(t);inputs.forEach(el=>el.classList.remove('ai-target'));el.scrollIntoView({block:'nearest',behavior:'instant'});
  const b=el.getBoundingClientRect(),nx=b.left+Math.min(b.width/2,32),ny=b.top+b.height/2,sx=cursorX,sy=cursorY,start=performance.now(),cursor=q('#checkout-cursor');cursor.hidden=false;
  await new Promise((resolve,reject)=>{function frame(now){if(t!==epoch||!active){reject(new DOMException('중지됨','AbortError'));return;}const u=Math.min(1,(now-start)/duration),ease=u*u*(3-2*u);cursorX=sx+(nx-sx)*ease;cursorY=sy+(ny-sy)*ease;cursor.style.transform=`translate(${cursorX}px,${cursorY}px)`;if(u<1)requestAnimationFrame(frame);else resolve();}requestAnimationFrame(frame);});ensure(t);
 }
 function click(el,t){
  ensure(t);if(ringAnimation)ringAnimation.cancel();clickRing.hidden=false;clickRing.style.left=cursorX+'px';clickRing.style.top=cursorY+'px';ringAnimation=clickRing.animate([{opacity:1,transform:'translate(-50%,-50%) scale(.5)'},{opacity:0,transform:'translate(-50%,-50%) scale(1.5)'}],{duration:300,fill:'forwards'});
  el.focus({preventScroll:true});el.click();if(el.matches('[data-field]'))el.classList.add('ai-target');
 }
 function insert(el,value,t){
  ensure(t);if(!el.dispatchEvent(new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertFromPaste',data:value})))return;
  el.value=value;el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertFromPaste',data:value}));
 }
 async function automate(t){
  try{const values=['김민수','010-0000-0000','kopo@example.com','서울특별시 중구 세종대로 110'],labels=['이름','연락처','이메일','주소'];
   for(let i=0;i<inputs.length;i++){q('#checkout-status').textContent=labels[i]+' 입력';await move(inputs[i],t);click(inputs[i],t);await sleep(45);insert(inputs[i],values[i],t);await sleep(100);ensure(t);}
   q('#checkout-status').textContent='결제 진행';await move(q('#pay'),t);click(q('#pay'),t);
  }catch(e){if(e.name!=='AbortError')q('#checkout-status').textContent=e.message;}finally{if(t===epoch){q('#checkout-cursor').hidden=true;inputs.forEach(el=>el.classList.remove('ai-target'));}}
 }
 async function start(fromRetry=false){const t=++epoch;active=false;q('#checkout-begin').disabled=true;
  try{run=await api('start',fromRetry?{from_retry:true}:{actor_kind:q('input[name="role"]:checked').value});if(t!==epoch)return;inputs.forEach(el=>{el.value='';el.disabled=false;el.classList.remove('ai-target');});cursorX=60;cursorY=100;q('#checkout-cursor').style.transform='translate(60px,100px)';clickRing.hidden=true;events=Object.fromEntries(inputs.map(el=>[el.dataset.field,[]]));focusTimes={};q('#pay').disabled=false;if(q('#checkout-start').open)q('#checkout-start').close();q('#checkout-role').textContent=run.actor_kind==='ai'?'AI · 자동 입력':'사람 · 직접 입력';q('#checkout-seat').textContent=run.seat.replace(/([A-H])-(\d+)-(\d+)/,'$1구역 $2열 $3번');q('#checkout-status').textContent='정보 입력 후 결제를 완료하세요.';await new Promise(requestAnimationFrame);if(t!==epoch)return;started=performance.now();active=true;if(run.actor_kind==='ai')automate(t);}catch(e){q('#checkout-status').textContent=e.message;if(fromRetry)chooser();}finally{q('#checkout-begin').disabled=false;}}
 q('#checkout-form').onsubmit=async e=>{e.preventDefault();if(!active)return;q('#pay').disabled=true;
  const body={duration_ms:performance.now()-started,fields:inputs.map(el=>({field:el.dataset.field,length:el.value.length,focused_at:focusTimes[el.dataset.field],events:events[el.dataset.field]}))};
  try{const v=await api('complete',body);active=false;const r=v.result;q('#checkout-status').textContent='결제 완료 · '+r.verdict;q('#checkout-verdict').textContent=r.verdict;q('#checkout-verdict').className=r.verdict==='AI 패턴'?'ai':'';q('#checkout-summary').textContent=`화면 표시→완료 ${(r.duration_ms/1000).toFixed(3)}초`;q('#checkout-evidence').textContent=`AI 점수 ${r.risk_score.toFixed(1)}점 · 일괄 입력 ${(r.bulk_ratio*100).toFixed(1)}%`;q('#checkout-result h2').textContent='예매 성공';q('#checkout-result').showModal();inputs.forEach(el=>el.disabled=true);}catch(e){q('#checkout-status').textContent=e.message;q('#pay').disabled=false;}
 };
 q('#checkout-begin').onclick=()=>start();q('#new-checkout').onclick=q('#checkout-replay').onclick=chooser;
 if(new URLSearchParams(location.search).get('from')==='retry')start(true);else chooser();
})();
