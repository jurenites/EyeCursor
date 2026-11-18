"""Local synchronized camera, screen and measurement recorder for EyeCursor."""

import argparse
import base64
import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import threading
import time
from urllib.request import urlopen, Request
from functools import lru_cache
import zipfile
from uuid import uuid4
from gaze_review import analyze
from calibration_log import numeric
from diagnostic_snapshot import compact_state, compact_record
from binocular_calibration import shared_fixation


ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
HELPER = ROOT / ".venv" / "bin" / "eyetracker-screen-recorder"
PAGE = Path(__file__).with_name("session_recorder.html")
TRACKER = "http://127.0.0.1:8765/state"
SAMPLE_INTERVAL = 1 / 30
SESSION_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")
SAMPLE_HZ = 24
GROUP_SIZE = 24
_service = None
_manager = None
_service_lock = threading.Lock()
_helper_lock = threading.Lock()


def ensure_helper():
    source = PAGE.with_name('screen_recorder.swift')
    with _helper_lock:
        if not HELPER.exists() or HELPER.stat().st_mtime < source.stat().st_mtime:
            cache = ROOT/'.venv/swift-cache'
            cache.mkdir(parents=True,exist_ok=True)
            subprocess.run(['/usr/bin/swiftc','-parse-as-library','-module-cache-path',str(cache),
                            str(source),'-o',str(HELPER)],check=True,capture_output=True)


def open_service(tracker_port=8765):
    global _service,_manager,TRACKER
    with _service_lock:
        TRACKER = f'http://127.0.0.1:{tracker_port}/state'
        if _service is None:
            try:
                manager = SessionManager()
                _service = ThreadingHTTPServer(('127.0.0.1',8766),make_handler(manager))
                _manager = manager
            except OSError:
                with urlopen('http://127.0.0.1:8766/api/config',timeout=1) as response:
                    config=json.load(response)
                if config.get('service')!='eyecursor-review-v1' or config.get('tracker')!=TRACKER:
                    raise ValueError('Recording port 8766 is already in use')
                return
            threading.Thread(target=_service.serve_forever,name='gaze-review',daemon=True).start()


def close_service():
    global _service,_manager
    with _service_lock:
        if _manager and _manager.active: _manager.stop()
        if _service:
            _service.shutdown(); _service.server_close()
        _service = None; _manager = None


def research_sample(state, display=None):
    """Use unbounded measured positions, never fenced/held desktop dots."""
    flow = state.get('onboarding') or {}
    learning = (flow.get('phase') in ('waiting','fitting','head','screen','motion','verify','refine')
                or (flow.get('cursor_calibration') or {}).get('active',False))
    predictions = state.get('raw_eye_predictions')
    confidence = state.get('confidence',0)
    stamp = state.get('gaze_capture_time')
    capture_id = str(stamp) if stamp is not None else None
    if state.get('mode') == 'hybrid' and predictions is not None:
        mode = state.get('gaze_eye_mode','both')
        detection_eyes = (state.get('eye_cameras') or {}).get('eyes',{})
        measured = {side:row for side,row in predictions.items()
                    if not row.get('held') and (mode=='both' or side==mode)
                    and detection_eyes.get(side,{}).get('measurement_valid',True)}
        gaze = shared_fixation(measured)['uv']
        confidence = min((r.get('confidence',0) for r in measured.values()),default=0)
        capture_id = '|'.join(f"{s}:{r.get('captured_at')}" for s,r in sorted(measured.items())) or None
        stamp = max((r.get('captured_at',0) for r in measured.values()),default=None)
    else:
        gaze = state.get('unclamped_gaze') or state.get('raw_gaze',state.get('gaze')) if state.get('valid') else None
    viewport = state.get('tracking_viewport')
    if gaze is not None and display is not None:
        if viewport is None:
            gaze = None  # A display-local coordinate cannot be assigned to another monitor.
        else:
            x,y,w,h = viewport
            gaze = [(x+gaze[0]*w-display['x'])/display.get('point_width',display['width']),
                    (y+gaze[1]*h-display['y'])/display.get('point_height',display['height'])]
    return dict(valid=gaze is not None,x=gaze[0] if gaze is not None else None,
                y=gaze[1] if gaze is not None else None,confidence=confidence,
                capture_id=capture_id,captured_at=stamp,learning=bool(learning),
                raw_eyes=predictions,detection_eyes=(state.get('eye_cameras') or {}).get('eyes'),
                displayed_gaze=state.get('desktop_gaze'),
                binocular_status=state.get('binocular_status'),evidence=state.get('detection_evidence'))


