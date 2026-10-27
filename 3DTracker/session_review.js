/* Local, retrospective review. Original observations and live cursor are untouched. */
const $ = id => document.getElementById(id);
let selected=null, data=null, analysis=null, active=null, areas=[], drawing=null, selecting=false, requestID=0;
let heatCanvas=null, heatKey='';
async function api(path, options) {
  const response=await fetch(path,options), payload=await response.json();
  if (!response.ok) throw Error(payload.error || `HTTP ${response.status}`);
  return payload;
}
const post = (path,body) => api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function notice(text) { $('message').textContent=text; }
function showStatus(status) {
  active=status.active; $('start').disabled=!!active; $('stop').disabled=!active;
  if (active) notice('Recording. Stop to save the video; keep EyeCursor open.');
}
async function refreshDisplays() {
  const [list,config]=await Promise.all([api('/api/displays'),api('/api/config')]);
  $('display').replaceChildren(...list.map((item,index)=>{
    const o=document.createElement('option'); o.value=item.id;
    o.textContent=`Display ${item.id} · ${item.width}×${item.height}`;
    o.selected=item.id===config.default_display_id || !config.default_display_id && index===0;
    return o;
  }));
}
async function refreshSessions() {
  const list=await api('/api/sessions');
  $('sessions').replaceChildren(...list.map(item=>{
    const button=document.createElement('button'); button.className=`session ${selected===item.id?'active':''}`;
    button.textContent=new Date(item.created_at).toLocaleString();
    const detail=document.createElement('span'); detail.textContent=`${item.status} · display ${item.display.id}`;
    button.append(detail); button.onclick=()=>loadSession(item.id).catch(e=>notice(e.message)); return button;
  }));
}
async function loadSession(id) {
  const token=++requestID;
  const loaded=await api(`/api/sessions/${id}/data`);
  if(token!==requestID) return;
  selected=id; data=loaded; analysis=null; areas=[];
  try { areas=JSON.parse(localStorage.getItem(`gaze-areas:${id}`)||'[]'); } catch {}
  if(!Array.isArray(areas)) areas=[];
  areas=areas.filter(a=>[a.x0,a.x1,a.y0,a.y1].every(Number.isFinite));
  $('title').textContent=`Session ${new Date(data.manifest.created_at).toLocaleString()}`;
  $('video').src=`/api/sessions/${id}/video`;
  $('tracking').href=`/api/sessions/${id}/tracking`; $('tracking').hidden=false;
  $('from').value=0;
  $('to').value=((data.manifest.duration_ms || data.gaze.at(-1)?.t_ms || 0)/1000).toFixed(3);
  await review(); refreshSessions();
}
function span(text) { const node=document.createElement('span'); node.textContent=text; return node; }
async function review() {
  if(!selected) return;
  const start=Number($('from').value)*1000,end=Number($('to').value)*1000;
  if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start) { notice('Choose an end time after the start.'); return; }
  const token=++requestID; $('review').disabled=true;
  try {
    const result=await post('/api/review',{session_id:selected,start_ms:start,end_ms:end,dispersion_px:Number($('dispersion').value)});
    if(token!==requestID) return;
    analysis=result; heatKey='';
    $('stats').replaceChildren(...[
      `${(start/1000).toFixed(2)}–${(end/1000).toFixed(2)} s`,
      `${result.fixations.length} estimated fixations`,
      `${(result.summary.fixation_ms/1000).toFixed(2)} s fixation time`,
      `${result.summary.possible_glitches} possible glitches`,
      `${result.summary.excluded_samples} excluded samples`
    ].map(span));
    notice('Review ready. The path keeps original sample times; flagged samples remain in the recording.');
    renderAreas(); draw();
  } catch(e) { notice(e.message); }
  finally { if(token===requestID) $('review').disabled=false; }
}
function lowerBound(items,t,key='t_ms') {
  let lo=0,hi=items.length; while(lo<hi) { const m=(lo+hi)>>1; if(items[m][key]<t) lo=m+1; else hi=m; } return lo;
}
function nearest(items,t) {
  if(!items?.length) return null;
  const i=Math.min(items.length-1,lowerBound(items,t));
  return i && Math.abs(items[i-1].t_ms-t)<Math.abs(items[i].t_ms-t)?items[i-1]:items[i];
}
function buildHeat(w,h) {
  const radius=Math.max(5,Math.min(500,Number($('radius').value)||55));
  const key=`${requestID}:${radius}:${w}:${h}`;
  if(key===heatKey && heatCanvas) return heatCanvas;
  const gw=220,gh=Math.max(1,Math.round(gw*h/w)), values=new Float32Array(gw*gh);
  const sigma=Math.max(.5,radius*gw/w), reach=Math.ceil(sigma*3);
  for(const f of analysis.fixations) {
    const x=f.x*gw,y=f.y*gh,weight=f.duration_ms/1000;
    for(let j=Math.max(0,Math.floor(y-reach));j<Math.min(gh,y+reach);j++)
      for(let i=Math.max(0,Math.floor(x-reach));i<Math.min(gw,x+reach);i++)
        values[j*gw+i]+=weight*Math.exp(-((i-x)**2+(j-y)**2)/(2*sigma*sigma));
  }
  let maximum=0; for(const v of values) maximum=Math.max(maximum,v);
  heatCanvas=document.createElement('canvas'); heatCanvas.width=gw; heatCanvas.height=gh;
  const ctx=heatCanvas.getContext('2d'),image=ctx.createImageData(gw,gh);
  if(maximum) for(let i=0;i<values.length;i++) {
    const v=values[i]/maximum;
    image.data[i*4]=Math.round(255*Math.min(1,v*2));
    image.data[i*4+1]=Math.round(210*(1-v));
    image.data[i*4+2]=Math.round(150*(1-v));
    image.data[i*4+3]=Math.round(190*Math.min(1,v*3));
  }
  ctx.putImageData(image,0,0); heatKey=key; return heatCanvas;
}
function draw() {
  const video=$('video'),canvas=$('overlay'),w=video.videoWidth||1280,h=video.videoHeight||720;
  if(canvas.width!==w||canvas.height!==h) {canvas.width=w;canvas.height=h;}
  const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,w,h);
  if(!data || !analysis) return;
  const ms=video.currentTime*1000, scale=w/1280;
  if($('heatmap').checked) ctx.drawImage(buildHeat(w,h),0,0,w,h);
  // A short replay trail, not fabricated positions between camera observations.
  const points=analysis.points, from=lowerBound(points,ms-1500),end=lowerBound(points,ms+.001);
  if($('trail').checked || $('raw').checked) {
    let previous=null;
    for(let i=from;i<end;i++) {
      const p=points[i],ok=p.status==='measured',x=p.x*w,y=p.y*h;
      if(ok && $('trail').checked) {
        ctx.strokeStyle='#66d6e0';ctx.lineWidth=1.5*scale;
        if(previous && p.t_ms-previous.t_ms<=analysis.parameters.max_gap_ms) {
          ctx.beginPath();ctx.moveTo(previous.x*w,previous.y*h);ctx.lineTo(x,y);ctx.stroke();
        }
        ctx.fillStyle='#66d6e0';ctx.beginPath();ctx.arc(x,y,2.5*scale,0,Math.PI*2);ctx.fill();
      }
      if(!ok && $('raw').checked && p.x!==null && p.y!==null) {
        ctx.strokeStyle='#ff65c2';ctx.lineWidth=2*scale;ctx.beginPath();
        ctx.moveTo(x-5*scale,y-5*scale);ctx.lineTo(x+5*scale,y+5*scale);
        ctx.moveTo(x-5*scale,y+5*scale);ctx.lineTo(x+5*scale,y-5*scale);ctx.stroke();
      }
      previous=ok?p:null;
    }
  }
  const point=end?points[end-1]:null;
  if($('gaze').checked && point?.status==='measured' && ms-point.t_ms<100) {
    ctx.beginPath();ctx.arc(point.x*w,point.y*h,12*scale,0,Math.PI*2);
    ctx.lineWidth=2*scale;ctx.strokeStyle='white';ctx.stroke();
  }
  const frame=nearest(data.frames,ms);
  if($('cursor').checked && frame?.cursor_on_display && Math.abs(frame.t_ms-ms)<250) {
    const x=frame.cursor_nx*w,y=frame.cursor_ny*h;
    ctx.strokeStyle='#59d7ff';ctx.beginPath();ctx.moveTo(x-8,y);ctx.lineTo(x+8,y);ctx.moveTo(x,y-8);ctx.lineTo(x,y+8);ctx.stroke();
  }
  const rects=drawing?[...areas,drawing]:areas;
  rects.forEach((a,i)=>{
    ctx.strokeStyle='#ffe3a1';ctx.lineWidth=2*scale;
    ctx.strokeRect(a.x0*w,a.y0*h,(a.x1-a.x0)*w,(a.y1-a.y0)*h);
    ctx.font=`${14*scale}px sans-serif`;ctx.fillStyle='#ffe3a1';ctx.fillText(a.name||`Area ${i+1}`,a.x0*w+5,a.y0*h+18*scale);
  });
}
function areaStats(a) {
  const hits=(analysis?.fixations||[]).filter(f=>f.x>=a.x0 && f.x<=a.x1 && f.y>=a.y0 && f.y<=a.y1);
  return {name:a.name,bounds:[a.x0,a.y0,a.x1,a.y1],fixations:hits.length,
    dwell_ms:hits.reduce((s,f)=>s+f.duration_ms,0),first_fixation_ms:hits[0]?.start_ms??null};
}
function saveAreas() { if(selected) try {localStorage.setItem(`gaze-areas:${selected}`,JSON.stringify(areas));} catch {} }
function renderAreas() {
  $('areas').replaceChildren(...areas.map((a,i)=>{
    const row=document.createElement('div');row.className='area';
    const name=document.createElement('input');name.value=a.name;name.maxLength=60;name.setAttribute('aria-label',`Area ${i+1} name`);
    name.onchange=()=>{a.name=name.value;saveAreas();draw();};
    const stats=areaStats(a);const remove=document.createElement('button');remove.className='secondary';remove.textContent='Remove';
    remove.onclick=()=>{areas.splice(i,1);saveAreas();renderAreas();draw();};
    row.append(name,span(`${(stats.dwell_ms/1000).toFixed(2)} s center dwell`),span(`${stats.fixations} fixations`),remove);return row;
  }));
}
function selectionPoint(e) { const r=$('overlay').getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]; }
$('addArea').onclick=()=>{if(!analysis)return;selecting=!selecting;$('video').pause();$('screen').classList.toggle('selecting',selecting);notice(selecting?'Drag a box around a screen area. Keep the review range within a stable scene.':'Area selection cancelled.');};
$('overlay').onpointerdown=e=>{if(!selecting)return;const [x,y]=selectionPoint(e);drawing={x0:x,y0:y,x1:x,y1:y};$('overlay').setPointerCapture(e.pointerId);};
$('overlay').onpointermove=e=>{if(!drawing)return;[drawing.x1,drawing.y1]=selectionPoint(e);draw();};
$('overlay').onpointerup=e=>{
  if(!drawing)return;
  [drawing.x1,drawing.y1]=selectionPoint(e);
  const a=drawing;[a.x0,a.x1]=[Math.min(a.x0,a.x1),Math.max(a.x0,a.x1)];[a.y0,a.y1]=[Math.min(a.y0,a.y1),Math.max(a.y0,a.y1)];
  if(a.x1-a.x0>.005 && a.y1-a.y0>.005) {a.name=`Area ${areas.length+1}`;areas.push(a);}
  drawing=null;selecting=false;$('screen').classList.remove('selecting');saveAreas();renderAreas();draw();
};
$('overlay').onpointercancel=()=>{drawing=null;draw();};
$('clearAreas').onclick=()=>{areas=[];saveAreas();renderAreas();draw();};
$('export').onclick=()=>{
  if(!analysis)return;
  const report={...analysis,session_id:selected,manifest:data.manifest,areas:areas.map(areaStats),heatmap_radius_px:Number($('radius').value),
    area_interpretation:'Fixation-center dwell in static screen rectangles for this range. Overlapping rectangles can count the same fixation. No reading/comprehension inference.'};
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=`${selected}-review.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('start').onclick=async()=>{notice('Starting screen capture…');$('start').disabled=true;try {const s=await post('/api/start',{display_id:Number($('display').value)});showStatus({active:s.id});await refreshSessions();}catch(e){notice(e.message);$('start').disabled=false;}};
$('stop').onclick=async()=>{notice('Saving recording…');$('stop').disabled=true;try{const s=await post('/api/stop',{});showStatus({active:null});await refreshSessions();await loadSession(s.id);if(s.error)notice(s.error);}catch(e){notice(e.message);$('stop').disabled=false;}};
$('review').onclick=review;
$('markIn').onclick=()=>{$('from').value=$('video').currentTime.toFixed(3);};
$('markOut').onclick=()=>{$('to').value=$('video').currentTime.toFixed(3);};
['trail','heatmap','raw','cursor','gaze','radius'].forEach(id=>$(id).addEventListener('change',draw));
['timeupdate','seeked','loadedmetadata'].forEach(event=>$('video').addEventListener(event,draw));
if($('video').requestVideoFrameCallback) { const frame=()=>{draw();$('video').requestVideoFrameCallback(frame);};$('video').requestVideoFrameCallback(frame); }
Promise.all([refreshDisplays(),refreshSessions(),api('/api/status').then(showStatus)]).catch(e=>notice(e.message));
setInterval(()=>{if(active)refreshSessions().catch(()=>{});},4000);
