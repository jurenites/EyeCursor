"""Hands-free onboarding through the real calibration state machine."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import Orlosky3DEyeTracker as tracker
from monitor_demo import Calibration
from onboarding import Onboarding, VERIFY_TARGETS, MAX_ORBIT_SECONDS


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.serial = 0
        clock = patch('monitor_demo.time.monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'profile.json'
        self.displays = [{'id': 'one', 'viewport': [0, 0, 1920, 1080]},
                         {'id': 'two', 'viewport': [1920, -200, 1600, 900]}]
        self.new_flow()

    def tearDown(self):
        tracker.reset_tracking_state()

    def new_flow(self, displays=None, source='USB-id'):
        self.c = Calibration('USB Camera', require_eye_model=True)
        self.flow = Onboarding(self.c, self.path, source, clock=lambda: self.now)
        self.c.onboarding = self.flow
        self.flow.configure(displays or self.displays)

    def feed(self, target=(.5, .5), count=1, good=True, eye_shift=0):
        for _ in range(count):
            self.now += 1 / 30
            self.serial += 1
            index = min(self.flow.index, len(self.flow.displays) - 1)
            feature = [target[0] * .3 - .5 + index * .7, target[1] * .3 - .15, 1]
            angle = self.serial / 8
            result = {'pupil_ellipse': {'center': [320 + 30 * math.cos(angle), 240 + 25 * math.sin(angle)]},
                      'confidence': .95 if good else .1, 'gaze_direction': feature,
                      'eye_center': [320 + eye_shift, 240], 'sphere_radius': 60,
                      'eye_model_estimated': True, 'eye_model_samples': 60}
            if self.flow.phase == 'fitting':
                tracker.prev_model_center_avg = (320 + eye_shift, 240)
                tracker.max_observed_distance = 60
            self.c.add_frame(result if good else None)

    def fit_eye(self, eye_shift=0):
        for _ in range(250):
            self.feed(eye_shift=eye_shift)
            if self.flow.phase in ('screen', 'verify'):
                return
        self.fail('Automatic eye fitting did not advance')

    def finish(self):
        for _ in range(800):
            if self.flow.phase == 'complete':
                return
            state = self.flow.state(self.now)
            self.assertIn(state['phase'], ('screen', 'verify'))
            self.assertIsNone(self.c.state()['desktop_gaze'])
            self.feed(state['target'])
        self.fail('Monitor calibration did not complete')

    def full_profile(self):
        self.fit_eye()
        self.finish()
        self.assertTrue(self.path.exists())

    def test_wear_look_around_and_two_displays_complete_without_actions(self):
        started = self.now
        self.fit_eye()
        self.assertFalse(tracker.eye_sphere_adjustment_enabled)
        self.assertEqual(self.flow.phase, 'screen')
        self.finish()
        self.assertLess(self.now - started, 60)
        self.assertEqual(len(self.flow.maps), 2)
        self.assertTrue(self.c.state()['calibrated'])
        self.assertTrue(np.allclose(self.flow.desktop_point([-.35, 0]), [960, 540]))
        self.assertTrue(np.allclose(self.flow.desktop_point([.35, 0]), [2720, 250]))
        self.assertIsNone(self.flow.desktop_point([0, 0]))
        print(f'\nSynthetic two-display onboarding: {self.now - started:.1f}s')

    def test_brief_detection_misses_do_not_prevent_automatic_start(self):
        for i in range(30):
            self.feed(good=i % 4 != 0)
        self.assertEqual(self.flow.phase, 'fitting')

    def test_returning_fit_requires_three_checks_per_display(self):
        self.full_profile()
        self.new_flow()
        started = self.now
        self.fit_eye()
        self.assertEqual(self.flow.phase, 'verify')
        self.assertTrue(self.flow.fast_path)
        self.assertIsNone(self.c.state()['desktop_gaze'])
        self.finish()
        self.assertTrue(self.flow.fast_path)
        self.assertLess(self.now - started, 20)
        print(f'Synthetic returning-wearer verification: {self.now - started:.1f}s')

    def test_failed_quick_check_falls_back_to_full_dots(self):
        self.full_profile()
        self.new_flow()
        self.fit_eye()
        self.assertEqual(self.flow.phase, 'verify')
        self.feed((.9, .9), 45)
        self.assertEqual(self.flow.phase, 'screen')
        self.assertFalse(self.flow.fast_path)
        self.assertFalse(self.c.state()['calibrated'])
        self.finish()

    def test_changed_eye_fit_or_device_never_reuses_profile(self):
        self.full_profile()
        self.new_flow()
        self.fit_eye(eye_shift=30)
        self.assertEqual(self.flow.phase, 'screen')
        self.new_flow(source='different-camera')
        self.fit_eye()
        self.assertEqual(self.flow.phase, 'screen')

    def test_stationary_eye_and_missing_frames_never_start_cursor(self):
        self.feed(good=False, count=60)
        self.assertEqual(self.flow.phase, 'waiting')
        self.fit_eye()
        self.feed((.5, .5), count=200)
        self.assertFalse(self.c.state()['calibrated'])
        self.feed((.5, .5), count=1800)
        self.assertEqual(self.c.state()['onboarding']['phase'], 'paused')
        self.assertIsNone(self.c.state()['desktop_gaze'])

    def test_explicit_cancel_stays_cancelled_and_display_change_restarts(self):
        self.fit_eye()
        self.flow.cancel()
        self.feed(count=250)
        self.assertEqual(self.flow.phase, 'cancelled')
        self.flow.configure([self.displays[0]])
        self.assertEqual(self.flow.phase, 'waiting')
        self.fit_eye()
        self.finish()

    def test_stale_tracking_and_ambiguous_display_maps_hide_cursor(self):
        self.full_profile()
        self.feed()
        self.now += .6
        self.assertIsNone(self.c.state()['desktop_gaze'])
        self.flow.maps[1]['matrix'] = self.flow.maps[0]['matrix']
        self.assertIsNone(self.flow.desktop_point([-.35, 0]))
        self.now += 3
        self.c.state()
        self.assertEqual(self.flow.phase, 'complete')

    def test_two_rotations_is_a_hard_limit_and_never_restarts_automatically(self):
        self.feed(count=18)
        self.assertEqual(self.flow.phase, 'fitting')
        self.now = self.flow.started_at + MAX_ORBIT_SECONDS - .01
        self.assertEqual(self.flow.state(self.now)['phase'], 'fitting')
        self.now += .02
        self.assertEqual(self.flow.state(self.now)['phase'], 'paused')
        self.feed(count=300)
        self.assertEqual(self.flow.phase, 'paused')
        self.assertFalse(self.c.state()['calibrated'])
        self.assertEqual(self.flow.message, 'Calibration paused')

    def test_failed_five_point_check_does_not_repeat(self):
        self.fit_eye()
        self.c.native['phase'] = 'retry'
        self.feed()
        self.assertEqual(self.flow.phase, 'paused')
        self.feed(count=150)
        self.assertEqual(self.flow.phase, 'paused')
        self.assertFalse(self.c.state()['calibrated'])

    def test_single_display_uses_exactly_five_fixations_then_shows_cursor(self):
        self.new_flow(displays=[self.displays[0]])
        self.fit_eye()
        visited = []
        for _ in range(400):
            if self.flow.phase == 'complete':
                break
            target = self.flow.state(self.now)['target']
            if not visited or visited[-1] != target:
                visited.append(target)
            self.feed(target)
        self.assertEqual(visited, [[.5, .5], [.08, .08], [.92, .08], [.92, .92], [.08, .92]])
        self.assertEqual(self.flow.phase, 'complete')
        self.feed()
        self.assertTrue(self.c.state()['display_valid'])
        self.feed(good=False, count=150)
        self.assertEqual(self.flow.phase, 'complete')
        self.assertFalse(self.c.state()['display_valid'])
        self.feed()
        self.assertTrue(self.c.state()['display_valid'])

    def test_corrupt_profile_and_changed_layout_use_full_calibration(self):
        self.path.write_text('{not json')
        self.fit_eye()
        self.assertEqual(self.flow.phase, 'screen')
        self.finish()
        self.new_flow(displays=[self.displays[0]])
        self.fit_eye()
        self.assertEqual(self.flow.phase, 'screen')

    def test_profile_contains_only_parameters_and_rejects_invalid_matrix(self):
        self.full_profile()
        data = json.loads(self.path.read_text())
        self.assertEqual(set(data), {'version', 'context', 'eye', 'maps'})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        data['maps'][0]['matrix'] = [[0]*3]*3
        self.path.write_text(json.dumps(data))
        self.new_flow()
        self.assertIsNone(self.flow.load_profile())


if __name__ == '__main__':
    unittest.main()
