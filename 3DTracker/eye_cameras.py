"""Independent USB eye streams and detection results, bound to stable device IDs."""
from collections import deque
import json
import math
from pathlib import Path
import threading
import time

import cv2
from live_capture import ReconnectingCapture
from isolated_capture import IsolatedCapture


class EyeCameraRig:
    def __init__(self, enumerate_devices, path, opener=None, excluded_id=None, clock=time.monotonic):
        self.enumerate_devices = enumerate_devices
        self.path = Path(path)
        self.opener = opener or IsolatedCapture
        self.excluded_id = excluded_id
        self.clock = clock
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.threads = []
        self.devices = []
        self.discovery_error = None
        self.config = {'active_eye': 'left', 'left': {'device_id': None, 'rotation': 180},
                       'right': {'device_id': None, 'rotation': 0}}
        self.samples = {}
        self.tracking = {}
        self.observation_history = {eye: deque(maxlen=600) for eye in ("left","right")}
        self.tracking_errors = {}
        self.revisions = {'left': 0, 'right': 0}
        self.tracking_times = {eye: deque(maxlen=60) for eye in ('left', 'right')}
        self.errors = {}
        self.sessions = {'left': 0, 'right': 0}
        self.times = {eye: deque(maxlen=60) for eye in ('left', 'right')}
        self.serial = 0
        self.last_read = None
        self.frame_context = None
        self.last_session = None
        self.recovered = False
        try:
            saved = json.loads(self.path.read_text())
            self._validate(saved)
            self.config = saved
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, KeyError):
            self.discovery_error = 'Camera settings could not be read. Assign each eye again.'

    def _validate(self, config):
        if not isinstance(config, dict):
            raise ValueError('Expected camera settings')
        if config.get('active_eye') not in ('left', 'right'):
            raise ValueError('Choose the left or right tracking eye')
        ids = []
        for eye in ('left', 'right'):
            item = config.get(eye)
            if not isinstance(item, dict) or 'device_id' not in item or type(item.get('rotation')) is not int or item['rotation'] not in (0, 180):
                raise ValueError('Eye rotation must be 0 or 180 degrees')
            device = item.get('device_id')
            if device is not None and (not isinstance(device, str) or not device or len(device) > 256):
                raise ValueError('Invalid camera ID')
            if device:
                if device == self.excluded_id:
                    raise ValueError('The head webcam cannot also be an eye camera')
                ids.append(device)
        if len(ids) != len(set(ids)):
            raise ValueError('Assign a different camera to each eye')

    def context(self):
        with self.lock:
            eye = self.config['active_eye']
            item = self.config[eye]
            return eye, item['device_id'], item['rotation']

    @property
    def device_id(self):
        return self.context()[1]

    @property
    def name(self):
        return f'{self.context()[0].title()} eye camera'

    def configure(self, config):
        self._validate(config)
        # Persist before publishing so failed writes leave the live setup intact.
        with self.lock:
            known = {d['id'] for d in self.devices}
            saved = {self.config[e]['device_id'] for e in ('left', 'right')}
            if any(config[e]['device_id'] and config[e]['device_id'] not in known | saved for e in ('left', 'right')):
                raise ValueError('Choose an available USB camera')
            new = json.loads(json.dumps(config))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(new, indent=2) + '\n')
            temporary.replace(self.path)
            for eye in ('left', 'right'):
                if new[eye] != self.config[eye]:
                    self.samples.pop(eye, None)
                    self.tracking.pop(eye, None)
                    self.tracking_errors.pop(eye, None)
                    self.revisions[eye] += 1
                    self.tracking_times[eye].clear()
                    self.times[eye].clear()
            self.config = new

    def start(self):
        for target, args in ((self._discover, ()), (self._capture, ('left',)), (self._capture, ('right',))):
            thread = threading.Thread(target=target, args=args, daemon=True)
            self.threads.append(thread)
            thread.start()

    def _discover(self):
        while not self.stop.is_set():
            try:
                devices = [d for d in self.enumerate_devices()
                           if 'usb' in d['name'].lower() and 'camera' in d['name'].lower()
                           and d['id'] != self.excluded_id]
                with self.lock:
                    self.devices = devices
                    self.discovery_error = None
            except (Exception, SystemExit) as error:
                with self.lock:
                    self.discovery_error = str(error)
            self.stop.wait(3)

    def _open(self, eye, device_id):
        # Refresh indices at every open: hotplug can reorder AVFoundation devices
        # between periodic UI discovery updates.
        try:
            devices = [d for d in self.enumerate_devices() if d['id'] == device_id]
        except SystemExit as error:
            raise RuntimeError(str(error)) from error
        if len(devices) != 1:
            raise ValueError('Assigned camera is disconnected')
        capture = self.opener(devices[0]['index'])
        with self.lock:
            self.sessions[eye] += 1
        return capture

    def _publish(self, eye, settings, frame, captured_at):
        rotated = cv2.rotate(frame, cv2.ROTATE_180) if settings['rotation'] == 180 else frame
        # Preview compression stays off the tracking thread and away from its lock.
        height, width = rotated.shape[:2]
        scale = min(1, 640 / width)
        ok, jpeg = cv2.imencode('.jpg', cv2.resize(rotated, (round(width * scale), round(height * scale))),
                               [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.lock:
            if settings != self.config[eye]:
                return
            self.serial += 1
            self.samples[eye] = {'frame': rotated, 'time': captured_at, 'serial': self.serial,
                                 'jpeg': jpeg.tobytes() if ok else None,
                                 'context': (eye, settings['device_id'], settings['rotation']),
                                 'revision': self.revisions[eye],
                                 'session': self.sessions[eye]}
            self.times[eye].append(captured_at)
            self.errors.pop(eye, None)

    def _capture(self, eye):
        capture = None
        selected = None
        try:
            while not self.stop.is_set():
                with self.lock:
                    settings = dict(self.config[eye])
                if selected != settings['device_id']:
                    if capture:
                        capture.release()
                    selected = settings['device_id']
                    capture = None
                if not selected:
                    self.stop.wait(.1)
                    continue
                try:
                    if capture is None:
                        capture = ReconnectingCapture(lambda: self._open(eye, selected),clock=self.clock,warmup_seconds=8.)
                    ok, frame = capture.read()
                    if ok:
                        self._publish(eye, settings, frame, capture.frame_time)
                    else:
                        with self.lock:
                            sample=self.samples.get(eye)
                            if sample is None or self.clock()-sample['time']>=.5:
                                self.errors[eye]='Reconnecting camera' if capture.reopened else 'Waiting for camera frames'
                        self.stop.wait(.02)
                except Exception as error:
                    with self.lock:
                        self.errors[eye] = str(error)
                    if capture:
                        capture.release()
                    capture = None
                    self.stop.wait(1)
        finally:
            if capture:
                capture.release()

    def isOpened(self):
        return self.active_fresh()

    def active_fresh(self):
        with self.lock:
            sample = self.samples.get(self.config['active_eye'])
            return bool(sample and self.clock() - sample['time'] < .5)

    def read(self):
        with self.lock:
            context = self.context()
            sample = self.samples.get(context[0])
            if not self.active_fresh() or (context, sample['serial']) == self.last_read:
                return False, None
            self.last_read = context, sample['serial']
            self.frame_context = context
            self.frame_time = sample['time']
            self.frame_sample = dict(sample)
            session = context, sample['session']
            self.recovered = self.last_session is not None and self.last_session != session
            self.last_session = session
            return True, sample['frame']

    def snapshot(self, eye):
        """Return the latest frame without consuming the other eye's read cursor."""
        with self.lock:
            sample = self.samples.get(eye)
            return dict(sample) if sample and self.clock() - sample['time'] < .5 else None

    def publish_tracking(self, eye, sample, result, jpeg, threshold):
        self.remember_observation(eye,sample,result,threshold)
        with self.lock:
            current = self.samples.get(eye)
            if (not current or current['context'] != sample['context']
                    or current['revision'] != sample['revision']
                    or current['session'] != sample['session']
                    or self.clock() - sample['time'] >= .5):
                return
            previous = self.tracking.get(eye)
            if previous and previous['serial'] >= sample['serial']:
                return
            valid = bool(result and result.get('pupil_ellipse') and result.get('confidence', 0) >= threshold)
            self.tracking[eye] = {'time': sample['time'], 'serial': sample['serial'], 'jpeg': jpeg,
                                  'epoch': (sample['revision'], sample['session']),
                                  'valid': valid, 'result': result}
            self.tracking_errors.pop(eye, None)
            self.tracking_times[eye].append(sample['time'])

    def remember_observation(self, eye, sample, result, threshold):
        """Numeric history for target captures committed after a one-second hold."""
        if not sample or not result or not result.get('pupil_ellipse') or result.get('confidence',0)<threshold:return
        head=result.get('head_pose') or {}
        if not head.get('features') or abs(sample['time']-head.get('time',-1))>.12:return
        from continuous_calibration import pupil_shape_rejection
        if pupil_shape_rejection(result):return
        import numpy as np
        raw=np.array(result['pupil_ellipse']['center'])/[640,480]
        features=np.asarray(head['features'])
        if raw.shape!=(2,) or features.shape!=(6,) or not np.isfinite(np.r_[raw,features]).all():return
        with self.lock:
            if (sample['context'][1:]!=(self.config[eye]['device_id'],self.config[eye]['rotation'])
                    or sample['revision']!=self.revisions[eye] or sample['session']!=self.sessions[eye]):return
            identity=(sample['context'][1],sample['context'][2],sample['revision'],sample['session'],head.get('epoch'))
            history=self.observation_history[eye]
            if history and history[-1]['identity']!=identity:history.clear()
            if history and sample['time']<=history[-1]['time']:return
            history.append({'identity':identity,'time':sample['time'],'eye':raw.tolist(),
                            'head':features.tolist(),'confidence':result['confidence']})

    def observations_at(self, stamp, tolerance=.12):
        with self.lock:
            observations={}
            for side,history in self.observation_history.items():
                if not history:continue
                sample=self.samples.get(side)
                if not sample:continue
                row=min(history,key=lambda row:abs(row['time']-stamp))
                identity=row['identity']
                if (abs(row['time']-stamp)<=tolerance and identity[:4]==
                    (self.config[side]['device_id'],self.config[side]['rotation'],self.revisions[side],self.sessions[side])):
                    observations[side]=dict(row)
            return observations

    def prediction_observations_at(self,stamp,tolerance=.15):
        """Display-only raster holds never enter observations_at or fit history."""
        observations=self.observations_at(stamp,tolerance)
        with self.lock:
            for side,tracked in self.tracking.items():
                result=tracked.get('result') or {};held=result.get('display_hold')
                sample=self.samples.get(side);head=result.get('head_pose') or {}
                if not held or not sample or not head.get('features'):continue
                if not (0<=stamp-tracked['time']<=tolerance and stamp<=held['held_until']):continue
                if tracked['epoch']!=(sample['revision'],sample['session']):continue
                if abs(tracked['time']-head.get('time',-1))>.12:continue
                identity=(sample['context'][1],sample['context'][2],sample['revision'],sample['session'],head.get('epoch'))
                observations[side]={'identity':identity,'time':tracked['time'],
                    'eye':[held['pupil_ellipse']['center'][0]/640,held['pupil_ellipse']['center'][1]/480],
                    'head':head['features'],'confidence':held['confidence'],
                    'held':True,'measured_at':held['measured_at']}
        return observations

    def jpeg(self, eye):
        with self.lock:
            tracked = self.tracking.get(eye)
            if tracked and self.clock() - tracked['time'] < .5:
                return tracked['jpeg']
            sample = self.samples.get(eye)
            return sample['jpeg'] if sample and self.clock() - sample['time'] < .5 else None

    def status(self):
        with self.lock:
            eyes = {}
            for eye in ('left', 'right'):
                sample = self.samples.get(eye)
                connected = bool(sample and self.clock() - sample['time'] < .5)
                times = self.times[eye]
                fps = (len(times) - 1) / (times[-1] - times[0]) if connected and len(times) > 1 and times[-1] > times[0] else 0
                tracked = self.tracking.get(eye)
                tracking_fresh = bool(connected and tracked and self.clock() - tracked['time'] < .5
                                      and tracked['epoch'] == (sample['revision'], sample['session']))
                result = (tracked['result'] or {}) if tracking_fresh else {}
                tracking_times = self.tracking_times[eye]
                tracking_fps = ((len(tracking_times) - 1) / (tracking_times[-1] - tracking_times[0])
                                if tracking_fresh and len(tracking_times) > 1 and tracking_times[-1] > tracking_times[0] else 0)
                direction = None
                vector = result.get('gaze_direction')
                head = (result.get('head_pose') or {}).get('features')
                def finite(values, count):
                    return (isinstance(values, (list, tuple)) and len(values) == count
                            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in values))
                if (tracking_fresh and tracked['valid'] and result.get('eye_model_estimated')
                        and finite(vector, 3) and sum(v*v for v in vector) > 1e-6
                        and finite(head, 6)):
                    direction = {'vector': vector, 'head_features': head, 'captured_at':tracked['time']}
                eyes[eye] = {**self.config[eye], 'connected': connected, 'fps': fps,
                             'tracking_fps': tracking_fps,
                             'tracking': ('Pupil tracked' if tracked['valid'] else 'Searching for pupil') if tracking_fresh else 'Waiting for detection',
                             'confidence': result.get('confidence'),
                             'pupil_center': (result.get('pupil_ellipse') or {}).get('center'),
                             'gaze_direction': result.get('gaze_direction'),
                             'scene_direction': direction,
                             'tracking_epoch': f'{self.revisions[eye]}:{self.sessions[eye]}',
                             'error': self.errors.get(eye) or self.tracking_errors.get(eye),
                             'status': ('Connected' if connected else 'Disconnected' if self.config[eye]['device_id'] else 'Not assigned')}
            return {'active_eye': self.config['active_eye'], 'eyes': eyes,
                    'devices': list(self.devices), 'error': self.discovery_error}

    def release(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=1)
