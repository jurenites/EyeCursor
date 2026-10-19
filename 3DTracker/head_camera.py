"""Local MediaPipe head tracking, independently captured from the selected webcam.

Uses the facial-landmark approach of Webcam3DTracker without importing its camera,
UI, or mouse-control loop. Camera samples carry capture-return timestamps, not
hardware exposure timestamps; pairing is deliberately bounded.
"""
from collections import deque, Counter
from pathlib import Path
import math
import os
import threading
import time
import cv2
import numpy as np
from live_capture import ReconnectingCapture

MODEL_PATH = Path(__file__).resolve().parents[1] / '.venv/models/face_landmarker.task'
PAIR_MAX_SECONDS = .12
FACE_MAX_SECONDS = .25


def choose_head_camera(cameras, requested_id=None):
    matches = [c for c in cameras if c.get('type') == 'AVCaptureDeviceTypeBuiltInWideAngleCamera']
    if requested_id:
        matches = [c for c in cameras if c['id'] == requested_id]
    if len(matches) != 1:
        raise ValueError('Waiting for the selected head camera; no automatic camera substitution.')
    return matches[0]


def pose_from_landmarks(landmarks, matrix, image_aspect=16/9):
    if len(landmarks) < 478:
        return None
    transform = np.asarray(matrix, dtype=float)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        return None
    # Remove any scale from the canonical-face transform before extracting angles.
    u, _, vt = np.linalg.svd(transform[:3, :3])
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        return None
    yaw = math.atan2(-rotation[2, 0], math.hypot(rotation[0, 0], rotation[1, 0]))
    pitch = math.atan2(rotation[2, 1], rotation[2, 2])
    roll = math.atan2(rotation[1, 0], rotation[0, 0])
    xy = np.array([[p.x, p.y] for p in landmarks], dtype=float)
    center = (xy[33] + xy[263]) / 2
    # Compare lengths in image-width units, then undo the projected shortening
    # of the head's horizontal axis. Otherwise turning in place looks like depth
    # translation, and rolling changes scale on a non-square camera image.
    if not np.isfinite(image_aspect) or image_aspect<=0:return None
    cheek_delta=(xy[234]-xy[454])*[1.,1./image_aspect]
    projected_axis=float(np.linalg.norm(rotation[:2,0]))
    if projected_axis<.5:return None  # Near profile cannot give stable depth.
    width=float(np.linalg.norm(cheek_delta)/projected_axis)
    if not np.isfinite(xy).all() or not .10 <= width <= .85 or not np.all((center > .05) & (center < .95)):
        return None
    features = [yaw, pitch, roll, *center.tolist(), math.log(width)]
    # Iris positions are shown as a diagnostic cross-check; IR supplies fine gaze.
    irises = [xy[468].tolist(), xy[473].tolist()]
    # Iris displacement within each eye gives a rough direction, not calibrated
    # screen gaze. Degenerate/closed eyes produce no line rather than a fake ray.
    rays=[]
    for iris,a,b,top,bottom in ((468,33,133,159,145),(473,362,263,386,374)):
        across=xy[b]-xy[a];eye_width=np.linalg.norm(across)
        if eye_width<.005 or np.linalg.norm(xy[top]-xy[bottom])/eye_width<.08:
            rays.append(None);continue
        across/=eye_width
        down=np.array([-across[1],across[0]])
        offset=xy[iris]-(xy[a]+xy[b])/2
        horizontal=float(np.clip(np.dot(offset,across)/eye_width,-.35,.35))
        vertical=float(np.clip(np.dot(offset,down)/eye_width,-.35,.35))
        ray=np.array([-horizontal*1.2,-vertical*1.2,-1.])
        rays.append((ray/np.linalg.norm(ray)).tolist())
    return {'features': features, 'feature_schema':'rotation_corrected_face_scale_v1',
            'irises': irises, 'eye_rays':rays,
            'face_box': [*np.min(xy[:468],axis=0).tolist(), *np.max(xy[:468],axis=0).tolist()]}


