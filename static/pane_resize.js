(() => {
 const workspace=document.querySelector('.workspace'),analysis=workspace?.querySelector('.analysis-pane'),booking=workspace?.querySelector('.booking-pane'),chart=analysis?.querySelector('.chart-panel'),logs=analysis?.querySelector('.log-panel');
 if(!workspace||!analysis||!booking||!chart||!logs||workspace.dataset.resizable)return;
 workspace.dataset.resizable='true';
 const stylesheet=document.createElement('link');stylesheet.rel='stylesheet';stylesheet.href='/static/pane_resize.css';stylesheet.onload=setup;document.head.append(stylesheet);
 function setup(){
  const key='ticket-demo.pane-layout.v1';let settings={};try{settings=JSON.parse(localStorage.getItem(key)||'{}')||{};}catch(e){}if(typeof settings!=='object'||Array.isArray(settings))settings={};
  for(const axis of ['width','height'])if(!Number.isFinite(settings[axis]))delete settings[axis];
  const oldRows=getComputedStyle(analysis).gridTemplateRows.split(' ').map(parseFloat),defaultHeight=oldRows.length===2&&oldRows.every(Number.isFinite)?oldRows[0]/(oldRows[0]+oldRows[1]):.55;
  const vertical=separator('vertical','예매 화면과 분석 화면 너비 조절'),horizontal=separator('horizontal','그래프와 로그 높이 조절');
  workspace.insertBefore(vertical,analysis);analysis.insertBefore(horizontal,logs);workspace.classList.add('split-layout');
  let actual={width:.5,height:defaultHeight},drag=null,frame=null;
  const wide=()=>matchMedia('(min-width:751px)').matches;
  function separator(orientation,label){const el=document.createElement('div');el.className='pane-divider pane-divider-'+orientation;el.setAttribute('role','separator');el.setAttribute('aria-orientation',orientation);el.setAttribute('aria-label',label);el.tabIndex=0;el.title='드래그하여 크기 조절 · 더블클릭으로 초기화';return el;}
  function save(){try{localStorage.setItem(key,JSON.stringify(settings));}catch(e){}}
  function size(axis){if(axis==='height')return Math.max(1,analysis.getBoundingClientRect().height-10);const style=getComputedStyle(workspace);return Math.max(1,workspace.getBoundingClientRect().width-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-10);}
  function limits(axis){const space=size(axis),first=axis==='width'?280:180,second=axis==='width'?280:90;return {min:Math.min(.45,first/space),max:Math.max(.55,1-second/space)};}
  function render(){
   frame=null;vertical.hidden=!wide();vertical.tabIndex=wide()?0:-1;
   for(const axis of ['width','height']){const {min,max}=limits(axis);let preferred=settings[axis]??(axis==='width'?.5:defaultHeight);
    if(axis==='height'&&settings.height==null&&!document.querySelector('#path-view')?.hidden&&document.querySelector('#path-view'))preferred=Math.max(preferred,Math.min(.8,480/size(axis)));
    actual[axis]=Math.max(min,Math.min(max,preferred));const el=axis==='width'?vertical:horizontal;
    el.setAttribute('aria-valuemin',String(Math.round(min*100)));el.setAttribute('aria-valuemax',String(Math.round(max*100)));el.setAttribute('aria-valuenow',String(Math.round(actual[axis]*100)));el.setAttribute('aria-valuetext',Math.round(actual[axis]*100)+'%');
   }
   if(wide())workspace.style.gridTemplateColumns=`minmax(0,${actual.width}fr) 10px minmax(0,${1-actual.width}fr)`;else workspace.style.removeProperty('grid-template-columns');
   analysis.style.gridTemplateRows=`minmax(0,${actual.height}fr) 10px minmax(0,${1-actual.height}fr)`;
  }
  function schedule(){if(frame==null)frame=requestAnimationFrame(render);}
  function change(axis,value){const {min,max}=limits(axis);settings[axis]=Math.max(min,Math.min(max,value));render();}
  function finish(event){if(!drag||(event?.pointerId!=null&&event.pointerId!==drag.id))return;const previous=drag;drag=null;if(previous.el.hasPointerCapture(previous.id))previous.el.releasePointerCapture(previous.id);previous.el.classList.remove('dragging');document.body.classList.remove('resizing-panes','resizing-columns','resizing-rows');save();}
  for(const [el,axis] of [[vertical,'width'],[horizontal,'height']]){
   el.addEventListener('pointerdown',event=>{if(event.button!==0||(axis==='width'&&!wide()))return;event.preventDefault();el.focus();drag={el,axis,id:event.pointerId,start:axis==='width'?event.clientX:event.clientY,ratio:actual[axis],space:size(axis)};el.setPointerCapture(event.pointerId);el.classList.add('dragging');document.body.classList.add('resizing-panes',axis==='width'?'resizing-columns':'resizing-rows');});
   el.addEventListener('pointermove',event=>{if(!drag||drag.el!==el||drag.id!==event.pointerId)return;event.preventDefault();change(axis,drag.ratio+((axis==='width'?event.clientX:event.clientY)-drag.start)/drag.space);});
   el.addEventListener('pointerup',finish);el.addEventListener('pointercancel',finish);el.addEventListener('lostpointercapture',finish);
   el.addEventListener('dblclick',()=>{delete settings[axis];save();render();});
   el.addEventListener('keydown',event=>{const negative=axis==='width'?'ArrowLeft':'ArrowUp',positive=axis==='width'?'ArrowRight':'ArrowDown';if(event.key===negative||event.key===positive){event.preventDefault();change(axis,actual[axis]+(event.key===positive?1:-1)*(event.shiftKey?.05:.02));save();}else if(event.key==='Home'||event.key==='End'){event.preventDefault();const range=limits(axis);change(axis,event.key==='Home'?range.min:range.max);save();}else if(event.key==='Enter'){event.preventDefault();delete settings[axis];save();render();}});
  }
  window.addEventListener('blur',()=>finish());window.addEventListener('pagehide',()=>finish());
  new ResizeObserver(schedule).observe(workspace);new ResizeObserver(schedule).observe(analysis);
  const path=document.querySelector('#path-view');if(path)new MutationObserver(schedule).observe(path,{attributes:true,attributeFilter:['hidden']});
  render();
 }
})();
