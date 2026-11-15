(() => {
  const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
  const room=q('.parallel-app').dataset.room,key='parallel-controller:'+room;
  let token=new URLSearchParams(location.hash.slice(1)).get('access')||sessionStorage.getItem(key)||'',state=null,busy=false,focused=null,view='action';
  if(token){sessionStorage.setItem(key,token);history.replaceState(null,'',location.pathname);}
  const time=value=>new Date(value*1000).toLocaleTimeString('ko-KR',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'})+'.'+String(Math.floor(value*1000)%1000).padStart(3,'0');
  async function api(path,data){const r=await fetch(`/api/live/${room}/${path}`,data===undefined?{headers:{'X-Live-Token':token},cache:'no-store'}:{method:'POST',headers:{'X-Live-Token':token,'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||'요청 실패');return v;}
  function error(text){q('#parallel-error').textContent=text;q('#parallel-error').hidden=false;}
  function sizeFrames(){qa('.client-card').forEach(card=>{
    const box=card.querySelector('.client-viewport'),frame=box.querySelector('iframe');if(!frame)return;
    let bounds={left:0,top:0,width:1000,height:760};
    if(view==='action'&&!card.classList.contains('focused')){
      const doc=frame.contentDocument,heading=doc?.querySelector('.selection-heading'),bottom=doc?.querySelector('#confirm-seats');
      if(heading&&bottom){const a=heading.getBoundingClientRect(),b=bottom.getBoundingClientRect();bounds={left:a.left-10,top:a.top-12,width:a.width+20,height:b.bottom-a.top+24};}
    }
    const scale=Math.min(box.clientWidth/bounds.width,box.clientHeight/bounds.height);
    frame.style.transform=`scale(${scale})`;frame.style.left=((box.clientWidth-bounds.width*scale)/2-bounds.left*scale)+'px';frame.style.top=((box.clientHeight-bounds.height*scale)/2-bounds.top*scale)+'px';
  });}
  function focus(id){if(state?.phase==='parallel_fire'&&state.requests.some(r=>r.finished===null))return;focused=focused===id?null:id;qa('.client-card').forEach(card=>{const active=card.dataset.client===focused;card.classList.toggle('focused',active);card.querySelector('.client-focus').textContent=active?'분할 화면으로 돌아가기':'확대 ↗';});requestAnimationFrame(sizeFrames);}
  function render(v){
    state=v;q('#parallel-account').textContent='동일 계정 '+v.account;q('#parallel-ready').textContent=`${v.ready} / 5`;q('#parallel-pending').textContent=v.pending;q('#parallel-peak').textContent=v.peak_inflight;q('#parallel-overlap').textContent=v.overlap_ms?Number(v.overlap_ms).toLocaleString('ko-KR')+' ms':'—';
    const complete=v.requests.length>=5&&v.requests.every(r=>r.finished!==null),processing=v.phase==='parallel_fire'&&!complete&&!v.banned;
    q('#parallel-fire').disabled=v.ready!==5||v.phase!=='waiting';q('#parallel-fire').textContent=v.fire_at&&v.server_now<v.fire_at?`${Math.max(0,v.fire_at-v.server_now).toFixed(1)}초 후 동시 전송`:'동시 예매 시작';
    q('#parallel-phase').textContent=v.banned?'동일 계정 차단 · 다섯 요청의 처리 결과를 확인하세요.':v.phase==='stopped'?'예매 중지':v.fire_at&&v.server_now<v.fire_at?'다섯 예매 화면에 같은 전송 시각을 전달했습니다.':v.pending?'서로 다른 예매 화면의 요청을 서버가 처리 중입니다.':v.ready===5?'다섯 예매 화면이 모두 준비됐습니다. 시작을 누르세요.':`각 화면이 좌석 선택 중입니다. ${v.ready} / 5 준비`;
    q('.parallel-app').classList.toggle('blocked',v.banned);q('.parallel-summary').classList.toggle('blocked',v.banned);
    q('#summary-title').textContent=v.banned?'동일 계정 차단':v.phase==='stopped'?'예매 중지':v.pending?'동시에 요청 처리 중':v.ready===5?'동시 예매 준비 완료':'다섯 화면 준비 중';
    q('#summary-number').innerHTML=`${v.banned||v.requests.length?v.peak_inflight:v.ready}<span> / 5</span>`;
    q('#summary-message').textContent=v.banned?`서로 다른 화면 ${v.peak_inflight}개의 요청이 실제로 겹쳤습니다.`:v.phase==='stopped'?'다시 예매에서 다시 시작할 수 있습니다.':v.pending?`완료되지 않은 요청 ${v.pending}건이 서버에 있습니다.`:'시작 버튼을 누르면 3초 뒤 다섯 화면이 각각 요청합니다.';
    q('#parallel-details').hidden=!v.banned;q('#parallel-stop').disabled=v.banned||v.phase==='stopped';
    const latest=new Map();v.requests.forEach(r=>latest.set(r.actor,r));
    v.clients.forEach(client=>{const id=client.id,req=latest.get(id),card=q(`[data-client="${id}"]`);let label=client.ready?'준비 완료':client.joined?'좌석 선택 중':'연결 중';if(req)label=req.finished===null?'서버 처리 중':req.outcome==='account_blocked'?'차단 · 403':req.outcome==='ok'?'예매 성공':'예매 거절';card.classList.toggle('processing',!!req&&req.finished===null);card.classList.toggle('blocked',!!req&&req.outcome==='account_blocked');q('#client-state-'+id).textContent=label;
      const footer=q('#client-result-'+id),main=document.createElement('b'),detail=document.createElement('span');
      const seat=req?.seat||client.selected[0];main.textContent=seat?'선택 '+seat.replace(/([A-H])-(\d+)-(\d+)/,'$1구역 $2열 $3번'):'좌석 선택 중';
      detail.textContent=req?`접수 ${time(req.started)}${req.finished?' → '+time(req.finished):' · 응답 대기'}`:'동일 계정 · 동시 전송 대기';footer.replaceChildren(main,detail);
      card.querySelector('.client-focus').disabled=!(v.ready===5&&v.phase==='waiting'||complete||v.banned);});
    drawTimeline(v,latest);sizeFrames();
  }
  function drawTimeline(v,latest){
    const rows=[...latest.values()],origin=rows.length?Math.min(...rows.map(r=>r.started)):(v.fire_at||v.server_now);
    const finish=rows.length?Math.max(...rows.map(r=>r.finished??v.server_now)):origin;
    const span=Math.max(2.2,finish-origin+.12);
    q('#timeline-origin').textContent=rows.length?time(origin):'전송 대기';q('#timeline-end').textContent=rows.length?'+'+span.toFixed(2)+'초':'—';
    for(let i=1;i<=5;i++){
      const id=String(i),req=latest.get(id),track=q('#track-'+id);track.replaceChildren();
      if(!req){const empty=document.createElement('span');empty.className='timeline-empty';empty.textContent='요청 전';track.append(empty);q('#request-time-'+id).textContent='—';q('#request-outcome-'+id).textContent='대기';continue;}
      if(v.common_start!==null){const band=document.createElement('i');band.className='timeline-overlap';band.style.left=((v.common_start-origin)/span*100)+'%';band.style.width=((v.common_end-v.common_start)/span*100)+'%';track.append(band);}
      const bar=document.createElement('div');bar.className='request-bar '+(req.outcome==='account_blocked'?'denied':req.finished===null?'pending':'');bar.style.left=((req.started-origin)/span*100)+'%';bar.style.width=Math.max(.3,((req.finished??v.server_now)-req.started)/span*100)+'%';bar.title=`접수 ${time(req.started)} → ${req.finished?time(req.finished):'처리 중'}`;track.append(bar);
      q('#request-time-'+id).textContent=time(req.started);q('#request-outcome-'+id).textContent=req.finished===null?'처리 중':req.outcome==='account_blocked'?'403':req.outcome==='ok'?'200':'409';q('#request-outcome-'+id).className=req.outcome==='account_blocked'?'denied':'';
    }
  }
  async function poll(){if(busy||state&&(state.banned||state.phase==='stopped')&&state.requests.every(r=>r.finished!==null))return;busy=true;try{render(await api('dashboard'));}catch(e){error(e.message);}finally{busy=false;}}
  async function init(){
    try{const v=await api('clients');v.items.forEach(client=>{const box=q(`[data-client="${client.id}"] .client-viewport`),frame=document.createElement('iframe');frame.title=client.id+'번 전체 예매 페이지';frame.src=client.url;frame.setAttribute('loading','eager');box.append(frame);frame.addEventListener('load',()=>{box.querySelector('.client-loading').hidden=true;sizeFrames();});});new ResizeObserver(sizeFrames).observe(q('#parallel-grid'));await poll();}catch(e){error(e.message);}
  }
  qa('[data-focus]').forEach(b=>b.onclick=()=>focus(b.dataset.focus));document.addEventListener('keydown',e=>{if(e.key==='Escape'&&focused)focus(focused);});
  qa('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;qa('[data-view]').forEach(el=>{el.classList.toggle('active',el===b);el.setAttribute('aria-pressed',String(el===b));});sizeFrames();});
  q('#parallel-fire').onclick=async()=>{q('#parallel-fire').disabled=true;if(focused)focus(focused);try{await api('control',{action:'fire'});await poll();}catch(e){error(e.message);}};
  q('#parallel-stop').onclick=async()=>{try{await api('control',{action:'stop'});await poll();}catch(e){error(e.message);}};
  q('#parallel-new').onclick=async()=>{try{const r=await fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scene:'parallel'})});const v=await r.json();if(!r.ok)throw Error(v.error);location.assign(v.url);}catch(e){error(e.message);}};
  q('#parallel-details').onclick=()=>{q('#parallel-ban-evidence').replaceChildren(...state.ban.evidence.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));q('#parallel-ban').showModal();};q('#parallel-ban-close').onclick=q('#parallel-ban-ok').onclick=()=>q('#parallel-ban').close();
  init();setInterval(poll,160);addEventListener('resize',sizeFrames);
})();
