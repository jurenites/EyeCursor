"""Deterministic capture interruption and USB identity regression checks."""
import unittest
from unittest.mock import Mock, patch
import numpy as np

from live_capture import ReconnectingCapture
from monitor_demo import Calibration, USBCameraSource


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.frame = np.ones((2, 2, 3), dtype=np.uint8)
        self.device = Mock()
        self.device.isOpened.return_value = True
        self.device.read.return_value = (False, None)
        self.opener = Mock(return_value=self.device)
        self.source = ReconnectingCapture(self.opener, clock=lambda: self.now)

    def test_short_dropout_keeps_session_and_calibration(self):
        for self.now in (0, .5, 1, 2.9):
            self.assertFalse(self.source.read()[0])
        self.device.release.assert_not_called()
        self.device.read.return_value = (True, self.frame)
        self.assertTrue(self.source.read()[0])
        self.assertFalse(self.source.recovered)
        self.assertEqual(self.opener.call_count, 1)

    def test_reopen_waits_and_requires_actual_frame_for_recovery(self):
        self.now = 3
        self.source.read()
        self.device.release.assert_called_once()
        self.now = 3.9
        self.source.read()
        self.assertEqual(self.opener.call_count, 1)
        self.now = 4
        self.assertFalse(self.source.read()[0])
        self.assertEqual(self.opener.call_count, 2)
        self.assertFalse(self.source.recovered)
        self.device.read.return_value = (True, self.frame)
        self.assertTrue(self.source.read()[0])
        self.assertTrue(self.source.recovered)
        self.source.read()
        self.assertFalse(self.source.recovered)

    def test_absent_device_backs_off_and_recovers(self):
        self.source.release()
        self.opener.side_effect = ValueError('device missing')
        self.source.read()
        attempts = self.opener.call_count
        for self.now in (.1, .2, .9):
            self.source.read()
        self.assertEqual(self.opener.call_count, attempts)
        self.now = 1
        self.source.read()
        self.assertEqual(self.source.next_attempt_at, 3)
        self.opener.side_effect = None
        self.device.read.return_value = (True, self.frame)
        self.now = 3
        self.assertTrue(self.source.read()[0])
        self.assertTrue(self.source.recovered)

    def test_closed_capture_is_released_and_empty_frame_rejected(self):
        self.source.release()
        self.device.isOpened.return_value = False
        self.source.read()
        self.assertIsNone(self.source.capture)
        self.device.isOpened.return_value = True
        self.device.read.return_value = (True, np.empty((0, 0, 3)))
        self.now = 1
        self.assertFalse(self.source.read()[0])

    def test_reconnect_follows_id_when_index_changes(self):
        camera = {'name': 'USB Camera', 'id': 'eye', 'index': 0}
        moved = dict(camera, index=2)
        other = {'name': 'USB Camera', 'id': 'other', 'index': 0}
        with patch('monitor_demo.list_mac_cameras', side_effect=[[camera], [other, moved], [other]]), \
                patch('monitor_demo.cv2.VideoCapture') as open_camera:
            source = USBCameraSource(requested_index=0)
            source.open()
            source.open()
            self.assertEqual(open_camera.call_args.args[0], 2)
            with self.assertRaises(ValueError):
                source.open()
            self.assertEqual(open_camera.call_count, 2)

    def test_interruption_invalidates_gaze_but_keeps_preview(self):
        calibration = Calibration('USB Camera')
        calibration.diagnostic_jpeg = b'last image'
        calibration.add_frame({'confidence': 0})
        calibration.click_event = {'id': 1}
        calibration.hold_frames.append((0, [0, 0]))
        calibration.interrupt_stream()
        self.assertFalse(calibration.state()['camera_connected'])
        self.assertFalse(calibration.state()['valid'])
        self.assertEqual(calibration.diagnostic_jpeg, b'last image')
        self.assertIsNone(calibration.click_event)
        self.assertFalse(calibration.hold_frames)


if __name__ == '__main__':
    unittest.main()
