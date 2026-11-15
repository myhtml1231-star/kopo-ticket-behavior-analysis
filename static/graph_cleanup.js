// Display-only cleanup: never deletes stored measurements or reference samples.
window.GraphCleanup={create(key,isReference){
 let hidden;
 try{hidden=new Set(JSON.parse(localStorage.getItem(key)||'[]'));}catch(e){hidden=new Set();}
 return {
  keep(point){return isReference(point)||!hidden.has(point.id);},
  clear(points){
   for(const point of points)if(!isReference(point))hidden.add(point.id);
   try{localStorage.setItem(key,JSON.stringify([...hidden]));}catch(e){}
  }
 };
},mountLog({key,items,onChange}){
 const view=GraphCleanup.create(key,()=>false),header=document.querySelector('.log-panel>header');let button=null;
 if(header){button=document.createElement('button');button.id='log-clear';button.className='log-clear-button';button.textContent='화면 로그 비우기';button.title='화면 로그만 비우기 · 저장 기록 유지';button.disabled=true;button.onclick=()=>{view.clear(items());onChange();};header.insertBefore(button,document.querySelector('#delivery'));}
 return {...view,sync(){if(button)button.disabled=!items().some(point=>view.keep(point));}};
}};