def preview_irises(irises, width, height, crop=None):
    """Map camera coordinates through the same 640x480 letterbox as its JPEG."""
    if crop is not None:
        left, top, right, bottom = crop
        irises = [[(px*width-left)/(right-left), (py*height-top)/(bottom-top)] for px,py in irises]
        width, height = right-left, bottom-top
    scale = min(640 / width, 480 / height)
    w, h = round(width * scale), round(height * scale)
    x, y = (640 - w) // 2, (480 - h) // 2
    return [[(px * w + x) / 640, (py * h + y) / 480] for px, py in irises]


class FacePreviewCrop:
    """Smoothed display crop only. Head/gaze features stay in full-frame coordinates."""
    def __init__(self):
        self.rect = None
        self.last_seen = None
        self.shape = None

    def update(self, face_box, width, height, now):
        if self.shape != (width,height):
            self.rect = None
            self.last_seen = None
            self.shape = (width,height)
        valid = (face_box is not None and np.shape(face_box)==(4,)
                 and np.isfinite(face_box).all() and face_box[2]>face_box[0] and face_box[3]>face_box[1])
        if valid:
            left,top,right,bottom = np.clip(face_box,0,1)*[width,height,width,height]
            size = min(width,height*4/3,max((right-left)*1.55,(bottom-top)*1.35*4/3,width/3))
            # Put the face 10% lower in the preview for more forehead/headroom.
            target = np.array([(left+right)/2,(top+bottom)/2-size*3/4*.10,size])
            if self.rect is None:self.rect=target
            else:self.rect += .18*(target-self.rect)
            self.last_seen=now
        elif self.last_seen is None or now-self.last_seen>.5:
            self.rect=None
        if self.rect is None:return (0,0,width,height)
        cx,cy,size=self.rect
        w=max(1,min(width,round(size)));h=max(1,min(height,round(size*3/4)))
        x=max(0,min(width-w,round(cx-w/2)));y=max(0,min(height-h,round(cy-h/2)))
        return (x,y,x+w,y+h)


