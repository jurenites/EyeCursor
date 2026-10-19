"""Readiness checks around the original 3DTracker eye-sphere estimator."""
from collections import deque
import numpy as np


class EyeModelCalibration:
    def __init__(self, threshold=.5):
        self.threshold = threshold
        self.phase = 'uncalibrated'
        self.pupils = deque(maxlen=600)
        self.estimates = deque(maxlen=240)
        self.last_good = None

    def start(self):
        self.__init__(self.threshold)
        self.phase = 'collecting'

    def observe(self, result, now):
        if self.phase != 'collecting':
            return
        ellipse = result.get('pupil_ellipse') if result else None
        if not ellipse or not ellipse.get('center') or result.get('confidence', 0) < self.threshold:
            return
        self.last_good = now
        self.pupils.append((now, ellipse['center']))
        if (result.get('eye_model_updated', True)
                and result.get('eye_model_samples', 0) >= 30
                and result.get('eye_model_estimated')
                and result.get('sphere_radius', 0) > 0):
            self.estimates.append((now, *result['eye_center'], result['sphere_radius']))

    def status(self, now):
        count = len(self.pupils)
        duration = self.pupils[-1][0] - self.pupils[0][0] if count > 1 else 0
        coverage = (np.ptp(np.percentile([p[1] for p in self.pupils], [10, 90], axis=0), axis=0)
                    if count > 1 else np.zeros(2))
        recent = np.array([sample for sample in self.estimates if now - sample[0] <= 1.5])
        stability = 0.0
        stable = False
        if len(recent) >= 2:
            span = recent[-1, 0] - recent[0, 0]
            center_spread = np.max(np.std(recent[:, 1:3], axis=0))
            radius_spread = np.std(recent[:, 3]) / np.mean(recent[:, 3])
            continuous = np.max(np.diff(recent[:, 0])) <= .25
            stability = min(1, len(recent) / 8, span / .75)
            if center_spread > 4 or radius_spread > .08 or not continuous:
                stability *= .5
            stable = (len(recent) >= 8 and now - recent[-1, 0] <= .5 and span >= .75
                      and continuous and center_spread <= 4 and radius_spread <= .08)
        can_freeze = False
        if self.phase == 'ready':
            message = 'Eye model fixed while screen coordinates are learned.'
        elif self.phase == 'uncalibrated':
            message = 'Waiting for eye calibration.'
        elif self.last_good is None or now - self.last_good > .5:
            message = 'Waiting for clearer pupil frames to estimate the eye.'
        elif count < 30 or duration < 2:
            message = f'Collecting clear pupil views: {min(count, 30)}/30'
        elif np.min(coverage) < 12:
            direction = 'left and right' if coverage[0] < coverage[1] else 'up and down'
            message = f'More eye movement needed {direction}.'
        elif len(self.estimates) < 30:
            message = f'Estimating eye center: {len(self.estimates)}/30'
        else:
            can_freeze = bool(stable)
            message = ('Eye estimate stable. Ready to learn screen coordinates.'
                       if stable else 'Waiting for the eye center and size to settle.')
        # Evidence collected, not elapsed animation time. A poor image or a
        # stationary pupil cannot fill the ring simply by waiting.
        progress = .25 * (min(1, count / 30, duration / 2)
                          + min(1, float(np.min(coverage)) / 12)
                          + min(1, len(self.estimates) / 30) + stability)
        if self.phase == 'ready' or can_freeze:
            progress = 1.0
        else:
            progress = min(.95, progress)
        return {'phase': self.phase, 'can_freeze': can_freeze, 'message': message,
                'progress': progress, 'pupil_samples': count, 'model_samples': len(self.estimates)}

    def freeze(self, now):
        if not self.status(now)['can_freeze']:
            raise ValueError(self.status(now)['message'])
        self.phase = 'ready'
