"""Two-stage calibration gates and original-estimator integration."""
import math
import random
import unittest
from unittest.mock import patch
import numpy as np

from eye_model import EyeModelCalibration
from monitor_demo import Calibration
import Orlosky3DEyeTracker as tracker


def result(index, confidence=.95, moving=True, unstable=False, samples=60):
    return {'pupil_ellipse': {'center': [320 + (30 * math.cos(index / 8) if moving else 0),
                                       240 + (25 * math.sin(index / 8) if moving else 0)]},
            'confidence': confidence, 'gaze_direction': [.2, .1, 1],
            'eye_center': [320 + (30 * (index % 2) if unstable else 0), 240],
            'sphere_radius': 60, 'eye_model_estimated': True, 'eye_model_samples': samples}


class EyeModelTests(unittest.TestCase):
    def tearDown(self):
        tracker.eye_region = None
        tracker.reset_tracking_state()

    def collect(self, **kwargs):
        model = EyeModelCalibration()
        model.start()
        for i in range(120):
            model.observe(result(i, **kwargs), i / 30)
        return model

    def test_stationary_low_confidence_unstable_and_insufficient_fit_rejected(self):
        for kwargs in ({'moving': False}, {'confidence': .4}, {'unstable': True}, {'samples': 29}):
            with self.subTest(kwargs=kwargs):
                model = self.collect(**kwargs)
                self.assertFalse(model.status(4)['can_freeze'])
                with self.assertRaises(ValueError):
                    model.freeze(4)

    def test_configurable_threshold_accepts_more_candidates_without_skipping_geometry(self):
        model = EyeModelCalibration(threshold=.4)
        model.start()
        self.assertEqual(model.threshold, .4)
        for i in range(120):
            model.observe(result(i, confidence=.45), i / 30)
        self.assertTrue(model.status(4)['can_freeze'])
        model.threshold = .6
        model.start()
        for i in range(120):
            model.observe(result(i, confidence=.45), i / 30)
        self.assertFalse(model.status(4)['can_freeze'])

    def test_varied_stable_eye_model_can_be_fixed_and_remains_fixed(self):
        model = self.collect()
        self.assertTrue(model.status(4)['can_freeze'])
        model.freeze(4)
        size = len(model.estimates)
        model.observe(result(121, unstable=True), 4.1)
        self.assertEqual(len(model.estimates), size)
        self.assertEqual(model.status(4.1)['phase'], 'ready')

    def test_old_frames_cannot_approve_model(self):
        model = self.collect()
        self.assertFalse(model.status(5)['can_freeze'])

    def test_progress_tracks_evidence_and_explains_missing_movement(self):
        model = EyeModelCalibration()
        model.start()
        self.assertEqual(model.status(0)['progress'], 0)
        model.observe(result(0, confidence=.4), 1)
        self.assertEqual(model.status(10)['progress'], 0)
        for i in range(90):
            model.observe(result(i, moving=False), 10 + i / 30)
        status = model.status(13)
        self.assertGreater(status['progress'], 0)
        self.assertLess(status['progress'], 1)
        self.assertIn('movement', status['message'])
        self.assertFalse(status['can_freeze'])
        complete = self.collect().status(4)
        self.assertEqual(complete['progress'], 1)
        self.assertTrue(complete['can_freeze'])

    def test_stability_window_supports_different_capture_rates(self):
        for fps in (15, 30, 60, 120):
            with self.subTest(fps=fps):
                model = EyeModelCalibration()
                model.start()
                for i in range(4 * fps):
                    model.observe(result(i * 30 / fps), i / fps)
                self.assertTrue(model.status(4)['can_freeze'])

    def test_monitor_stage_blocked_until_eye_stage_accepted(self):
        calibration = Calibration('USB Camera', require_eye_model=True)
        with self.assertRaisesRegex(ValueError, 'step 1'):
            calibration.start_native([0, 0, 1920, 1080])
        with self.assertRaisesRegex(ValueError, 'eye model'):
            calibration.capture('top_left', [0, 0, 1920, 1080])
        calibration.start_eye_model()
        for i in range(120):
            with patch('monitor_demo.time.monotonic', return_value=i / 30):
                calibration.add_frame(result(i))
        with patch('monitor_demo.time.monotonic', return_value=4):
            calibration.freeze_eye_model()
            calibration.start_native([0, 0, 1920, 1080])
        self.assertFalse(tracker.eye_sphere_adjustment_enabled)
        self.assertEqual(calibration.native['phase'], 'collecting')
        calibration.reset()
        self.assertEqual(calibration.eye_model.phase, 'ready')
        calibration.set_eye_region([.1, .1, .9, .9])
        self.assertEqual(calibration.eye_model.phase, 'uncalibrated')
        self.assertIsNone(calibration.native)

    def test_restart_reconnect_and_interruption_invalidate_pending_work(self):
        calibration = Calibration('USB Camera')
        calibration.eye_model = self.collect()
        calibration.interrupt_stream()
        self.assertFalse(calibration.eye_model.status(4)['can_freeze'])
        calibration.eye_model.phase = 'ready'
        calibration.start_native([0, 0, 1920, 1080])
        calibration.reset_eye_model()
        self.assertIsNone(calibration.native)
        self.assertEqual(calibration.eye_model.phase, 'uncalibrated')
        calibration.start_eye_model()
        self.assertEqual(calibration.eye_model.phase, 'collecting')
        self.assertEqual(tracker.model_centers, [])

    def test_robust_ray_estimator_recovers_known_center(self):
        tracker.reset_tracking_state()
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        rays = [((320 + 50 * math.cos(math.radians(a)), 240 + 50 * math.sin(math.radians(a))),
                 (20, 30), a) for a in range(0, 360, 10)]
        with patch.object(tracker.random, 'sample', side_effect=random.Random(42).sample):
            centers = [tracker.compute_average_intersection(image, rays, 4, 1500, 8) for _ in range(60)]
        for center in centers:
            self.assertLess(np.linalg.norm(np.array(center) - [320, 240]), 2)


if __name__ == '__main__':
    unittest.main()
