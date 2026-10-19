"""Conservative pupil-loss double-blink heuristic; never emits OS input itself."""
import math
from collections import deque


class FixationDoubleBlink:
    def __init__(self):
        self.cooldown_until = 0
        self.reset()

    def reset(self):
        self.points = deque()
        self.anchor = None
        self.closed_at = None
        self.first_opened = None
        self.confirm_since = None
        self.last_frame = None

    def update(self, now, point, pupil_missing=False):
        if self.last_frame is not None and now - self.last_frame > 0.2:
            self.reset()  # A stopped stream is not a blink.
        self.last_frame = now
        if now < self.cooldown_until:
            return None
        if point is None:
            if not pupil_missing or self.anchor is None or self.confirm_since is not None:
                self.reset()
                return None
            if self.closed_at is None:
                if self.first_opened is not None and now - self.first_opened > 0.6:
                    self.reset()
                    return None
                self.closed_at = now
            elif now - self.closed_at > 0.35:
                self.reset()
            return None
        if self.anchor is not None:
            if math.dist(point, self.anchor) > 24:
                self.reset()
            else:
                if self.closed_at is not None:
                    duration = now - self.closed_at
                    self.closed_at = None
                    if not 0.08 <= duration <= 0.35:
                        self.reset()
                        return None
                    if self.first_opened is None:
                        self.first_opened = now
                    elif 0.08 <= now - duration - self.first_opened <= 0.6:
                        self.confirm_since = now
                    else:
                        self.reset()
                    return None
                if self.confirm_since is not None:
                    if now - self.confirm_since >= 0.15:
                        destination = list(self.anchor)
                        self.reset()
                        self.cooldown_until = now + 1
                        return destination
                    return None
                if self.first_opened is not None and now - self.first_opened > 0.6:
                    self.reset()
                else:
                    return None
        if self.points and math.dist(point, self.points[0][1]) > 24:
            self.points.clear()
        self.points.append((now, list(point)))
        while self.points and now - self.points[0][0] > 1.2:
            self.points.popleft()
        if len(self.points) >= 8 and now - self.points[0][0] >= 1:
            self.anchor = [sum(p[i] for _, p in self.points) / len(self.points) for i in (0, 1)]
            self.points.clear()
        return None
