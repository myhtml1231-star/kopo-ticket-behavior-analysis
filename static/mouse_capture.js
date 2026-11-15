(() => {
 if(!window.RETRY_CONTEXT)return;
 let active=false,kind='human',points=[],lastSend=0;
 function point(x,y,t=performance.now()){
  if(!active)return;
  if(points.length&&t<=points.at(-1).t)return;
  points.push({x,y,t});if(points.length>2048)points.splice(0,points.length-2048);
  if(t-lastSend>35){lastSend=t;send();}
 }
 function send(){if(parent!==window)parent.postMessage({type:'mouse-path-preview',actor_kind:kind,path:points.map(p=>({...p,t:p.t-(points[0]?.t||0)}))},location.origin);}
 window.mouseCapture={
  start(k){active=true;kind=k;points=[];},stop(){active=false;},reset(){points=[];},point,
  consume(){send();const first=points[0]?.t||0;const result=points.map(p=>({x:p.x,y:p.y,t:p.t-first}));points=[];return result;}
 };
 document.addEventListener('pointermove',e=>{if(active&&kind==='human'&&e.isTrusted)point(e.clientX,e.clientY);},{capture:true});
 document.addEventListener('pointerdown',e=>{if(!active||kind!=='human')return;if(!e.target.closest('[data-seat]'))points=[];point(e.clientX,e.clientY);},{capture:true});
})();
