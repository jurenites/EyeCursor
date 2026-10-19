"""Two-eye identity, orientation, recovery and calibration isolation checks."""
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

import numpy as np

from eye_cameras import EyeCameraRig
from monitor_demo import Calibration, make_handler, render_diagnostic_frame
from binocular_tracking import CompanionEyeTracker, independent_detector


class EyeCameraTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = 10.0
        self.devices = [{'id': 'left-usb', 'name': 'USB Camera', 'index': 2},
                        {'id': 'right-usb', 'name': 'USB Camera', 'index': 0}]
        self.rig = EyeCameraRig(lambda: self.devices, Path(self.folder.name) / 'eyes.json',
                                clock=lambda: self.now)
        self.rig.devices = self.devices
        self.config = {'active_eye': 'left', 'left': {'device_id': 'left-usb', 'rotation': 180},
                       'right': {'device_id': 'right-usb', 'rotation': 0}}
        self.rig.configure(self.config)
        self.frame = np.arange(4*6*3, dtype=np.uint8).reshape(4, 6, 3)

    def tearDown(self):
        self.rig.release()
        self.folder.cleanup()

    def publish(self, eye, frame=None):
        self.rig._publish(eye, self.rig.config[eye], self.frame if frame is None else frame, self.now)

    def test_left_rotates_before_tracking_right_keeps_original_pixels(self):
        self.publish('left')
        self.publish('right')
        ok, frame = self.rig.read()
        self.assertTrue(ok)
        np.testing.assert_array_equal(frame, self.frame[::-1, ::-1])
        np.testing.assert_array_equal(self.rig.samples['right']['frame'], self.frame)
        self.assertIsNotNone(self.rig.jpeg('left'))
        self.assertFalse(self.rig.read()[0], 'Do not process a captured sample twice')

    def test_assignments_persist_and_no_device_is_automatically_substituted(self):
        restored = EyeCameraRig(lambda: self.devices, self.rig.path)
        self.assertEqual(restored.config, self.config)
        self.rig.opener = Mock()
        self.rig._open('left', 'left-usb')
        self.rig.opener.assert_called_with(2)
        self.devices = [dict(self.devices[1], index=2)]
        with self.assertRaises(ValueError):
            self.rig._open('left', 'left-usb')
        self.rig.opener.assert_called_once()

    def test_reject_duplicate_unknown_and_head_camera_ids_without_mutation(self):
        for device in ('left-usb', 'unknown', 'face'):
            config = copy.deepcopy(self.config)
            config['right']['device_id'] = device
            self.rig.excluded_id = 'face'
            with self.assertRaises(ValueError):
                self.rig.configure(config)
            self.assertEqual(self.rig.config, self.config)
        for rotation in (90, True, '180'):
            config = copy.deepcopy(self.config)
            config['left']['rotation'] = rotation
            with self.assertRaises(ValueError):
                self.rig.configure(config)

    def test_missing_other_eye_and_stale_preview_do_not_substitute_tracking(self):
        self.publish('left')
        self.assertTrue(self.rig.read()[0])
        state = self.rig.status()
        self.assertTrue(state['eyes']['left']['connected'])
        self.assertFalse(state['eyes']['right']['connected'])
        self.now += .6
        self.publish('right')
        self.assertFalse(self.rig.read()[0])
        self.assertIsNone(self.rig.jpeg('left'))
        self.assertEqual(self.rig.status()['eyes']['left']['fps'], 0)
        self.assertIsNotNone(self.rig.jpeg('right'))

    def test_orientation_change_drops_old_pixels_and_invalidates_calibration(self):
        calibration = Calibration('Left eye camera')
        calibration.eye_cameras = self.rig
        calibration.onboarding = Mock()
        # Let real reset execute through the mocked onboarding arm callback.
        calibration.onboarding.arm.side_effect = calibration.reset_eye_model
        calibration.eye_region = (.1, .1, .9, .9)
        calibration.matrix = np.eye(3)
        calibration.latest = {'time': self.now, 'result': None}
        self.publish('left')
        calibration.diagnostic_jpeg = b'old'
        config = copy.deepcopy(self.config)
        config['left']['rotation'] = 0
        calibration.configure_eye_cameras(config)
        self.assertFalse(self.rig.read()[0])
        self.assertIsNone(calibration.matrix)
        self.assertIsNone(calibration.latest)
        self.assertIsNone(calibration.eye_region)
        self.assertIsNone(calibration.diagnostic_jpeg)
        self.assertEqual(calibration.onboarding.orientation, (False, False))
        self.rig._publish('left', self.config['left'], self.frame, self.now)
        self.assertIsNone(self.rig.jpeg('left'), 'Discard an in-flight frame from the old orientation')
        self.publish('left')
        np.testing.assert_array_equal(self.rig.read()[1], self.frame)

    def test_preview_eye_changes_preserve_active_calibration_and_no_duplicate_sample(self):
        calibration = Calibration('Left eye camera')
        calibration.eye_cameras = self.rig
        calibration.matrix = np.eye(3)
        self.publish('left')
        self.rig.read()
        config = copy.deepcopy(self.config)
        config['right']['rotation'] = 180
        calibration.configure_eye_cameras(config)
        self.assertIsNotNone(calibration.matrix)
        self.assertFalse(self.rig.read()[0])
        config['active_eye'] = 'right'
        calibration.configure_eye_cameras(config)
        self.assertIsNone(calibration.matrix)
        self.assertEqual(calibration.eye_camera_id, 'right-usb')

    def test_reopening_same_camera_marks_recovered(self):
        self.publish('left')
        self.rig.read()
        self.assertFalse(self.rig.recovered)
        self.rig.sessions['left'] += 1
        self.now += .1
        self.publish('left')
        self.rig.read()
        self.assertTrue(self.rig.recovered)

    def test_http_setup_and_preview_routes(self):
        calibration = Calibration('Left eye camera')
        calibration.eye_cameras = self.rig
        handler_type = make_handler(calibration)
        def request(path, body=None):
            handler = handler_type.__new__(handler_type)
            handler.path = path
            data = json.dumps(body).encode() if body is not None else b''
            handler.headers = {'Content-Length': str(len(data))}
            handler.rfile = io.BytesIO(data)
            handler.wfile = io.BytesIO()
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            (handler.do_POST if body is not None else handler.do_GET)()
            return handler.send_response.call_args.args[0], handler.wfile.getvalue()
        status, data = request('/eye-cameras', self.config)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['eye_cameras']['active_eye'], 'left')
        duplicate = copy.deepcopy(self.config)
        duplicate['right']['device_id'] = 'left-usb'
        self.assertEqual(request('/eye-cameras', duplicate)[0], 400)
        malformed = copy.deepcopy(self.config)
        del malformed['left']['device_id']
        self.assertEqual(request('/eye-cameras', malformed)[0], 400)
        self.assertEqual(request('/diagnostics/right.jpg')[0], 503)
        self.publish('left')
        status, data = request('/diagnostics/left.jpg')
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b'\xff\xd8'))

    def test_both_streams_capture_independently_and_release(self):
        captures = []
        def open_camera(index):
            capture = Mock()
            capture.isOpened.return_value = True
            def read():
                time.sleep(.01)
                return True, self.frame.copy()
            capture.read.side_effect = read
            captures.append((index, capture))
            return capture
        self.rig.opener = open_camera
        self.rig.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not all(self.rig.status()['eyes'][e]['connected'] for e in ('left', 'right')):
            time.sleep(.01)
        self.assertEqual({i for i, _ in captures}, {0, 2})
        self.assertTrue(all(self.rig.status()['eyes'][e]['connected'] for e in ('left', 'right')))
        self.rig.release()
        for _, capture in captures:
            capture.release.assert_called_once()

    def test_second_eye_detects_without_primary_and_rejects_old_results(self):
        calibration = Calibration('Left eye camera')
        calibration.eye_cameras = self.rig
        detector = Mock()
        detector.get_last_tracking_result.return_value = {
            'pupil_ellipse': {'center': [320, 240], 'axes': [80, 64], 'angle_degrees': 20},
            'confidence': .9, 'gaze_direction': [0, 0, 1]}
        worker = CompanionEyeTracker(calibration, render_diagnostic_frame, detector)
        self.publish('right')
        sample = self.rig.snapshot('right')
        self.assertTrue(worker.process_next())
        self.assertFalse(worker.process_next(), 'Do not detect the same frame twice')
        detector.process_frame.assert_called_once()
        detector.reset_tracking_state.assert_called_once()
        self.assertFalse(self.rig.active_fresh())
        self.assertEqual(self.rig.status()['eyes']['right']['tracking'], 'Pupil tracked')
        self.assertEqual(self.rig.status()['eyes']['right']['pupil_center'], [320, 240])
        self.assertNotEqual(self.rig.jpeg('right'), sample['jpeg'], 'Publish detection overlays, not just raw video')
        self.assertIsNone(calibration.latest, 'Do not mix the second eye into a single-eye mapping')
        config = copy.deepcopy(self.config)
        config['right']['rotation'] = 180
        self.rig.configure(config)
        self.publish('right')
        self.rig.publish_tracking('right', sample, detector.get_last_tracking_result(), b'old', .5)
        self.assertNotIn('right', self.rig.tracking)
        self.assertTrue(worker.process_next())
        self.assertEqual(detector.reset_tracking_state.call_count, 2)
        np.testing.assert_array_equal(detector.process_frame.call_args.args[0], self.frame[::-1, ::-1])
        self.now += .6
        self.assertIsNone(self.rig.jpeg('right'))
        self.assertIsNone(self.rig.status()['eyes']['right']['confidence'])
        self.assertEqual(self.rig.status()['eyes']['right']['tracking_fps'], 0)

    def test_independent_real_detectors_keep_distinct_pupils_and_history(self):
        import cv2
        from test_iris_edge_detection import eye
        first, second = independent_detector(), independent_detector()
        first.pupil_confidence_threshold = second.pupil_confidence_threshold = .5
        for stamp in (10, 10.04):
            for detector, center in ((first, (240, 220)), (second, (400, 260))):
                gray, _, _ = eye(center=center)
                detector.process_frame(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), timestamp=stamp)
        for detector, center in ((first, (240, 220)), (second, (400, 260))):
            pupil = detector.get_last_tracking_result()['pupil_ellipse']['center']
            np.testing.assert_allclose(pupil, center, atol=3)
        self.assertIsNot(first._pupil_track, second._pupil_track)
        self.assertIsNot(first.ray_lines, second.ray_lines)
        first.reset_tracking_state()
        self.assertIsNotNone(second.get_last_tracking_result())

    def test_scene_directions_require_valid_modeled_pupils_and_paired_head(self):
        pose = [0., 0., 0., .5, .4, -1.2]
        result = {'pupil_ellipse': {'center': [320, 240]}, 'confidence': .9,
                  'gaze_direction': [.1, .2, .97], 'eye_model_estimated': True,
                  'head_pose': {'features': pose}}
        for eye in ('left', 'right'):
            self.publish(eye)
            self.rig.publish_tracking(eye, self.rig.snapshot(eye), result, b'jpg', .5)
        directions = self.rig.status()['eyes']
        self.assertEqual(directions['left']['scene_direction']['head_features'], pose)
        self.assertEqual(directions['right']['scene_direction']['vector'], [.1, .2, .97])
        for invalid in (dict(result, confidence=.1), dict(result, eye_model_estimated=False),
                        dict(result, head_pose=None), dict(result, gaze_direction=[0, 0, 0]),
                        dict(result, gaze_direction=[float('nan'), 0, 1])):
            self.publish('left')
            self.rig.publish_tracking('left', self.rig.snapshot('left'), invalid, b'jpg', .5)
            self.assertIsNone(self.rig.status()['eyes']['left']['scene_direction'])
            self.assertIsNotNone(self.rig.status()['eyes']['right']['scene_direction'])
        self.rig.sessions['right'] += 1
        self.publish('right')
        self.assertIsNone(self.rig.status()['eyes']['right']['scene_direction'], 'Old-session rays must disappear immediately')
        self.now += .6
        self.assertTrue(all(slot['scene_direction'] is None for slot in self.rig.status()['eyes'].values()))

    def test_companion_pairs_head_to_its_own_capture_time(self):
        calibration = Calibration('Left eye camera')
        calibration.eye_cameras = self.rig
        calibration.head_camera = Mock()
        pose = {'features': [0., 0., 0., .5, .4, -1.2]}
        calibration.head_camera.sample_at.return_value = pose
        detector = Mock()
        detector.get_last_tracking_result.return_value = {
            'pupil_ellipse': {'center': [320, 240], 'axes': [80, 64], 'angle_degrees': 0},
            'confidence': .9, 'gaze_direction': [0, 0, 1], 'eye_model_estimated': True}
        worker = CompanionEyeTracker(calibration, render_diagnostic_frame, detector)
        self.publish('right')
        worker.process_next()
        calibration.head_camera.sample_at.assert_called_once_with(self.now)
        self.assertEqual(self.rig.status()['eyes']['right']['scene_direction']['head_features'], pose['features'])
        self.assertIsNone(calibration.latest, 'Scene rays must not feed the single cursor calibration')


if __name__ == '__main__':
    unittest.main()
