window.PatternPlot={create({canvas,controls,tip,describe,onSelect,xLabel,yLabel}){
 const ctx=canvas.getContext('2d');let points=[],drawn=[],view={x:0,y:0,w:105,h:105},drag=null,moved=false;
 const bounds=()=>{view.w=Math.max(.00001,Math.min(105,view.w));view.h=Math.max(.00001,Math.min(105,view.h));view.x=Math.max(0,Math.min(105-view.w,view.x));view.y=Math.max(0,Math.min(105-view.h,view.y));};
 const reference=p=>p.measurement_origin==='synthetic_fixture';
 const num=(n,s)=>Number(n.toFixed(Math.min(7,Math.max(0,2-Math.floor(Math.log10(s)))))).toString();
 function draw(){
  const {width:w,height:h}=canvas.getBoundingClientRect();if(!w||!h)return;const d=devicePixelRatio||1;canvas.width=w*d;canvas.height=h*d;ctx.setTransform(d,0,0,d,0,0);
  const m={l:58,r:24,t:28,b:40},pw=w-m.l-m.r,ph=h-m.t-m.b;if(ph<=0)return;ctx.font='11px Arial,"Malgun Gothic",sans-serif';
  for(let i=0;i<=4;i++){const x=m.l+pw*i/4,y=m.t+ph-ph*i/4;ctx.strokeStyle='#edf0f5';ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t+ph);ctx.moveTo(m.l,y);ctx.lineTo(m.l+pw,y);ctx.stroke();ctx.fillStyle='#8492a6';ctx.textAlign='center';ctx.fillText(num(view.x+view.w*i/4,view.w),x,m.t+ph+16);ctx.textAlign='right';ctx.fillText(num(view.y+view.h*i/4,view.h),m.l-8,y+4);}
  ctx.strokeStyle='#adb8c7';ctx.beginPath();ctx.moveTo(m.l,m.t);ctx.lineTo(m.l,m.t+ph);ctx.lineTo(m.l+pw,m.t+ph);ctx.stroke();ctx.fillStyle='#586d89';ctx.textAlign='left';ctx.fillText(yLabel,m.l,13);ctx.textAlign='right';ctx.fillText(xLabel,m.l+pw,h-4);
  drawn=[];for(const p of points){if(p.speed_score<view.x||p.speed_score>view.x+view.w||p.pattern_score<view.y||p.pattern_score>view.y+view.h)continue;const x=m.l+pw*(p.speed_score-view.x)/view.w,y=m.t+ph-ph*(p.pattern_score-view.y)/view.h;ctx.beginPath();ctx.fillStyle=reference(p)?'#111':p.actor_kind==='ai'?'#df3348':'#2676e8';ctx.arc(x,y,reference(p)?1.3:2.6,0,Math.PI*2);ctx.fill();drawn.push({p,x,y});}
 }
 function zoom(f,at){at=at||{x:view.x+view.w/2,y:view.y+view.h/2};view={x:at.x+(view.x-at.x)*f,y:at.y+(view.y-at.y)*f,w:view.w*f,h:view.h*f};bounds();draw();}
 for(const [label,title,fn] of [['＋','그래프 확대',()=>zoom(.5)],['−','그래프 축소',()=>zoom(2)],['전체','전체 보기',()=>{view={x:0,y:0,w:105,h:105};draw();}]]){const b=document.createElement('button');b.textContent=label;b.title=title;b.onclick=fn;controls.append(b);}
 function nearest(e){const r=canvas.getBoundingClientRect();let best=null,d=12;for(const p of drawn){const z=Math.hypot(p.x-(e.clientX-r.left),p.y-(e.clientY-r.top));if(z<d){best=p;d=z;}}return best;}
 canvas.onpointermove=e=>{if(drag){const r=canvas.getBoundingClientRect();view.x=drag.view.x-(e.clientX-drag.x)/(r.width-82)*view.w;view.y=drag.view.y+(e.clientY-drag.y)/(r.height-68)*view.h;moved=true;bounds();draw();return;}const p=nearest(e);tip.hidden=!p;canvas.style.cursor=p?'pointer':'grab';if(p){tip.textContent=describe(p.p);tip.style.left=Math.max(4,Math.min(p.x+8,canvas.clientWidth-265))+'px';tip.style.top=Math.max(0,Math.min(p.y+5,canvas.clientHeight-95))+'px';}};
 canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,view:{...view}};moved=false;canvas.setPointerCapture(e.pointerId);};canvas.onpointerup=e=>{drag=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);};canvas.onpointerleave=()=>tip.hidden=true;canvas.onclick=e=>{if(!moved){const p=nearest(e);if(p)onSelect(p.p);}};
 canvas.addEventListener('wheel',e=>{e.preventDefault();const r=canvas.getBoundingClientRect();zoom(e.deltaY<0?.65:1/.65,{x:view.x+(e.clientX-r.left-58)/(r.width-82)*view.w,y:view.y+(1-(e.clientY-r.top-28)/(r.height-68))*view.h});},{passive:false});
 new ResizeObserver(draw).observe(canvas.parentElement);return {set(data){points=data;draw();},reset(){view={x:0,y:0,w:105,h:105};tip.hidden=true;draw();}};
}};
