"""Reject transient ellipse jumps without manufacturing current-frame evidence."""
from collections import deque
from dataclasses import dataclass
import math

import numpy as np


@dataclass
class Observation:
    time: float
    center: np.ndarray
    axes: np.ndarray  # major, minor; OpenCV may exchange its two axes
    angle: float  # major-axis orientation, modulo 180 degrees
    iris: object = None


def observation(ellipse, now, iris=None):
    center, axes, angle = ellipse
    center, axes = np.asarray(center, dtype=float), np.asarray(axes, dtype=float)
    if (center.shape != (2,) or axes.shape != (2,)
            or not np.isfinite([*center, *axes, angle, now]).all() or min(axes) <= 0):
        raise ValueError("Invalid ellipse")
    if axes[0] < axes[1]:
        angle += 90
    return Observation(now, center, np.sort(axes)[::-1], angle % 180, iris)


class PupilTrack:
    """A short reliable history gates detections, not display interpolation.

    Bounds are engineering defaults, not physiological limits. Position has a
    generous, time-dependent allowance for saccades. Size uses iris proportions
    when both frames have reliable iris evidence. A consistent new track can
    replace the old one after >=3 observations spanning >=80 ms; 350 ms without
    a trusted observation discards history. No rejected/weak sample trains it.
    """
    def __init__(self, reliable_confidence=.60, expiry=.35):
        self.reliable_confidence = reliable_confidence
        self.expiry = expiry
        self.reset()

    def reset(self):
        self.history = deque(maxlen=5)
        self.pending = []
        self.last_time = None

    @staticmethod
    def differences(current, previous):
        size = current.axes[0] / previous.axes[0]
        shape = (current.axes[1] / current.axes[0]) / (previous.axes[1] / previous.axes[0])
        angle = current.angle - previous.angle
        if current.iris is not None and previous.iris is not None:
            ci, pi = current.iris, previous.iris
            size /= ci.axes[0] / pi.axes[0]
            shape /= (ci.axes[1] / ci.axes[0]) / (pi.axes[1] / pi.axes[0])
            if ci.axes[1] / ci.axes[0] < .85 and pi.axes[1] / pi.axes[0] < .85:
                angle -= ci.angle - pi.angle
        # Nearly circular ellipses have no meaningful major-axis orientation.
        angle = abs((angle + 90) % 180 - 90) if max(
            current.axes[1] / current.axes[0], previous.axes[1] / previous.axes[0]) < .85 else 0
        return abs(math.log(size)), abs(math.log(shape)), angle

    def predicted_center(self, current):
        last = self.history[-1]
        samples = [sample for sample in self.history if last.time - sample.time <= .15]
        relative = current.iris is not None and all(s.iris is not None for s in samples)
        centers = np.array([(s.center - s.iris.center) / s.iris.axes[0]
                            if relative else s.center for s in samples])
        prediction = centers[-1].copy()
        if len(samples) >= 2:
            times = np.array([s.time for s in samples])
            times -= times.mean()
            denominator = float(times @ times)
            if denominator > 1e-8:
                velocity = times @ centers / denominator
                offset = velocity * min(current.time - last.time, .05)
                limit = last.axes[0] * .5 / (last.iris.axes[0] if relative else 1)
                prediction += offset * min(1., limit / max(float(np.linalg.norm(offset)), 1e-8))
        return prediction * current.iris.axes[0] + current.iris.center if relative else prediction

    def update(self, ellipse, confidence, iris, now):
        if not math.isfinite(now):
            self.reset()
            return {"accepted": False, "reason": "invalid-time"}
        if self.last_time is not None and now == self.last_time:
            return {"accepted": False, "reason": "duplicate-frame"}
        if self.last_time is not None and now < self.last_time:
            self.reset()  # New source, video seek, or changed timestamp domain.
        self.last_time = now
        expired = bool(self.history and now - self.history[-1].time > self.expiry)
        if expired:
            self.history.clear()
            self.pending.clear()
        try:
            guide = observation(iris['ellipse'], now) if iris and iris.get('support', 0) >= .65 else None
        except (ValueError, TypeError):
            guide = None
        try:
            current = observation(ellipse, now, guide) if ellipse is not None else None
        except (ValueError, TypeError):
            current = None
        if current is None or not math.isfinite(confidence):
            self.pending.clear()
            return {"accepted": False, "reason": "missing"}

        reliable = confidence >= self.reliable_confidence
        reason = None
        if self.history:
            last = self.history[-1]
            dt = min(now - last.time, .1)
            size, shape, angle = self.differences(current, last)
            distance = float(np.linalg.norm(current.center - self.predicted_center(current)))
            if size > math.log(1.25) + .8 * dt:
                reason = "size-jump"
            elif shape > math.log(1.4) + 2 * dt:
                reason = "shape-jump"
            elif angle > 35 + 360 * dt:
                reason = "angle-jump"
            elif distance > max(12., last.axes[0] * (.65 + 6 * dt)):
                reason = "position-jump"

        if reason:
            if reliable:
                if self.pending:
                    previous = self.pending[-1]
                    size, shape, angle = self.differences(current, previous)
                    if (now - previous.time > .12 or size > math.log(1.15)
                            or shape > math.log(1.2) or angle > 25
                            or np.linalg.norm(current.center - previous.center) > current.axes[0] * .75):
                        self.pending.clear()
                self.pending.append(current)
                if len(self.pending) >= 3 and now - self.pending[0].time >= .08:
                    self.history.clear()
                    self.history.extend(self.pending[-5:])
                    self.pending.clear()
                    return {"accepted": True, "reason": "reacquired"}
            else:
                self.pending.clear()
            return {"accepted": False, "reason": reason}

        self.pending.clear()
        status = "tracked" if self.history else "acquired"
        if reliable:
            self.history.append(current)
        return {"accepted": True, "reason": status if reliable else "weak-evidence"}