def session_data(folder):
    manifest = json.loads((folder/'session.json').read_text())
    # Full original observations retain confidence and native capture identity.
    if (folder/'gaze.jsonl').exists():
        return dict(manifest=manifest,gaze=load_gaze(folder/'gaze.jsonl'),frames=load_lines(folder/'frames.jsonl'),
                    cameras={side:load_lines(folder/f'{side}-frames.jsonl') for side in ('left','right','face','face_secondary')},
                    initial_state=compact_state(json.loads((folder/'initial-state.json').read_text())) if (folder/'initial-state.json').exists() else None,
                    presentation=load_lines(folder/'presentation.jsonl'))
    saved = json.loads((folder/'tracking.json').read_text())
    return expand_tracking(saved,manifest) if saved.get('schema')=='eyetracker.tracking.v2' else saved


def tracker_command(action, body):
    request = Request(TRACKER.removesuffix('/state')+'/diagnostics/'+action,
                      data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=30) as response: return json.load(response)


@lru_cache(maxsize=6)
def camera_archive(folder):
    # Only completed sessions are opened, so the central directory is immutable.
    return zipfile.ZipFile(Path(folder)/'camera-frames.zip')


@lru_cache(maxsize=1)
def replay_data(session_id):
    if not SESSION_ID.fullmatch(session_id): raise ValueError('Invalid recording')
    data=session_data(RECORDINGS/session_id)
    if data['manifest'].get('status') not in ('complete','partial'): raise ValueError('Stop recording before replay')
    groups={**data.get('cameras',{}),'state':data['gaze'],'presentation':data.get('presentation',[])}
    for key,rows in groups.items(): groups[key]=sorted(rows,key=lambda row:row['t_ms'])
    return data,groups,{key:[r['t_ms'] for r in rows] for key,rows in groups.items()}


def replay_timeline(session_id):
    data,groups,times=replay_data(session_id)
    return dict(id=session_id,duration_ms=data['manifest'].get('duration_ms',0),
                frames=sorted(set(t for side in ('left','right','face','face_secondary') for t in times.get(side,[]))),
                has_scene=any(row.get('tracker_state') for row in groups['state']))


def replay_frame(session_id,ms):
    if not math.isfinite(ms): raise ValueError('Invalid replay time')
    data,groups,times=replay_data(session_id)
    ms=max(0,min(data['manifest'].get('duration_ms',0),ms))
    images={};camera_times={}
    for side in ('left','right','face','face_secondary'):
        row=nearest_sample(groups.get(side,[]),times.get(side,[]),ms,150)
        if row:
            images[side]=base64.b64encode(camera_archive(str(RECORDINGS/session_id)).read(row['preview'])).decode('ascii')
            camera_times[side]=row['t_ms']
    state=nearest_sample(groups['state'],times['state'],ms,150)
    shown=nearest_sample(groups['presentation'],times['presentation'],ms,150)
    return dict(t_ms=ms,images=images,camera_times=camera_times,
                state=state.get('tracker_state') if state else None,
                cursors=shown.get('cursors',{}) if shown else {},
                scene=shown.get('scene',{}) if shown else {})


def read_state():
    with urlopen(TRACKER, timeout=0.7) as response:
        return json.load(response)


