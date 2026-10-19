"""Temporal rejection and recovery on deterministic frame timestamps."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import Orlosky3DEyeTracker as tracker
from pupil_tracking import PupilTrack, observation
from test_iris_edge_detection import eye
from monitor_demo import Calibration, usable


def ellipse(center=(320, 240), axes=(80, 64), angle=20):
    return (center, axes, angle)


def iris(center=(320, 240), axes=(200, 160), angle=20):
    return {'ellipse': ellipse(center, axes, angle), 'support': .95}


class PupilTrackTests(unittest.TestCase):
    def setUp(self):
        self.track = PupilTrack()
        self.track.update(ellipse(), .9, iris(), 0.)

    def update(self, pupil, now=1/30, confidence=.9, guide=None):
        return self.track.update(pupil, confidence, guide, now)

    def test_half_and_double_size_are_rejected_and_do_not_train_history(self):
        for i, axes in enumerate(((40, 32), (160, 128)), 1):
            result = self.update(ellipse(axes=axes), i/30, guide=iris())
            self.assertEqual(result, {'accepted': False, 'reason': 'size-jump'})
            self.assertEqual(len(self.track.history), 1)
        self.assertTrue(self.update(ellipse(), 3/30, guide=iris())['accepted'])

    def test_gradual_size_changes_and_fast_eye_motion_are_accepted(self):
        for i in range(1, 10):
            pupil = ellipse(center=(320 + min(i, 2)*20, 240), axes=(80-i, 64-.8*i))
            self.assertTrue(self.update(pupil, i/30, guide=iris())['accepted'])

    def test_iris_scaling_and_translation_compensate_camera_motion(self):
        result = self.update(ellipse(center=(180, 180), axes=(40, 32)),
                             guide=iris(center=(180, 180), axes=(100, 80)))
        self.assertTrue(result['accepted'])

    def test_shape_orientation_and_remote_position_jumps_are_rejected(self):
        for pupil, reason in ((ellipse(axes=(80, 25)), 'shape-jump'),
                              (ellipse(angle=110), 'angle-jump'),
                              (ellipse(center=(50, 50)), 'position-jump')):
            with self.subTest(reason=reason):
                self.setUp()
                result = self.update(pupil)
                self.assertEqual(result, {'accepted': False, 'reason': reason})

    def test_swapped_axes_wrapped_angles_and_circular_angles_are_equivalent(self):
        self.assertTrue(self.update(ellipse(axes=(64, 80), angle=110))['accepted'])
        self.assertTrue(self.update(ellipse(angle=200), 2/30)['accepted'])
        circle = PupilTrack()
        circle.update(ellipse(axes=(80, 80)), .9, None, 0)
        self.assertTrue(circle.update(ellipse(axes=(80, 80), angle=110), .9, None, 1/30)['accepted'])

    def test_iris_rotation_and_foreshortening_are_compensated(self):
        self.assertTrue(self.update(ellipse(axes=(80, 32), angle=100),
                                   guide=iris(axes=(200, 80), angle=100))['accepted'])

    def test_weak_candidates_cannot_poison_history_or_confirm_reacquisition(self):
        self.assertTrue(self.update(ellipse(axes=(90, 72)), confidence=.4)['accepted'])
        self.assertEqual(len(self.track.history), 1)
        for i in range(2, 8):
            self.assertFalse(self.update(ellipse(axes=(40, 32)), i/30, confidence=.4)['accepted'])
        self.assertEqual(len(self.track.history), 1)
        self.assertFalse(self.track.pending)

    def test_persistent_new_geometry_reacquires_using_current_evidence(self):
        for i in range(1, 4):
            self.assertFalse(self.update(ellipse(axes=(40, 32)), i/30, guide=iris())['accepted'])
        result = self.update(ellipse(axes=(40, 32)), 4/30, guide=iris())
        self.assertEqual(result, {'accepted': True, 'reason': 'reacquired'})

    def test_inconsistent_outliers_do_not_confirm_a_new_track(self):
        for i in range(1, 9):
            axes = (40, 32) if i % 2 else (160, 128)
            self.assertFalse(self.update(ellipse(axes=axes), i/30, guide=iris())['accepted'])

    def test_blink_never_outputs_prediction_and_long_loss_expires_history(self):
        for now in (.03, .06, .4):
            self.assertEqual(self.update(None, now), {'accepted': False, 'reason': 'missing'})
        self.assertFalse(self.track.history)
        self.assertTrue(self.update(ellipse(axes=(40, 32)), .43)['accepted'])

    def test_short_blink_keeps_reference_and_interrupts_pending_reacquisition(self):
        self.assertFalse(self.update(ellipse(axes=(40, 32)), .03)['accepted'])
        self.update(None, .06)
        self.assertFalse(self.track.pending)
        self.assertFalse(self.update(ellipse(axes=(40, 32)), .09)['accepted'])
        self.assertTrue(self.update(ellipse(), .12)['accepted'])

    def test_reset_seek_and_long_capture_gap_start_a_new_track(self):
        for method in ('reset', 'seek', 'gap'):
            with self.subTest(method=method):
                self.setUp()
                if method == 'reset': self.track.reset()
                now = -.1 if method == 'seek' else .5 if method == 'gap' else .03
                self.assertEqual(self.update(ellipse(axes=(40, 32)), now)['reason'], 'acquired')

    def test_invalid_geometry_and_time_are_rejected(self):
        for pupil in (ellipse(axes=(0, 30)), ellipse(center=(float('nan'), 200))):
            self.assertFalse(self.update(pupil)['accepted'])
        self.assertFalse(self.update(ellipse(), float('nan'))['accepted'])

    def test_velocity_prediction_follows_motion_and_stopping(self):
        self.update(ellipse(center=(335, 240)), .03)
        prediction = self.track.predicted_center(observation(ellipse(center=(350, 240)), .06))
        self.assertGreater(prediction[0], 335)
        self.assertTrue(self.update(ellipse(center=(350, 240)), .06)['accepted'])
        self.assertTrue(self.update(ellipse(center=(350, 240)), .09)['accepted'])

    def test_duplicate_timestamp_cannot_reset_history_or_confirm_outlier(self):
        self.assertFalse(self.update(ellipse(axes=(40, 32)), 0)['accepted'])
        self.assertEqual(len(self.track.history), 1)
        self.assertFalse(self.update(ellipse(axes=(40, 32)), .03)['accepted'])


class TemporalPipelineTests(unittest.TestCase):
    def setUp(self):
        tracker.reset_tracking_state()
        self.display = patch.object(tracker, 'DISPLAY_ENABLED', False)
        self.display.start()

    def tearDown(self):
        self.display.stop()
        tracker.reset_tracking_state()

    def process(self, scale, timestamp):
        gray, _, _ = eye(scale=scale)
        tracker.process_frame(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), timestamp=timestamp)
        return tracker.get_last_tracking_result()

    def test_half_size_frame_cannot_update_model_calibration_or_gaze(self):
        first = self.process(.5, 0)
        self.assertTrue(first['temporal_tracking']['accepted'])
        rays, radius = list(tracker.ray_lines), tracker.max_observed_distance
        with patch.object(tracker, 'compute_average_intersection') as fit, \
                patch.object(tracker, 'update_eye_sphere_radius') as sphere:
            rejected = self.process(.25, 1/30)
        self.assertEqual(rejected['temporal_tracking']['reason'], 'size-jump')
        self.assertEqual(rejected['confidence'], 0)
        self.assertNotIn('gaze_direction', rejected)
        self.assertFalse(usable(rejected, .01))
        self.assertTrue(rejected['pupil_ellipse'], 'A rejected candidate must not count as a blink')
        self.assertEqual(tracker.ray_lines, rays)
        self.assertEqual(tracker.max_observed_distance, radius)
        fit.assert_not_called()
        sphere.assert_not_called()
        calibration = Calibration('test')
        calibration.add_frame(rejected)
        self.assertFalse(calibration.samples)
        self.assertEqual(calibration.state()['detection_evidence']['temporal_tracking']['reason'], 'size-jump')
        self.assertTrue(self.process(.5, 2/30)['temporal_tracking']['accepted'])

    def test_repeated_current_edges_can_reacquire_after_size_change(self):
        self.process(.5, 0)
        for i in range(1, 4):
            self.assertFalse(self.process(.25, i/30)['temporal_tracking']['accepted'])
        self.assertEqual(self.process(.25, 4/30)['temporal_tracking']['reason'], 'reacquired')

    def test_video_timestamp_uses_source_fps_not_processing_speed(self):
        class Capture:
            def get(self, prop):
                return 30. if prop == cv2.CAP_PROP_FPS else 4.
        self.assertAlmostEqual(tracker.video_frame_timestamp(Capture()), .1)


if __name__ == '__main__':
    unittest.main()
