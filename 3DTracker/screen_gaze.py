"""Conservative screen feedback; raw gaze and calibration stay untouched."""
from collections import deque
import math

import numpy as np


class ScreenGazeMotion:
    """Reject isolated jumps, then follow confirmed measurements with a short lag.

    A three-sample median removes isolated smaller spikes. Larger moves need
    three consistent observations over >=50 ms. A time-based low-pass follows
    the accepted target without overshoot or speculative extrapolation. All
    distances are measured in screen fractions, independent of pixel density.
    """
    def __init__(self, response=.02, expiry=.25):
        self.response = response
        self.expiry = expiry
        self.reset()

    def reset(self):
        self.position = None
        self.viewport = None
        self.context = None
        self.history = deque(maxlen=3)
        self.pending = deque(maxlen=5)
        self.pending_since = None
        self.last_input = None
        self.last_accepted = None
        self.accepted = False

    def update(self, point, viewport, timestamp, context):
        point = np.asarray(point, dtype=float)
        if (point.shape != (2,) or not np.isfinite(point).all()
                or not math.isfinite(timestamp) or len(viewport) != 4
                or not np.isfinite(viewport).all() or min(viewport[2:]) <= 0):
            self.reset()
            return
        if self.context != context or (self.last_input is not None and timestamp < self.last_input):
            self.reset()
        # Repeated HTTP polls of one camera frame are not new observations.
        if self.last_input == timestamp:
            return
        if self.last_input is not None and timestamp - self.last_input > self.expiry:
            self.reset()
        previous_time = self.last_input
        self.last_input = timestamp
        self.context = context
        viewport = tuple(viewport)
        if self.position is None:
            self.position = point.copy()
            self.viewport = viewport
            self.history.extend([point.copy() for _ in range(3)])
            self.last_accepted = timestamp
            self.accepted = True
            return

        scale = np.asarray(self.viewport[2:])
        anchor = np.median(self.history, axis=0)
        jump = np.linalg.norm((point - anchor) / scale) > .10
        self.accepted = not jump
        if jump:
            if self.pending and (self.pending[-1][1] != viewport
                    or np.linalg.norm((point - np.median([p for p, _ in self.pending], axis=0))
                                      / np.asarray(viewport[2:])) > .045):
                self.pending.clear()
                self.pending_since = None
            if not self.pending:
                self.pending_since = timestamp
            self.pending.append((point.copy(), viewport))
            if len(self.pending) < 3 or timestamp - self.pending_since < .05:
                return
            target = np.median([p for p, _ in self.pending], axis=0)
            self.history.clear()
            self.history.extend([target.copy() for _ in range(3)])
            self.accepted = True
            if viewport != self.viewport:
                # Confirm a monitor switch before placing there. Do not blend
                # coordinates belonging to different screen mappings.
                self.position = target.copy()
                self.viewport = viewport
        else:
            self.history.append(point.copy())
            target = np.median(self.history, axis=0)
            self.viewport = viewport
        self.pending.clear()
        self.pending_since = None
        # Integrate only this frame interval. A long rejected interval must not
        # accumulate time credit and cause an immediate jump on confirmation.
        dt = min(max(0., timestamp - previous_time), .1)
        # Settle small fixation noise gently, but follow purposeful motion fast.
        response=max(self.response,.08) if np.linalg.norm((target-self.position)/np.asarray(viewport[2:]))<.025 else self.response
        alpha = -math.expm1(-dt / response)
        self.position += alpha * (target - self.position)
        self.last_accepted = timestamp

    def sample(self, now):
        if (self.position is None or not math.isfinite(now) or self.last_accepted is None
                or not 0 <= now - self.last_accepted <= self.expiry):
            return None
        return self.position.tolist()

    def interrupt_confirmation(self):
        """Missing/rejected frames cannot connect two pieces of jump evidence."""
        self.pending.clear()
        self.pending_since = None
        self.accepted = False