def displays():
    ensure_helper()
    completed = subprocess.run([str(HELPER), "--list"], capture_output=True, text=True, timeout=15)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Could not list displays")
    return [json.loads(line) for line in completed.stdout.splitlines()]


def load_lines(path, transform=None):
    if not path.exists():
        return []
    with path.open() as stream:
        return [(transform(json.loads(line)) if transform else json.loads(line))
                for line in stream if line.strip()]


def load_gaze(path):
    # Replay states are immutable. Share unchanged beam history instead of
    # retaining hundreds of copies while loading older verbose recordings.
    previous_rays = None
    def snapshot(row):
        nonlocal previous_rays
        row = compact_record(row)
        onboarding = (row.get('tracker_state') or {}).get('onboarding') or {}
        rays = onboarding.get('calibration_rays')
        if rays is not None:
            if rays == previous_rays:
                onboarding['calibration_rays'] = previous_rays
            else:
                previous_rays = rays
        return row
    return load_lines(path, snapshot)


def nearest_sample(samples, times, target_ms, max_distance_ms):
    if not samples:
        return None
    index = bisect_left(times, target_ms)
    candidates = [samples[position] for position in (index - 1, index)
                  if 0 <= position < len(samples)]
    nearest = min(candidates, key=lambda item: abs(item["t_ms"] - target_ms))
    return nearest if abs(nearest["t_ms"] - target_ms) <= max_distance_ms else None


def compact_tracking(manifest, gaze, frames):
    """Resample onto the video timeline and anchor every 24 coordinates in UTC."""
    gaze = sorted(gaze, key=lambda item: item["t_ms"])
    frames = sorted(frames, key=lambda item: item["t_ms"])
    gaze_times = [item["t_ms"] for item in gaze]
    frame_times = [item["t_ms"] for item in frames]
    end_ms = max(gaze_times[-1] if gaze_times else 0,
                 frame_times[-1] if frame_times else 0)
    sample_count = int(end_ms * SAMPLE_HZ / 1000) + 1 if gaze or frames else 0
    groups = []
    for first in range(0, sample_count, GROUP_SIZE):
        start_ms = first * 1000 / SAMPLE_HZ
        absolute_ns = manifest["started_at_unix_ns"] + round(start_ms * 1_000_000)
        utc = datetime.fromtimestamp(absolute_ns / 1_000_000_000, timezone.utc)
        group = {"utc": utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "video_ms": round(start_ms, 3), "gaze_xy": [], "cursor_xy": []}
        for index in range(first, min(first + GROUP_SIZE, sample_count)):
            target_ms = index * 1000 / SAMPLE_HZ
            eye = nearest_sample(gaze, gaze_times, target_ms, 75)
            group["gaze_xy"].append([round(eye["x"], 4), round(eye["y"], 4)]
                                    if eye and eye.get("valid") and eye.get("x") is not None
                                    and eye.get("y") is not None else None)
            frame_index = bisect_right(frame_times, target_ms) - 1
            cursor = frames[frame_index] if frame_index >= 0 else None
            group["cursor_xy"].append([round(cursor["cursor_nx"], 4),
                                       round(cursor["cursor_ny"], 4)]
                                      if cursor and cursor.get("cursor_on_display") else None)
        groups.append(group)
    return {"schema": "eyetracker.tracking.v2", "sample_hz": SAMPLE_HZ,
            "group_size": GROUP_SIZE, "coordinate_space": "normalized display",
            "groups": groups}


def expand_tracking(compact, manifest):
    """Decode grouped coordinates for the existing replay UI."""
    rate = compact["sample_hz"]
    gaze, frames = [], []
    for group in compact["groups"]:
        for index, (eye, cursor) in enumerate(zip(group["gaze_xy"], group["cursor_xy"])):
            time_ms = group["video_ms"] + index * 1000 / rate
            gaze.append({"t_ms": time_ms, "valid": eye is not None,
                         "x": eye[0] if eye else None, "y": eye[1] if eye else None})
            frames.append({"t_ms": time_ms, "cursor_on_display": cursor is not None,
                           "cursor_nx": cursor[0] if cursor else None,
                           "cursor_ny": cursor[1] if cursor else None})
    return {"manifest": manifest, "gaze": gaze, "frames": frames}


