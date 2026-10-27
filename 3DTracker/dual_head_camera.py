"""Optional, locally calibrated second-view head-pose assistance.

This is empirical view alignment, not metric stereo triangulation. Both cameras
must see the same person. The laptop remains the reference coordinate frame.
Only held-out-validated, in-range, fresh observations can adjust its pose.
"""
from collections import deque
import json
from pathlib import Path
import threading
import time

import numpy as np
from head_camera import HeadCamera, PAIR_MAX_SECONDS, FACE_MAX_SECONDS

SCALE = np.array([.14, .14, .18, .04, .04, .12])


class ViewAlignment:
    def __init__(self):
        self.rows = deque(maxlen=1800)
        self.collecting = False
        self.model = None
        self.last_key = None
        self.bad_keys = set()
        self.message = 'Select a second webcam, then learn its view before gaze calibration.'
        self.validation_error = None

    def begin(self):
        self.__init__()
        self.collecting = True
        self.message = ('Move slowly: turn, nod, tilt, shift sideways/up/down and lean forward/back. '
                        'Repeat these movements, then finish alignment (at least 80 frames and 20 seconds).')

    def add(self, primary, secondary):
        key = (secondary['epoch'], secondary['time'])
        if not self.collecting or (self.last_key is not None and key <= self.last_key):
            return
        self.last_key = key
        if abs(primary['time'] - secondary['time']) > .06:
            return  # Training needs a tighter pair than live assistance.
        p, s = np.asarray(primary['features']), np.asarray(secondary['features'])
        if p.shape == s.shape == (6,) and np.isfinite(np.r_[p, s]).all():
            self.rows.append((secondary['time'], p, s))

    def finish(self):
        if len(self.rows) < 80 or self.rows[-1][0] - self.rows[0][0] < 20:
            raise ValueError('Keep moving slowly: need 80 distinct paired frames over at least 20 seconds.')
        p = np.array([r[1] for r in self.rows]) / SCALE
        s = np.array([r[2] for r in self.rows]) / SCALE
        split = int(len(s) * .75)
        # A later, untouched time interval validates the mapping. Repeated motion
        # is intentional: random frame splits would leak near-identical samples.
        center = np.mean(s[:split], axis=0)
        _, singular, vt = np.linalg.svd(s[:split] - center, full_matrices=False)
        rank = int(np.sum(singular > max(1., singular[0] * .06)))
        if rank < 4:
            raise ValueError('Need more varied motion: turn/nod/tilt and shift sideways, up/down, and toward/away.')
        basis = vt[:rank].T
        x = (s - center) @ basis
        design = np.column_stack((np.ones(len(x)), x))
        coef = np.linalg.solve(design[:split].T @ design[:split] + np.diag([1e-8] + [.05]*rank),
                               design[:split].T @ p[:split])
        prediction = design[split:] @ coef
        error = float(np.percentile(np.max(np.abs(prediction - p[split:]), axis=1), 90))
        baseline = float(np.mean((p[split:] - np.mean(p[:split], axis=0))**2))
        if error > .35 or baseline < .015 or np.mean((prediction - p[split:])**2) > baseline * .6:
            raise ValueError('Views did not agree on the later movements. Keep both cameras fixed and repeat slow movements.')
        # Do not refit on validation rows. Reject extrapolation and unseen motion.
        self.model = (center, basis, coef, np.min(x[:split], axis=0), np.max(x[:split], axis=0))
        self.validation_error = error
        self.collecting = False
        self.message = 'Second view aligned. Start gaze calibration; relearn after moving either webcam or changing person.'

    def predict(self, features):
        if self.model is None:
            return None
        s = np.asarray(features, dtype=float) / SCALE
        if s.shape != (6,) or not np.isfinite(s).all():
            return None
        center, basis, coef, low, high = self.model
        x = (s - center) @ basis
        residual = s - center - x @ basis.T
        if np.max(np.abs(residual)) > .35 or np.any(x < low-.15) or np.any(x > high+.15):
            return None
        return (np.r_[1., x] @ coef) * SCALE

    def assist(self, current, paired_primary, secondary):
        predicted = self.predict(secondary['features'])
        if predicted is None:
            return current, 0., 'outside_alignment'
        delta = predicted - np.asarray(paired_primary['features'])
        # Gate every frame before blending. Repeated disagreement invalidates
        # alignment, including a bumped camera or a different person.
        if np.max(np.abs(delta / SCALE)) > .6:
            self.bad_keys.add((secondary['epoch'], secondary['time']))
            if len(self.bad_keys) >= 4:
                self.model = None
                self.message = 'Views disagree. Relearn alignment with both cameras fixed and the same person visible.'
            return current, 0., 'views_disagree'
        self.bad_keys.clear()
        skew = max(abs(secondary['time'] - current['time']),
                   abs(paired_primary['time'] - secondary['time']))
        weight = .25 * max(0., 1. - skew / PAIR_MAX_SECONDS)
        # Transfer only the simultaneous-view correction, not an old head pose.
        # Primary motion since that exposure is preserved, avoiding low-FPS lag.
        features = np.asarray(current['features']) + weight * delta
        return dict(current, features=features.tolist()), weight, 'assisting' if weight > 0 else 'timestamp_gap'