class HeadCamera:
    def __init__(self, enumerate_cameras, requested_id=None, model_path=MODEL_PATH):
        self.enumerate_cameras = enumerate_cameras
        self.device_id = requested_id
        self.name = 'Laptop webcam'
        self.model_path = Path(model_path)
        self.lock = threading.Lock()
        self.history = deque(maxlen=60)
        self.stamps = deque(maxlen=60)
        self.preview = None
        self.pair_checks = deque(maxlen=300)
        self.last_pair_check = None
        self.error = None
        self.epoch = 0
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if not self.model_path.is_file():
            raise ValueError('Run 3DTracker/setup_hybrid.py to download the face model first.')
        os.environ.setdefault('MPLCONFIGDIR', str(MODEL_PATH.parent.parent / 'matplotlib-cache'))
        import mediapipe  # Fail before opening cameras if the local dependency is absent.
        self.thread = threading.Thread(target=self._run, name='laptop-head-camera', daemon=True)
        self.thread.start()

    def _open(self):
        try:
            selected = choose_head_camera(self.enumerate_cameras(), self.device_id)
            self.device_id, self.name = selected['id'], selected['name']
            cap = cv2.VideoCapture(selected['index'], cv2.CAP_AVFOUNDATION)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.epoch += 1
            with self.lock:
                self.history.clear()
            return cap
        except (ValueError, SystemExit) as error:
            self.error = str(error)
            raise RuntimeError(str(error)) from error

    def _run(self):
        import mediapipe as mp
        cap = None
        try:
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(self.model_path),
                                                  delegate=mp.tasks.BaseOptions.Delegate.CPU),
                running_mode=mp.tasks.vision.RunningMode.VIDEO, num_faces=1,
                min_face_detection_confidence=.6, min_face_presence_confidence=.6,
                min_tracking_confidence=.6, output_facial_transformation_matrixes=True)
            with mp.tasks.vision.FaceLandmarker.create_from_options(options) as detector:
                cap = ReconnectingCapture(self._open)
                last_ms = -1
                preview_crop = FacePreviewCrop()
                while not self.stop_event.is_set():
                    ok, image = cap.read()
                    stamp = time.monotonic()
                    if not ok:
                        with self.lock:
                            self.history.clear()
                        self.stop_event.wait(.03)
                        continue
                    # Preserve aspect ratio; cap inference input width for predictable latency.
                    capture_image = image
                    h, w = image.shape[:2]
                    if w > 640:
                        image = cv2.resize(image, (640, round(h * 640 / w)))
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    ms = max(last_ms + 1, round(stamp * 1000)); last_ms = ms
                    result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
                    pose = None
                    if len(result.face_landmarks) == 1 and result.facial_transformation_matrixes:
                        pose = pose_from_landmarks(result.face_landmarks[0], result.facial_transformation_matrixes[0], w/h)
                    # Keep native capture pixels for the close-up. Inference remains
                    # capped at 640 px, and all calibration features stay unchanged.
                    image = capture_image.copy()
                    ih,iw=image.shape[:2]
                    crop=preview_crop.update(pose.get('face_box') if pose else None,iw,ih,stamp)
                    packet = {'time': stamp, 'pose': pose, 'epoch': self.epoch,
                              'image_aspect':iw/ih,
                              'preview_irises': preview_irises(pose['irises'],iw,ih,crop) if pose else None,
                              'processing_ms':round((time.monotonic()-stamp)*1000,2)}
                    if pose:
                        for x,y in pose['irises']:
                            cv2.circle(image,(round(x*iw),round(y*ih)),max(2,round(iw/160)),(255,255,255),1)
                    x0,y0,x1,y1=crop
                    image=image[y0:y1,x0:x1]
                    canvas = np.zeros((480,640,3), dtype=np.uint8)
                    ih, iw = image.shape[:2]
                    scale = min(640/iw, 480/ih)
                    image = cv2.resize(image, (round(iw*scale), round(ih*scale)))
                    y = (480-image.shape[0])//2; x = (640-image.shape[1])//2
                    canvas[y:y+image.shape[0],x:x+image.shape[1]] = image
                    ok, jpeg = cv2.imencode('.jpg',canvas,[cv2.IMWRITE_JPEG_QUALITY,75])
                    with self.lock:
                        self.history.append(packet)
                        self.stamps.append(stamp)
                        if ok: self.preview = jpeg.tobytes()
                        self.error = None
        except Exception as error:
            with self.lock:
                self.error = f'Webcam tracking unavailable: {error}'
                self.history.clear()
        finally:
            if cap: cap.release()

    def sample_at(self, stamp):
        with self.lock:
            packet = min(self.history,key=lambda p:abs(p['time']-stamp)) if self.history else None
            skew = packet['time']-stamp if packet else None
            reason = ('no_webcam_sample' if packet is None else 'timestamp_gap' if abs(skew)>PAIR_MAX_SECONDS
                      else 'no_face_in_paired_frame' if not packet['pose'] else 'paired')
            self.last_pair_check = {'reason':reason,'skew_ms':round(skew*1000,2) if skew is not None else None,
                                    'processing_ms':packet.get('processing_ms') if packet else None}
            self.pair_checks.append(reason)
            if reason!='paired':return None
            return {'time':packet['time'],'epoch':packet['epoch'],'camera_id':self.device_id,
                    'coordinate_frame':'camera_local',**packet['pose']}

    def status(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            latest = self.history[-1] if self.history else None
            fresh = bool(latest and 0 <= now-latest['time'] <= FACE_MAX_SECONDS)
            fps = ((len(self.stamps)-1)/(self.stamps[-1]-self.stamps[0])
                   if fresh and len(self.stamps)>1 and self.stamps[-1]>self.stamps[0] else 0)
            return {'name': self.name, 'camera_id':self.device_id, 'coordinate_frame':'camera_local',
                    'image_aspect':latest.get('image_aspect') if latest else None,
                    'connected': fresh, 'face_visible': bool(fresh and latest['pose']),
                    'fps': round(fps,1), 'error': self.error, 'epoch': self.epoch,
                    'preview_irises': latest.get('preview_irises') if fresh and latest['pose'] else None,
                    'features': latest['pose']['features'] if fresh and latest['pose'] else None,
                    'eye_rays': latest['pose'].get('eye_rays') if fresh and latest['pose'] else None,
                    'pairing': {'last':self.last_pair_check,'recent_counts':dict(Counter(self.pair_checks)),
                                'max_skew_ms':PAIR_MAX_SECONDS*1000,'max_age_ms':FACE_MAX_SECONDS*1000}}

    def jpeg(self):
        with self.lock: return self.preview

    def close(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=3)