def saved_sessions():
    """Only recorder-owned directories; never follow links when replacing a session."""
    result=[]
    for folder in RECORDINGS.glob('*'):
        if folder.is_symlink() or not folder.is_dir() or not SESSION_ID.fullmatch(folder.name):
            continue
        try:
            manifest=json.loads((folder/'session.json').read_text())
            if manifest.get('id')==folder.name: result.append(manifest)
        except (OSError,ValueError):
            continue
    return sorted(result,key=lambda row:row['id'],reverse=True)


def replace_previous_sessions(current_id):
    camera_archive.cache_clear()
    replay_data.cache_clear()
    errors=[]
    for row in saved_sessions():
        if row['id']==current_id: continue
        try: shutil.rmtree(RECORDINGS/row['id'])
        except OSError as error: errors.append(str(error))
    return errors


class SessionManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = None

    def status(self):
        with self.lock:
            active = self.active
            return {"active": active["id"] if active else None,
                    "started_at": active["started_at"] if active else None,
                    "elapsed_seconds": min(60,(active.get("paused_at") or time.monotonic())-active["origin"]) if active else 0,
                    "paused": bool(active and active.get("paused_at")),
                    "last_finished": getattr(self,'last_finished',None)}

    def start(self, display_id=0):
        with self.lock:
            if self.active: raise ValueError("A session is already recording")
            state = read_state()
            selected = None
            if display_id:
                selected = next((item for item in displays() if item['id']==display_id),None)
                if not selected: raise ValueError('Choose a connected display')
            session_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:8]
            folder = RECORDINGS/session_id
            folder.mkdir(parents=True)
            process = None
            started = {'epoch_ns':time.time_ns()}
            try:
                if selected:
                    process = subprocess.Popen([str(HELPER),'--record',str(display_id),
                        str(folder/'screen.mp4'),str(folder/'frames.jsonl')],stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout,selectors.EVENT_READ)
                        ready = selector.select(timeout=15)
                    if not ready: raise RuntimeError('Screen capture did not start within 15 seconds')
                    line = process.stdout.readline()
                    if not line: raise RuntimeError(process.stderr.read().strip() or 'Screen capture did not start')
                    started = json.loads(line)
                    if started.get('type')!='start': raise RuntimeError('Invalid screen capture start event')
                # Bridge first screen PTS (wall clock) to the tracker process's
                # shared OS monotonic clock. Subsequent timing never uses wall-clock deltas.
                origin = time.monotonic()+(started['epoch_ns']-time.time_ns())/1e9
            except Exception:
                if process and process.poll() is None:
                    process.kill(); process.wait(timeout=3)
                raise
            manifest = dict(id=session_id,created_at=datetime.now(timezone.utc).isoformat(),
                schema='eyecursor.diagnostics.v1',display=selected,has_screen=bool(selected),
                started_at_unix_ns=started['epoch_ns'],origin_monotonic=origin,
                tracker_source=state.get('source'),status='recording',max_seconds=60,
                time_unit='milliseconds from session origin (first screen PTS when enabled)',
                camera_timing='Software capture timestamps; independent cameras, no hardware sync',
                detector_coordinates='640 x 480 center-cropped/resized eye image, after configured rotation',
                gaze_timing='State observation time; native capture identity retained separately',
                gaze_source='Unbounded measured eye maps; held display values excluded',gaze_sample_hz=30)
            try:
                manifest['project_build_at_recording']=json.loads((ROOT/'version.json').read_text())
                (folder/'session.json').write_text(json.dumps(manifest,indent=2)+'\n')
                (folder/'initial-state.json').write_text(json.dumps(state,indent=2)+'\n')
                tracker_command('record-start',dict(session_id=session_id,origin_monotonic=origin))
            except Exception:
                if process and process.poll() is None:process.kill();process.wait(timeout=3)
                try:tracker_command('record-stop',dict(session_id=session_id))
                except Exception:pass
                manifest.update(status='failed',error='Recording could not start')
                try:(folder/'session.json').write_text(json.dumps(manifest,indent=2)+'\n')
                except OSError:pass
                raise
            active = dict(id=session_id,folder=folder,process=process,started_at=manifest['created_at'],
                          epoch_ns=started['epoch_ns'],origin=origin,display=selected,stop=threading.Event(),paused_at=None)
            # Replacement is committed only after both capture startup steps
            # succeeded. Failed permission/camera startup preserves the old clip.
            cleanup_errors=replace_previous_sessions(session_id)
            if cleanup_errors:
                manifest['retention_warning']='Could not remove previous recording: '+'; '.join(cleanup_errors)
                (folder/'session.json').write_text(json.dumps(manifest,indent=2)+'\n')
            self.last_finished=None
            active['presentation']=(folder/'presentation.jsonl').open('w',buffering=1)
            self.active=active
            active['sampler']=threading.Thread(target=self._sample_gaze,args=(active,),daemon=True)
            active['sampler'].start()
            active['timer']=threading.Timer(max(0,60-(time.monotonic()-origin)),self._auto_stop,args=(session_id,))
            active['timer'].daemon=True;active['timer'].start()
            return manifest

    def pause(self, paused):
        with self.lock:
            active=self.active
            if not active: raise ValueError('No recording is active')
            if active['display']: raise ValueError('Pause is available for camera recordings without a monitor video')
            if bool(active.get('paused_at')) == paused: return self.status()
            stamp=time.monotonic()
            tracker_command('record-pause',dict(session_id=active['id'],paused=paused,at=stamp))
            active['timer'].cancel()
            if paused: active['paused_at']=stamp
            else:
                active['origin']+=stamp-active['paused_at'];active['paused_at']=None
                active['timer']=threading.Timer(max(0,60-(stamp-active['origin'])),self._auto_stop,args=(active['id'],))
                active['timer'].daemon=True;active['timer'].start()
            return self.status()

    def presentation(self, body):
        with self.lock:
            active=self.active
            if not active or body.get('session_id')!=active['id'] or active.get('paused_at'): return
            stamp=float(body.get('captured_at',0));elapsed=(stamp-active['origin'])*1000
            if not math.isfinite(elapsed) or not 0<=elapsed<=60000: return
            cursors={}
            for name,item in body.get('cursors',{}).items():
                if name not in ('left','right','combined') or not isinstance(item,dict): continue
                point=item.get('point');opacity=item.get('opacity',0)
                if not isinstance(point,list) or len(point)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in point): continue
                if not isinstance(opacity,(int,float)) or not math.isfinite(opacity):continue
                cursors[name]=dict(point=point,opacity=max(0,min(1,opacity)))
            scene={k:v for k,v in body.get('scene',{}).items() if isinstance(k,str) and len(k)<64 and isinstance(v,(int,float)) and math.isfinite(v)}
            active['presentation'].write(json.dumps(dict(t_ms=elapsed,captured_at=stamp,cursors=cursors,scene=scene))+'\n')

    def _auto_stop(self, session_id):
        with self.lock:
            if self.active and self.active['id']==session_id and not self.active.get('paused_at'): self.stop()

    def _sample_gaze(self, active):
        next_sample = time.monotonic()
        with (active["folder"] / "gaze.jsonl").open("w", buffering=1) as output:
            while not active["stop"].is_set():
                if active.get('paused_at'):
                    active['stop'].wait(.03);next_sample=time.monotonic();continue
                sampled_ns = time.time_ns()
                sampled_time = time.monotonic()
                sampled_origin = active.get("origin")
                try:
                    state = read_state()
                    error = None
                except Exception as exc:
                    state, error = {}, str(exc)
                if active.get('paused_at') or active.get('origin') != sampled_origin: continue
                state=numeric(compact_state(state))
                gaze = research_sample(state,active.get('display'))
                output.write(json.dumps({"t_ms": ((sampled_time-active["origin"])*1000 if "origin" in active else (sampled_ns-active["epoch_ns"])/1e6),
                                         "unix_ns": sampled_ns, **gaze,
                                         "camera_connected": state.get("camera_connected", False),
                                         "calibrated": state.get("calibrated", False),
                                         "head_camera":state.get("head_camera"),
                                         "tracker_state":state,
                                         "error": error}, separators=(",", ":")) + "\n")
                next_sample += SAMPLE_INTERVAL
                next_sample = max(next_sample,time.monotonic())
                active["stop"].wait(max(0, next_sample - time.monotonic()))

    def stop(self):
        with self.lock:
            active = self.active
            if not active:
                raise ValueError("No session is recording")
            active["stop"].set()
            active["sampler"].join(timeout=2)
            active['timer'].cancel()
            duration_ms=min(60000,max(0,((active.get('paused_at') or time.monotonic())-active['origin'])*1000))
            active['presentation'].close()
            errors=[]
            process=active['process']
            if process and process.poll() is None:
                try:process.stdin.write('stop\n');process.stdin.flush();process.stdin.close()
                except BrokenPipeError:pass
            try: camera_summary=tracker_command('record-stop',dict(session_id=active['id']))
            except Exception as error:
                camera_summary={};errors.append('Camera finalization: '+str(error))
            process = active['process']
            if process:
                try:
                    process.wait(timeout=15)
                except (BrokenPipeError,subprocess.TimeoutExpired):
                    process.kill();process.wait()
                screen_error=process.stderr.read().strip()
                if process.returncode: errors.append(screen_error or 'Screen recording interrupted')
            errors.extend(camera_summary.get('errors',[]))
            folder = active["folder"]
            manifest = json.loads((folder / "session.json").read_text())
            gaze = load_lines(folder / "gaze.jsonl",
                              lambda row: {k: row.get(k) for k in ("t_ms", "valid", "x", "y")})
            frames = load_lines(folder / "frames.jsonl")
            compact = compact_tracking(manifest, gaze, frames)
            manifest.update(status="complete" if not errors else "partial",
                            cameras=camera_summary,
                            ended_at=datetime.now(timezone.utc).isoformat(),
                            duration_ms=duration_ms,
                            gaze_samples=sum(len(group["gaze_xy"]) for group in compact["groups"]),
                            raw_gaze_samples=len(gaze),
                            screen_frames=len(frames),
                            error="; ".join(errors) or None)
            (folder / "session.json").write_text(json.dumps(manifest, indent=2) + "\n")
            (folder / "tracking.json").write_text(json.dumps(compact, separators=(",", ":")) + "\n")
            self.active = None
            self.last_finished = active["id"]
            return manifest