class DualHeadCamera:
    def __init__(self, primary, enumerate_cameras, path, excluded_ids=lambda: set(),
                 factory=HeadCamera, clock=time.monotonic):
        self.primary = primary
        self.enumerate_cameras = enumerate_cameras
        self.path = Path(path)
        self.excluded_ids = excluded_ids
        self.factory = factory
        self.clock = clock
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.secondary = None
        self.selected_id = None
        self.devices = []
        self.error = None
        self.alignment = ViewAlignment()
        self.session = None
        self.revision = 0
        self.last_assistance = {'reason': 'disabled', 'weight': 0.}
        self.last_output = None
        try:
            value = json.loads(self.path.read_text()).get('secondary_camera_id')
            self._validate(value)
            self.selected_id = value
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, AttributeError, OSError, SystemExit):
            self.error = 'Second webcam settings conflict or could not be read. Select the camera again.'

    @property
    def epoch(self):
        # Changing alignment also changes the feature source used by gaze maps.
        return self.primary.epoch * 1000000 + self.revision

    @property
    def device_id(self):
        return self.primary.device_id

    def _validate(self, device_id):
        if device_id is not None and (not isinstance(device_id, str) or not device_id or len(device_id) > 256):
            raise ValueError('Invalid second webcam ID')
        if device_id and device_id in self.excluded_ids() | {self.primary.device_id}:
            raise ValueError('The two face webcams and the IR eye cameras must be different devices')
        if device_id and self.primary.device_id is None:
            if any(d['id'] == device_id and d.get('type') == 'AVCaptureDeviceTypeBuiltInWideAngleCamera'
                   for d in self.enumerate_cameras()):
                raise ValueError('The built-in webcam is already the primary face camera')

    def start(self):
        self.primary.start()
        if self.selected_id:
            self.secondary = self.factory(self.enumerate_cameras, self.selected_id, isolated=True)
            self.secondary.start()
        self.thread = threading.Thread(target=self._run, name='second-head-alignment', daemon=True)
        self.thread.start()

    def configure(self, device_id):
        with self.lock:
            self._validate(device_id)
            if device_id == self.selected_id:
                return
            if device_id and device_id not in {d['id'] for d in self.devices}:
                raise ValueError('Choose an available face webcam')
            new = self.factory(self.enumerate_cameras, device_id, isolated=True) if device_id else None
            temporary = self.path.with_suffix('.tmp')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({'secondary_camera_id': device_id}) + '\n')
            temporary.replace(self.path)
            if self.secondary:
                self.secondary.close()
            self.secondary, self.selected_id = new, device_id
            self._reset('Second webcam selected. Learn its view before gaze calibration.' if new else 'Second webcam disabled.')
            self.session = None
            self.error = None
            if new:
                new.start()

    def _reset(self, message):
        self.alignment = ViewAlignment()
        self.alignment.message = message
        self.last_output = None
        self.last_assistance = {'reason': 'not_aligned', 'weight': 0.}
        self.revision += 1

    def learn(self, finish=False):
        with self.lock:
            if not self.secondary:
                raise ValueError('Select a second webcam first')
            self._check_session()
            if finish:
                if not self.alignment.collecting:
                    raise ValueError('Start learning the second view first')
                self.alignment.finish()
                self.revision += 1
                self.last_output = None
            else:
                self._reset('')
                self.alignment.begin()

    def _check_session(self):
        session = (self.primary.epoch, self.secondary.epoch if self.secondary else None)
        if self.session is not None and session != self.session:
            self._reset('A webcam reconnected. Relearn the second view before gaze calibration.')
        self.session = session

    def _run(self):
        next_discovery = 0.
        while not self.stop_event.is_set():
            now = self.clock()
            if now >= next_discovery:
                try:
                    excluded = self.excluded_ids() | {self.primary.device_id}
                    devices = [d for d in self.enumerate_cameras() if d['id'] not in excluded]
                    with self.lock:
                        self.devices = devices
                        self.error = None
                except (Exception, SystemExit) as error:
                    with self.lock:
                        self.error = str(error)
                next_discovery = now + 3
            with self.lock:
                self._check_session()
                if self.secondary and self.alignment.collecting:
                    s = self.secondary.sample_at(now)
                    p = self.primary.sample_at(s['time']) if s else None
                    if p:
                        self.alignment.add(p, s)
            self.stop_event.wait(.03)

    def sample_at(self, stamp):
        with self.lock:
            self._check_session()
            p = self.primary.sample_at(stamp)
            if p is None or p['epoch'] != self.primary.epoch:
                return None  # Never invent a reference pose when the primary is lost.
            p = dict(p, epoch=self.epoch)
            weight, reason = 0., 'not_aligned' if self.secondary else 'disabled'
            if self.secondary and self.alignment.model is not None:
                s = self.secondary.sample_at(p['time'])
                # Both pairing to the primary AND pairing to the IR observation
                # must be fresh; their skews must not accumulate.
                paired = self.primary.sample_at(s['time']) if s else None
                now = self.clock()
                if s and paired and abs(s['time']-stamp) <= PAIR_MAX_SECONDS and 0 <= now-s['time'] <= FACE_MAX_SECONDS:
                    p, weight, reason = self.alignment.assist(p, paired, s)
                    if self.alignment.model is None:
                        self.revision += 1
                        p['epoch'] = self.epoch
                else:
                    reason = 'second_view_stale'
            self.last_assistance = {'reason': reason, 'weight': round(weight, 3), 'time': p['time']}
            p['secondary_view'] = dict(self.last_assistance)
            self.last_output = p
            return p

    def status(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            result = self.primary.status(now)
            result['epoch'] = self.epoch
            if self.last_output and result['face_visible'] and 0 <= now-self.last_output['time'] <= FACE_MAX_SECONDS:
                result['features'] = self.last_output['features']
            secondary = self.secondary.status(now) if self.secondary else None
            assistance = dict(self.last_assistance)
            if not 0 <= now-assistance.get('time', -1) <= FACE_MAX_SECONDS:
                assistance = {'reason': 'waiting_for_paired_tracking', 'weight': 0.}
            result['second_view'] = {'camera_id': self.selected_id, 'camera': secondary,
                'devices': self.devices, 'error': self.error,
                'collecting': self.alignment.collecting, 'aligned': self.alignment.model is not None,
                'samples': len(self.alignment.rows), 'message': self.alignment.message,
                'validation_error_normalized': self.alignment.validation_error,
                'method': 'empirical_pose_alignment', 'metric_triangulation': False,
                'assistance': assistance}
            return result

    def jpeg(self, secondary=False):
        with self.lock:
            camera = self.secondary if secondary else self.primary
            return camera.jpeg() if camera else None

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=4)
        self.primary.close()
        if self.secondary:
            self.secondary.close()
