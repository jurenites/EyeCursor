"""Explicit, bounded camera/measurement capture. No calibration or inferred targets.

Processed frames retain their actual timestamps rather than being resampled into
constant-rate movies. Replay uses a single session clock for all four sources.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import queue
import threading
import time
import zipfile
import cv2
from calibration_log import numeric

ROOT=Path(__file__).resolve().parents[1]/'recordings'
STREAMS=('left','right','face','face_secondary')
LIMIT_SECONDS=60.
_lock=threading.RLock()
_active=None


class CameraRecording:
    def __init__(self,folder,origin,session_id):
        self.folder=Path(folder);self.origin=float(origin);self.session_id=session_id
        self.queue=queue.Queue(maxsize=48);self.lock=threading.Lock()
        self.finish_lock=threading.Lock();self.summary=None
        self.paused_at=None
        self.closed=False;self.counts=Counter();self.dropped=Counter();self.errors=[];self.sequence=Counter()
        self.folder.mkdir(parents=True,exist_ok=True)
        self.worker=threading.Thread(target=self._write,name='diagnostic-frame-writer',daemon=True)
        self.worker.start()
        # Finalize even if the review browser/service disappears. No unbounded
        # image capture and no open archive left behind after the one-minute cap.
        self.timer=threading.Timer(max(0,LIMIT_SECONDS-(time.monotonic()-self.origin)),self.finish)
        self.timer.daemon=True;self.timer.start()

    def submit(self,stream,stamp,raw,preview,values):
        if stream not in STREAMS or raw is None:return
        with self.lock:
            if self.closed or self.paused_at or not 0<=stamp-self.origin<=LIMIT_SECONDS:return
            if self.queue.full():self.dropped[stream]+=1;return
            index=self.sequence[stream];self.sequence[stream]+=1
            # Producers own mutable detector arrays. Copy before returning.
            row=dict(stream=stream,frame=index,t_ms=(stamp-self.origin)*1000,
                     capture_monotonic=stamp,values=numeric(deepcopy(values)))
            self.queue.put_nowait((row,raw.copy(),bytes(preview) if preview else None))

    def pause(self, paused, stamp):
        with self.lock:
            if self.closed: raise ValueError('Recording has finished')
            if bool(self.paused_at)==paused:return
            self.timer.cancel()
            if paused:self.paused_at=stamp
            else:
                self.origin+=stamp-self.paused_at;self.paused_at=None
                self.timer=threading.Timer(max(0,LIMIT_SECONDS-(stamp-self.origin)),self.finish)
                self.timer.daemon=True;self.timer.start()

    def _write(self):
        logs={}
        try:
            with zipfile.ZipFile(self.folder/'camera-frames.zip','w',compression=zipfile.ZIP_STORED) as archive:
                logs={s:(self.folder/f'{s}-frames.jsonl').open('w',buffering=1) for s in STREAMS}
                while True:
                    item=self.queue.get()
                    try:
                        if item is None:break
                        row,raw,preview=item;stream=row['stream'];index=row['frame']
                        # Eyes are lossless source pixels; face is the unannotated
                        # full-frame inference input (not the moving preview crop).
                        extension='png' if stream in ('left','right') else 'jpg'
                        params=[cv2.IMWRITE_PNG_COMPRESSION,1] if extension=='png' else [cv2.IMWRITE_JPEG_QUALITY,92]
                        ok,encoded=cv2.imencode('.'+extension,raw,params)
                        if not ok:raise ValueError('Camera image encoding failed')
                        row['raw']=f'{stream}/{index:06d}.{extension}'
                        row['preview']=f'{stream}/{index:06d}-preview.jpg' if preview else row['raw']
                        row['raw_size']=[raw.shape[1],raw.shape[0]]
                        archive.writestr(row['raw'],encoded.tobytes())
                        if preview:archive.writestr(row['preview'],preview)
                        logs[stream].write(json.dumps(row,allow_nan=False)+'\n')
                        self.counts[stream]+=1
                    except Exception as error:
                        self.errors.append(str(error));self.errors=self.errors[-10:]
                    finally:self.queue.task_done()
        except Exception as error:
            self.errors.append(str(error))
        finally:
            for log in logs.values():log.close()

    def finish(self):
        with self.finish_lock:
            if self.summary is not None:return self.summary
            self.timer.cancel()
            with self.lock:self.closed=True
            # A disk failure may have stopped the consumer with a full queue.
            while self.worker.is_alive():
                try:self.queue.put(None,timeout=.1);break
                except queue.Full:continue
            self.worker.join()
            self.summary=dict(frames=dict(self.counts),dropped=dict(self.dropped),errors=self.errors,
                timing='Software camera capture timestamps; streams are not hardware synchronized',
                eye_images='Lossless PNG source frames; JPEG diagnostic overlays',
                face_images='JPEG full-frame inference input and face close-up overlay')
            (self.folder/'camera-summary.json').write_text(json.dumps(self.summary,indent=2)+'\n')
            return self.summary


def begin(session_id,origin):
    global _active
    # Folder ownership stays inside the project, never a caller-supplied path.
    import re,math
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}-[0-9a-f]{8}',session_id):raise ValueError('Invalid recording ID')
    if not math.isfinite(origin) or abs(time.monotonic()-origin)>30:raise ValueError('Invalid recording clock')
    with _lock:
        if _active is not None and not _active.closed:raise ValueError('Camera recording already active')
        if (ROOT/session_id/'camera-frames.zip').exists():raise ValueError('Recording already exists')
        _active=CameraRecording(ROOT/session_id,origin,session_id)


def publish(stream,stamp,raw,preview,values):
    with _lock:recording=_active
    if recording is not None:
        try:recording.submit(stream,stamp,raw,preview,values)
        except Exception as error:
            recording.errors.append(str(error));recording.errors=recording.errors[-10:]


def finish(session_id):
    global _active
    with _lock:
        if _active is None or _active.session_id!=session_id:raise ValueError('Recording session is not active')
        recording=_active;_active=None
    return recording.finish()


def pause(session_id,paused,stamp):
    import math
    if not math.isfinite(stamp) or abs(time.monotonic()-stamp)>5:raise ValueError('Invalid pause clock')
    with _lock:
        if _active is None or _active.session_id!=session_id:raise ValueError('Recording session is not active')
        _active.pause(paused,stamp)