def make_handler(manager, default_display_id=None):
    class Handler(BaseHTTPRequestHandler):
        def json(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def file(self, path, content_type):
            size = path.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                if not match:
                    self.send_error(416)
                    return
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
                if start > end or start >= size:
                    self.send_error(416)
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_GET(self):
            try:
                if self.path == "/":
                    self.file(PAGE, "text/html; charset=utf-8")
                elif self.path == "/review.js":
                    self.file(PAGE.with_name('session_review.js'), "text/javascript; charset=utf-8")
                elif self.path == "/diagnostics.js":
                    self.file(PAGE.with_name('session_diagnostics.js'), "text/javascript; charset=utf-8")
                elif self.path == "/api/displays":
                    self.json(200, displays())
                elif self.path == "/api/config":
                    self.json(200, {"default_display_id": default_display_id,"service":"eyecursor-review-v1","tracker":TRACKER})
                elif self.path == "/api/status":
                    self.json(200, manager.status())
                elif self.path == "/api/sessions":
                    self.json(200, [row for row in saved_sessions() if row.get('status') in ('recording','complete','partial')][:1])
                else:
                    image_match=re.fullmatch(r'/api/sessions/([0-9]{8}T[0-9]{6}-[0-9a-f]{8})/image/(left|right|face|face_secondary)/(\d{6})(-preview)?\.(png|jpg)',self.path)
                    if image_match:
                        sid,side,index,preview,extension=image_match.groups()
                        folder=RECORDINGS/sid
                        manifest=json.loads((folder/'session.json').read_text())
                        if manifest.get('status')=='recording': raise ValueError('Stop recording before replay')
                        image=camera_archive(str(folder)).read(f'{side}/{index}{preview or ""}.{extension}')
                        self.send_response(200);self.send_header('Content-Type','image/'+('jpeg' if extension=='jpg' else 'png'))
                        self.send_header('Content-Length',str(len(image)));self.end_headers();self.wfile.write(image)
                        return
                    match = re.fullmatch(r"/api/sessions/([^/]+)/(data|video|manifest|tracking|camera-archive|timeline)", self.path)
                    if not match or not SESSION_ID.fullmatch(match.group(1)):
                        self.send_error(404)
                        return
                    folder = RECORDINGS / match.group(1)
                    kind = match.group(2)
                    if kind == 'timeline':
                        self.json(200,replay_timeline(match.group(1)))
                    elif kind == 'camera-archive':
                        self.file(folder/'camera-frames.zip','application/zip')
                    elif kind == "video":
                        self.file(folder / "screen.mp4", "video/mp4")
                    elif kind == "manifest":
                        self.json(200, json.loads((folder / "session.json").read_text()))
                    elif kind == "tracking":
                        self.file(folder / "tracking.json", "application/json; charset=utf-8")
                    else:
                        self.json(200,session_data(folder))
            except (OSError, RuntimeError, ValueError, KeyError, zipfile.BadZipFile) as error:
                self.json(500, {"error": str(error)})

        def do_POST(self):
            try:
                if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("Expected application/json")
                origin = self.headers.get("Origin")
                if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                    raise ValueError("Request must originate from this local recorder page")
                size = int(self.headers.get("Content-Length", "0"))
                if size > 4096:
                    raise ValueError("Request too large")
                body = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/start":
                    self.json(200, manager.start(int(body.get("display_id", 0))))
                elif self.path == "/api/pause":
                    self.json(200,manager.pause(bool(body.get('paused'))))
                elif self.path == "/api/presentation":
                    manager.presentation(body);self.json(200,{})
                elif self.path == "/api/replay":
                    self.json(200,replay_frame(body.get('session_id',''),float(body.get('t_ms',0))))
                elif self.path == "/api/stop":
                    self.json(200, manager.stop())
                elif self.path == "/api/review":
                    session_id = body.get('session_id','')
                    if not SESSION_ID.fullmatch(session_id): raise ValueError('Choose a saved session')
                    data = session_data(RECORDINGS/session_id)
                    display = data['manifest']['display']
                    if not display: raise ValueError('Screen gaze review needs a recorded display; camera replay is available above')
                    start,end = float(body.get('start_ms',0)),float(body['end_ms'])
                    dispersion = float(body.get('dispersion_px',45))
                    if not 0<=start<=end or not 5<=dispersion<=500: raise ValueError('Invalid review range or dispersion')
                    self.json(200,analyze(data['gaze'],display['width'],display['height'],start,end,dispersion))
                else:
                    self.send_error(404)
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                self.json(400, {"error": str(error)})

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--default-display", type=int,
                        help="Preselect this display in the recorder page")
    args = parser.parse_args()
    RECORDINGS.mkdir(exist_ok=True)
    manager = SessionManager()
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 make_handler(manager, args.default_display))
    print(f"Recording and replay: http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if manager.active:
            manager.stop()
        server.server_close()


if __name__ == "__main__":
    main()
