"""Recover live capture without repeatedly tearing down a warming-up stream."""
import time


class ReconnectingCapture:
    def __init__(self, opener, clock=time.monotonic, recovery_seconds=3.0):
        self.opener = opener
        self.clock = clock
        self.recovery_seconds = recovery_seconds
        self.capture = None
        self.last_frame_at = clock()
        self.next_attempt_at = self.last_frame_at
        self.retry_delay = 1.0
        self.reopened = False
        self.recovered = False
        self._open()

    def _open(self):
        try:
            self.capture = self.opener()
        except (ValueError, RuntimeError):
            self.capture = None
        self.last_frame_at = self.clock()
        if not self.isOpened():
            self._schedule_retry()

    def _schedule_retry(self):
        self.release()
        self.next_attempt_at = self.clock() + self.retry_delay
        self.retry_delay = min(5.0, self.retry_delay * 2)
        self.reopened = True

    def isOpened(self):
        return self.capture is not None and self.capture.isOpened()

    def read(self):
        self.recovered = False
        if self.capture is None:
            if self.clock() < self.next_attempt_at:
                return False, None
            self._open()
            if self.capture is None:
                return False, None
        ok, frame = self.capture.read()
        if ok and frame is not None and frame.size:
            self.last_frame_at = self.clock()
            self.retry_delay = 1.0
            self.recovered = self.reopened
            self.reopened = False
            return True, frame
        if self.clock() - self.last_frame_at >= self.recovery_seconds:
            self._schedule_retry()
        return False, None

    def release(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
