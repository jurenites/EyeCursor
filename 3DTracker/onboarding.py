"""Hands-free eye fitting, per-display mapping, and validated profile reuse."""
from collections import deque
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
import Orlosky3DEyeTracker as tracker

VERIFY_TARGETS = ((.2, .2), (.8, .25), (.45, .8))
ACTIVE_PHASES = ('fitting', 'screen', 'verify')
MAX_ORBIT_SECONDS = 4 * math.pi / .75
TARGET_TRAVEL_SECONDS = .55


def project(matrix, feature):
    point = cv2.perspectiveTransform(np.array([[feature]], dtype=np.float32), np.array(matrix, dtype=float))[0, 0]
    return point if np.isfinite(point).all() else None


def validate_displays(displays):
    if not isinstance(displays, list) or not 1 <= len(displays) <= 8:
        raise ValueError('Expected one to eight connected displays')
    seen = set()
    clean = []
    for display in displays:
        if not isinstance(display, dict):
            raise ValueError('Invalid display')
        identity, viewport = display.get('id'), display.get('viewport')
        if (not isinstance(identity, str) or not identity or identity in seen
                or not isinstance(viewport, list) or len(viewport) != 4
                or not all(type(n) in (int, float) and math.isfinite(n) and abs(n) <= 100000 for n in viewport)
                or not all(0 < n <= 20000 for n in viewport[2:])):
            raise ValueError('Invalid display geometry or identifier')
        seen.add(identity)
        clean.append({'id': identity, 'viewport': viewport})
    return clean


