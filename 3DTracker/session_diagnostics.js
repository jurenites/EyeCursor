/* Camera frames and detector rows share capture timestamps, not playback timers. */
let playhead=0, playing=false, lastTick=0, hasScreen=false, allFrameTimes=[], lastFinished=null;
const streams=['left','right','face','face_secondary'];
function replayTime() { return hasScreen ? $('video').currentTime*1000 : playhead; }
function duration() { return data?.manifest.duration_ms||0; }
function clockLabel(ms) {
  const n=Math.max(0,Math.round(ms));
  return `${String(Math.floor(n/60000)).padStart(2,'0')}:${String(Math.floor(n/1000)%60).padStart(2,'0')}.${String(n%1000).padStart(3,'0')}`;
}
function pauseReplay() { playing=false;$('video').pause();$('play').textContent='Play'; }
function seekReplay(ms) {
  playhead=Math.max(0,Math.min(duration(),Number(ms)||0));
  if(hasScreen) $('video').currentTime=playhead/1000;
  renderCameras(playhead);draw();
}
function setupDiagnosticReplay() {
  $('gazeReview').hidden=!data.manifest.display;
  pauseReplay();playhead=0;$('screen').classList.remove('seeking');
  hasScreen=data.manifest.has_screen ?? !!data.manifest.display;
  $('screen').hidden=!hasScreen;
  if(hasScreen) $('video').src=`/api/sessions/${selected}/video`;
  else {$('video').removeAttribute('src');$('video').load();}
  const available=streams.some(side=>data.cameras?.[side]?.length);
  $('diagnosticReplay').hidden=!data.manifest.schema?.startsWith('eyecursor.diagnostics') && !available;
  $('cameraGrid').replaceChildren(...streams.map(side=>{
    const panel=document.createElement('div');panel.className='camera';panel.id=`panel-${side}`;
    const title=document.createElement('h3');title.textContent={left:'Left IR eye',right:'Right IR eye',face:'Laptop webcam',face_secondary:'Second face webcam'}[side];
    const box=document.createElement('div');box.className='image';
    const image=document.createElement('img');image.id=`image-${side}`;image.alt=title.textContent;
    const missing=document.createElement('div');missing.id=`missing-${side}`;missing.className='missing';
    box.append(image,missing);
    const timing=document.createElement('div');timing.className='timing';timing.id=`timing-${side}`;
    const values=document.createElement('pre');values.id=`values-${side}`;
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Full frame measurements';
    const raw=document.createElement('pre');raw.id=`json-${side}`;details.append(summary,raw);
    panel.append(title,box,timing,values,details);return panel;
  }));
  const summary=data.manifest.cameras||{};
  const dropped=Object.values(summary.dropped||{}).reduce((a,b)=>a+b,0);
  $('captureInfo').textContent=`Each image is paired with its own detection values. Software timestamps; cameras are not hardware synchronized. ${dropped} frames dropped by the recording writer.${data.manifest.error?' '+data.manifest.error:''}`;
  $('allLogs').href=`/api/sessions/${selected}/data`;
  $('cameraArchive').href=`/api/sessions/${selected}/camera-archive`;
  $('cameraArchive').hidden=!available;
  allFrameTimes=[...new Set(streams.flatMap(side=>(data.cameras?.[side]||[]).map(r=>r.t_ms)))].sort((a,b)=>a-b);
  $('timeline').max=duration();
  ['timeline','play','previousFrame','nextFrame','seekTime'].forEach(id=>$(id).disabled=!duration());
  $('review').disabled=!hasScreen;
  renderCameras(0);
}
const numberText=v=>typeof v==='number'?v.toFixed(3):'—';
const vectorText=v=>Array.isArray(v)?v.map(numberText).join(', '):'—';
function renderCameras(ms=replayTime()) {
  if(!data)return;
  $('timeline').value=ms;$('playTime').textContent=clockLabel(ms);
  if(document.activeElement!==$('seekTime'))$('seekTime').value=(ms/1000).toFixed(3);
  for(const side of streams) {
    const image=$(`image-${side}`);if(!image)continue;
    const row=nearest(data.cameras?.[side],ms);
    const present=row && Math.abs(row.t_ms-ms)<=150;
    const missing=$(`missing-${side}`);missing.hidden=!!present;image.hidden=!present || image.dataset.loaded!==image.getAttribute('src');
    missing.textContent=row?'No captured frame at this time':'No frames recorded';
    $(`timing-${side}`).textContent=present?`Frame ${row.frame} · ${clockLabel(row.t_ms)}\nOffset from playhead: ${(row.t_ms-ms).toFixed(1)} ms`:'—';
    if(!present) { $(`values-${side}`).textContent='No measurement';$(`json-${side}`).textContent='';continue; }
    const name=$('overlays').checked?row.preview:row.raw;
    const url=`/api/sessions/${selected}/image/${name}`;
    if(image.getAttribute('src')!==url) {
      image.hidden=true;
      image.onload=()=>{image.dataset.loaded=url;renderCameras();};
      image.onerror=()=>{image.hidden=true;missing.hidden=false;missing.textContent='Image unavailable';};
      image.src=url;
    }
    const values=row.values||{},d=values.detector||{},ellipse=d.pupil_ellipse||{};
    $(`values-${side}`).textContent=side.startsWith('face')
      ? `Head pose: ${values.packet?.pose?'detected':'unavailable'}\nProcessing: ${numberText(values.packet?.processing_ms)} ms\nYaw / pitch / roll: ${vectorText(values.packet?.pose?.features?.slice(0,3).map(v=>v*180/Math.PI))}°`
      : `${values.accepted?'Accepted':'Rejected / unavailable'} · confidence ${numberText(d.confidence)}\nThreshold: ${numberText(values.threshold)}\nPupil center: ${vectorText(ellipse.center)} px\nEllipse axes: ${vectorText(ellipse.axes)} px\nEllipse rotation: ${numberText(ellipse.angle_degrees)}°\nEye vector: ${vectorText(d.gaze_direction)}\nDecision: ${d.temporal_tracking?.reason||d.pupil_shape_source||'—'}`;
    $(`json-${side}`).textContent=JSON.stringify(row,null,2);
  }
}
function stepFrame(direction) {
  pauseReplay();const now=replayTime();
  let i=lowerBound(allFrameTimes,now+(direction>0?.01:-.01));
  if(direction<0)i--;
  seekReplay(allFrameTimes[Math.max(0,Math.min(allFrameTimes.length-1,i))]??now+direction*1000/30);
}
$('play').onclick=async()=>{
  if(playing){pauseReplay();return;}
  if(replayTime()>=duration()-1)seekReplay(0);
  playing=true;lastTick=performance.now();$('play').textContent='Pause';
  if(hasScreen)try{await $('video').play();}catch(e){pauseReplay();notice(e.message);}
};
$('timeline').oninput=()=>{pauseReplay();seekReplay($('timeline').value);};
$('seekTime').oninput=()=>{pauseReplay();seekReplay(Number($('seekTime').value)*1000);};
$('previousFrame').onclick=()=>stepFrame(-1);$('nextFrame').onclick=()=>stepFrame(1);
$('overlays').onchange=()=>renderCameras();
$('video').addEventListener('ended',pauseReplay);
$('video').addEventListener('seeking',()=>{$('screen').classList.add('seeking');});
$('video').addEventListener('seeked',()=>{$('screen').classList.remove('seeking');renderCameras();});
function tick(now) {
  if(playing) {
    if(!hasScreen)playhead=Math.min(duration(),playhead+now-lastTick);
    renderCameras();draw();
    if(replayTime()>=duration())pauseReplay();
  }
  lastTick=now;requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
$('moment').onclick=()=>{
  if(!data)return;
  const ms=replayTime(),report={session_id:selected,requested_t_ms:ms,time:clockLabel(ms),
    note:'Observed detection values, not a known gaze target. Nearby rows retain their own capture timestamps.',
    manifest:data.manifest,cameras:Object.fromEntries(streams.map(side=>[side,(data.cameras?.[side]||[]).filter(r=>Math.abs(r.t_ms-ms)<=500)])),
    gaze:data.gaze.filter(r=>Math.abs(r.t_ms-ms)<=500)};
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=`${selected}-${Math.round(ms)}ms.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  notice(`Exported ${clockLabel(ms)} with measurements from half a second before and after.`);
};
$('includeScreen').onchange=async()=>{
  $('displayChoice').hidden=!$('includeScreen').checked;
  if($('includeScreen').checked)try{await refreshDisplays();}catch(e){notice(e.message);$('includeScreen').checked=false;$('displayChoice').hidden=true;}
};
let polling=false;
async function pollStatus() {
  if(polling)return;polling=true;
  try {
    const status=await api('/api/status'),wasActive=active;
    showStatus(status);
    if(wasActive && !status.active && status.last_finished && lastFinished!==status.last_finished) {
      lastFinished=status.last_finished;await loadSession(lastFinished);
    }
  }catch(e){if(active)notice('Recorder connection interrupted. Keep EyeCursor open.');}
  finally{polling=false;}
}
async function openLatestRecording() {
  await pollStatus();
  const list=await refreshSessions();
  if(!active && list[0] && ['complete','partial'].includes(list[0].status)) await loadSession(list[0].id);
}
openLatestRecording().catch(e=>notice(e.message));
setInterval(pollStatus,1000);
