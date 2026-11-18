"""Pixel-supported smoothing of small ellipse jitter, independent for each eye."""
import math
import numpy as np
from pupil_tracking import observation


def border_candidate(ellipse, shape):
    if ellipse is None:
        return False
    try:
        p = observation(ellipse, 0)
    except (ValueError, TypeError):
        return True
    h, w = shape[:2]
    x, y = p.center
    angle = math.radians(p.angle)
    a, b = p.axes / 2
    rx = math.hypot(a * math.cos(angle), b * math.sin(angle))
    ry = math.hypot(a * math.sin(angle), b * math.cos(angle))
    return (not (.06*w <= x <= .94*w and .06*h <= y <= .94*h)
            or x-rx < 2 or x+rx > w-2 or y-ry < 2 or y+ry > h-2)


class PupilStabilizer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.frame = None

    def update(self, gray, ellipse, confidence, now):
        """Only call for an accepted current detection; never invent a pupil."""
        if ellipse is None or confidence < .6:
            self.reset()
            return ellipse, {'smoothed': False, 'reason': 'weak-evidence'}
        current = observation(ellipse, now)
        last = self.previous
        stable = False
        delta_mean = None
        if last is not None and self.frame.shape == gray.shape and 0 < now-last.time <= .15:
            h, w = gray.shape
            radius = max(16, last.axes[0]*.75)
            x, y = last.center
            x0, x1 = max(0, int(x-radius)), min(w, int(x+radius)+1)
            y0, y1 = max(0, int(y-radius)), min(h, int(y+radius)+1)
            old = self.frame[y0:y1, x0:x1].astype(np.float32)
            new = gray[y0:y1, x0:x1].astype(np.float32)
            mask = (old < 240) & (new < 240)
            if mask.size and mask.mean() >= .8:
                delta = (new-old)[mask]
                offset = float(np.median(delta))
                difference = np.abs(delta-offset)
                delta_mean = float(difference.mean())
                stable = abs(offset) <= 8 and delta_mean <= 3 and np.percentile(difference,90) <= 10
            angle_delta = (current.angle-last.angle+90) % 180-90
            small = (np.linalg.norm(current.center-last.center) <= max(4, last.axes[0]*.08)
                     and np.max(np.abs(np.log(current.axes/last.axes))) <= .18)
            if stable and small:
                dt = now-last.time
                center_alpha = 1-math.exp(-dt/.045)
                shape_alpha = 1-math.exp(-dt/.09)
                current.center = last.center + center_alpha*(current.center-last.center)
                current.axes = last.axes + shape_alpha*(current.axes-last.axes)
                current.angle = (last.angle+shape_alpha*angle_delta) % 180
                ellipse = (tuple(current.center), tuple(current.axes), current.angle)
            else:
                stable = False
        self.previous = current
        self.frame = gray.copy()
        return ellipse, {'smoothed': bool(stable), 'local_pixel_change': delta_mean,
                         'reason': 'stable-pixels' if stable else 'current-frame'}
