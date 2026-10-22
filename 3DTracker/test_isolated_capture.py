"""Exercise hung camera transport with disposable processes; no camera access."""
import sys
import time
import unittest
from isolated_capture import IsolatedCapture
from live_capture import ReconnectingCapture

FRAME="sys.stdout.buffer.write(struct.pack('!IIId',2,2,3,time.monotonic())+bytes(range(12)));sys.stdout.buffer.flush()"

class IsolatedCaptureTests(unittest.TestCase):
    def open(self,body):
        source=IsolatedCapture(0,command=[sys.executable,'-u','-c','import sys,time,struct,signal\n'+body])
        self.addCleanup(source.release)
        return source

    def first_frame(self,source):
        end=time.monotonic()+3
        while time.monotonic()<end:
            ok,frame=source.read()
            if ok:return frame
            time.sleep(.01)
        self.fail('Worker did not deliver its synthetic frame')

    def test_hung_read_is_nonblocking_and_worker_is_killed_even_if_it_ignores_termination(self):
        source=self.open("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"+FRAME+"\ntime.sleep(60)")
        frame=self.first_frame(source)
        self.assertEqual(frame.shape,(2,2,3));self.assertTrue(frame.flags.writeable)
        start=time.monotonic()
        self.assertFalse(source.read()[0])
        self.assertLess(time.monotonic()-start,.1)
        source.release()
        self.assertIsNotNone(source.process.poll())
        self.assertLess(time.monotonic()-start,1.5)
        self.assertFalse(source.isOpened())

    def test_watchdog_restarts_stalled_worker_and_preserves_capture_timestamp(self):
        now=[0.];opened=[]
        def opener():
            source=self.open(FRAME+'\ntime.sleep(60)');opened.append(source);return source
        recovery=ReconnectingCapture(opener,clock=lambda:now[0])
        self.addCleanup(recovery.release)
        end=time.monotonic()+3
        while time.monotonic()<end:
            if recovery.read()[0]:break
            time.sleep(.01)
        self.assertTrue(recovery.received_frame)
        self.assertGreater(recovery.frame_time,0)
        now[0]=3.1;self.assertFalse(recovery.read()[0])
        self.assertIsNotNone(opened[0].process.poll())
        now[0]=4.2;recovery.read()
        self.assertEqual(len(opened),2)
        end=time.monotonic()+3
        while time.monotonic()<end:
            if recovery.read()[0]:break
            time.sleep(.01)
        self.assertTrue(recovery.recovered)

    def test_partial_frame_cannot_trap_release_or_publish_invalid_pixels(self):
        source=self.open("sys.stdout.buffer.write(struct.pack('!IIId',2,2,3,time.monotonic())+b'x');sys.stdout.buffer.flush()\ntime.sleep(60)")
        self.assertFalse(source.read()[0])
        start=time.monotonic();source.release()
        self.assertLess(time.monotonic()-start,1.5)
        self.assertIsNone(source.latest)