class Onboarding:
    def __init__(self, calibration, profile_path=None, source_key=None, orientation=(False, False), clock=time.monotonic):
        self.calibration = calibration
        self.profile_path = Path(profile_path) if profile_path else None
        self.source_key = source_key
        self.orientation = list(orientation)
        self.clock = clock
        self.displays = []
        self.phase = 'no_displays'
        self.message = 'Waiting for displays'
        self.maps = []
        self.index = 0
        self.started_at = None
        self.visible_since = None
        self.last_seen = None
        self.hold = deque(maxlen=240)
        self.verify_index = 0
        self.progress = 0.0
        self.fast_path = False
        self.profile = None
        self.profile_error = None
        self.profile_saved = False
        self.saved_eye = None

    def configure(self, displays):
        clean = validate_displays(displays)
        if clean != self.displays:
            self.displays = clean
            self.arm()

    def arm(self):
        self.calibration.reset_eye_model()
        self.maps = []
        self.index = 0
        self.started_at = None
        self.visible_since = None
        self.last_seen = None
        self.fast_path = False
        self.saved_eye = None
        self.profile_error = None
        self.profile_saved = False
        self.phase = 'waiting' if self.displays else 'no_displays'
        self.message = 'Put on your glasses and look ahead. Calibration starts automatically.'
        self.hold.clear()
        self.progress = 0.0

    def cancel(self):
        self.arm()
        self.phase = 'cancelled'
        self.message = 'Calibration paused. Use Restart calibration in the menu when ready.'

    def context(self):
        region = self.calibration.eye_region
        return {'source': self.source_key, 'orientation': self.orientation,
                'eye_region': list(region) if region else None, 'displays': self.displays}

    def load_profile(self):
        if not self.profile_path or not self.source_key:
            return None
        try:
            data = json.loads(self.profile_path.read_text())
            if data.get('version') != 3 or data.get('context') != self.context():
                return None
            eye = np.array(data['eye'], dtype=float)
            if eye.shape != (3,) or not np.isfinite(eye).all() or eye[2] <= 0:
                return None
            maps = data['maps']
            if len(maps) != len(self.displays):
                return None
            for mapping, display in zip(maps, self.displays):
                matrix = np.array(mapping['matrix'], dtype=float)
                if (mapping['display'] != display or matrix.shape != (3, 3)
                        or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12):
                    return None
            return data
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def save_profile(self):
        if not self.profile_path or not self.source_key:
            return
        payload = {'version': 3, 'context': self.context(), 'eye': self.saved_eye, 'maps': self.maps}
        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.profile_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(payload, allow_nan=False))
            temporary.chmod(0o600)
            temporary.replace(self.profile_path)
            self.profile_saved = True
        except (OSError, ValueError) as error:
            self.profile_error = str(error)

    def tick(self, now=None):
        now = self.clock() if now is None else now
        expired = self.started_at is not None and (
            (self.phase == 'fitting' and now - self.started_at >= MAX_ORBIT_SECONDS)
            or (self.phase in ACTIVE_PHASES and now - self.started_at >= 60))
        if expired:
            self.calibration.reset_eye_model()
            self.maps.clear()
            self.phase = 'paused'
            self.message = 'Calibration paused'
        # Rejected frames after completion hide the cursor, but retain the mapping.
        # Only an explicit restart, source reconnect or display change starts over.

    def update(self, result, now=None):
        now = self.clock() if now is None else now
        self.tick(now)
        good = self.calibration.usable(result)
        previous_seen = self.last_seen
        if good:
            self.last_seen = now
        if self.phase in ('no_displays', 'cancelled', 'paused'):
            return
        if self.phase == 'waiting':
            if not good:
                if previous_seen is None or now - previous_seen > .2:
                    self.visible_since = None
                return
            if self.visible_since is None or previous_seen is None or now - previous_seen > .2:
                self.visible_since = now
            if now - self.visible_since >= .5:
                self.calibration.start_eye_model()
                self.started_at = now
                self.phase = 'fitting'
                self.message = 'Follow the moving dot with your eyes. Keep your head and glasses still.'
                self.profile = self.load_profile()
            return
        if self.phase == 'fitting':
            status = self.calibration.eye_model.status(now)
            if not status['can_freeze']:
                self.message = ('Follow the moving dot with your eyes. Keep your head and glasses still.'
                                if good else 'Keep your eye visible to the camera. Waiting for a clear pupil.')
                return
            self.calibration.freeze_eye_model()
            self.saved_eye = [float(v) for v in (*tracker.prev_model_center_avg, tracker.max_observed_distance)]
            prior = np.array(self.profile['eye']) if self.profile else None
            close = (prior is not None and np.linalg.norm(prior[:2] - self.saved_eye[:2]) <= 12
                     and abs(prior[2] / self.saved_eye[2] - 1) <= .12)
            self.fast_path = bool(close)
            if self.fast_path:
                # Saved mappings were measured in this exact frozen coordinate model.
                tracker.prev_model_center_avg = tuple(round(n) for n in prior[:2])
                tracker.max_observed_distance = float(prior[2])
                self.saved_eye = prior.tolist()
                self._verify_display()
            else:
                self._full_display()
            return
        if self.phase == 'screen':
            step = self.calibration.native
            if step and step['phase'] == 'complete':
                self.maps.append({'display': self.displays[self.index], 'matrix': self.calibration.matrix.tolist()})
                self._next_display()
            elif step and step['phase'] == 'retry':
                self.phase = 'paused'
                self.message = 'Calibration incomplete'
            return
        if self.phase == 'verify':
            if now < self.verify_since:
                return
            feature = result['gaze_direction'][:2] if good else None
            self.hold.append((now, feature))
            while self.hold and now - self.hold[0][0] > 1.5:
                self.hold.popleft()
            # A verification target gets only fresh, steady measurements at that target.
            recent = list(self.hold)
            if (not good or any(v is None for _, v in recent)
                    or any(b[0] - a[0] > .2 for a, b in zip(recent, recent[1:]))):
                self.hold.clear()
                self.progress = 0
                return
            if len(recent) < 2:
                return
            features = np.array([v for _, v in recent])
            if np.max(np.std(features, axis=0)) > .012:
                self.hold.clear()
                self.progress = 0
                return
            duration = now - recent[0][0]
            self.progress = min(1.0, duration / .8)
            if duration < .8 or len(recent) < 8:
                return
            mapping = self.profile['maps'][self.index]
            predicted = project(mapping['matrix'], np.median(features, axis=0).tolist())
            target = VERIFY_TARGETS[self.verify_index]
            if predicted is None or np.max(np.abs(predicted - target)) > .07:
                # A similar eye fit alone is never permission to reuse an old mapping.
                self.fast_path = False
                self._full_display()
                return
            self.verify_index += 1
            self.verify_since = now + TARGET_TRAVEL_SECONDS
            self.hold.clear()
            self.progress = 0
            if self.verify_index == len(VERIFY_TARGETS):
                self.maps.append(mapping)
                self._next_display()

    def _full_display(self):
        self.phase = 'screen'
        self.calibration.start_native(self.displays[self.index]['viewport'])
        self.message = 'Look at the dot until its ring fills.'

    def _verify_display(self):
        self.phase = 'verify'
        self.calibration.reset()
        self.verify_index = 0
        self.verify_since = self.clock() + TARGET_TRAVEL_SECONDS
        self.hold.clear()
        self.progress = 0
        self.message = 'Checking your previous calibration. Look at each dot.'

    def _next_display(self):
        self.index += 1
        if self.index == len(self.displays):
            self.phase = 'complete'
            self.calibration.desktop_cursor = True
            self.message = 'Eye cursor ready'
            self.save_profile()
        elif self.fast_path:
            self._verify_display()
        else:
            self._full_display()

    def desktop_point(self, feature):
        if self.phase != 'complete':
            return None
        matches = []
        for mapping in self.maps:
            point = project(mapping['matrix'], feature)
            if point is not None and np.all((point >= 0) & (point <= 1)):
                x, y, w, h = mapping['display']['viewport']
                matches.append([float(x + point[0] * w), float(y + point[1] * h)])
        # With no head-pose sensor, overlapping eye-angle maps cannot identify a display.
        return matches[0] if len(matches) == 1 else None

    def state(self, now=None):
        now = self.clock() if now is None else now
        self.tick(now)
        display = self.displays[min(self.index, len(self.displays) - 1)] if self.displays else None
        target, progress = None, 0
        if self.phase == 'fitting':
            elapsed = min(MAX_ORBIT_SECONDS, now - self.started_at)
            target = [.5 + .36 * math.cos(elapsed * .75), .5 + .34 * math.sin(elapsed * .75)]
            fit = self.calibration.eye_model.status(now)
            progress = fit['progress']
            self.message = (f"Follow the moving dot. Keep your head still.\n"
                            f"Eye fit {round(progress * 100)}% · {fit['message']}")
        elif self.phase == 'screen' and self.calibration.native:
            target = self.calibration.native['target']
            progress = self.calibration.native['progress']
        elif self.phase == 'verify':
            target = list(VERIFY_TARGETS[self.verify_index])
            progress = self.progress
        return {'phase': self.phase, 'display_id': display['id'] if display else None,
                'display_index': min(self.index + 1, len(self.displays)), 'display_count': len(self.displays),
                'target': target, 'progress': progress, 'message': self.message,
                'elapsed': max(0, now - self.started_at) if self.started_at is not None else 0,
                'fast_path': self.fast_path, 'profile_saved': self.profile_saved}
