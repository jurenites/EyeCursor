"""Screen motion regressions: spikes, sustained moves, polling and dropouts."""
import unittest
from unittest.mock import patch

import numpy as np

from screen_gaze import ScreenGazeMotion
from monitor_demo import Calibration
from test_monitor_demo import frame


class ScreenGazeTests(unittest.TestCase):
    def setUp(self):
        self.motion = ScreenGazeMotion()
        self.viewport = (0, 0, 1920, 1080)
        self.update((960, 540), 0)

    def update(self, point, now, viewport=None, context='camera'):
        self.motion.update(point, viewport or self.viewport, now, context)
        return self.motion.sample(now)

    def test_single_far_spike_never_moves_toward_the_wrong_corner(self):
        self.assertEqual(self.update((100, 100), 1/30), [960, 540])
        self.assertFalse(self.motion.accepted)
        self.assertEqual(self.update((960, 540), 2/30), [960, 540])
        self.assertTrue(self.motion.accepted)

    def test_single_small_spike_is_removed_by_median(self):
        self.assertEqual(self.update((1050, 540), 1/30), [960, 540])
        self.assertEqual(self.update((960, 540), 2/30), [960, 540])

    def test_confirmed_saccade_eases_to_target_without_overshoot(self):
        samples = [self.update((1700, 900), i/30) for i in range(1, 20)]
        self.assertEqual(samples[0], [960, 540])
        self.assertEqual(samples[1], [960, 540])
        self.assertTrue(960 < samples[2][0] < 1700)
        self.assertLess(np.linalg.norm(np.asarray(samples[11]) - [1700, 900]), 15)
        self.assertTrue(all(a[0] <= b[0] <= 1700 and a[1] <= b[1] <= 900
                            for a, b in zip(samples, samples[1:])))

    def test_erratic_far_candidates_expire_instead_of_chasing_them(self):
        for i in range(1, 20):
            point = (100, 100) if i % 2 else (1800, 1000)
            shown = self.update(point, i/30)
            self.assertEqual(shown, [960, 540] if i/30 <= .25 else None)

    def test_polling_same_frame_cannot_confirm_or_advance_motion(self):
        for _ in range(100):
            self.assertEqual(self.update((100, 100), 1/30), [960, 540])
        self.assertEqual(len(self.motion.pending), 1)

    def test_missing_frame_interrupts_confirmation_and_long_gap_restarts(self):
        self.update((100, 100), .03)
        self.motion.interrupt_confirmation()
        self.assertEqual(self.update((100, 100), .09), [960, 540])
        self.assertIsNone(self.motion.sample(.4))
        self.assertEqual(self.update((100, 100), .7), [100, 100])

    def test_monitor_switch_is_confirmed_before_repositioning(self):
        external = (-1920, 0, 1920, 1080)
        self.assertEqual(self.update((-960, 540), .03, external), [960, 540])
        self.assertEqual(self.update((-960, 540), .06, external), [960, 540])
        self.assertEqual(self.update((-960, 540), .09, external), [-960, 540])
        self.assertEqual(self.motion.viewport, external)

    def test_reset_and_changed_calibration_do_not_keep_old_screen_location(self):
        self.assertEqual(self.update((100, 100), .03, context='new-map'), [100, 100])
        self.motion.reset()
        self.assertIsNone(self.motion.sample(.04))

    def test_noise_range_is_reduced_and_behavior_scales_with_resolution(self):
        outputs = []
        scaled = ScreenGazeMotion()
        scaled.update((1920, 1080), (0, 0, 3840, 2160), 0, 'camera')
        for i in range(1, 121):
            point = (960 + (24 if i % 2 else -24), 540)
            shown = self.update(point, i/30)
            scaled.update(np.asarray(point)*2, (0, 0, 3840, 2160), i/30, 'camera')
            self.assertTrue(np.allclose(np.asarray(shown)*2, scaled.sample(i/30)))
            if i > 30: outputs.append(shown[0])
        self.assertLess(np.ptp(outputs), 12)

    def test_invalid_input_and_reversed_clock_clear_previous_motion(self):
        self.assertIsNone(self.update((float('nan'), 540), .03))
        self.assertEqual(self.update((100, 100), .1), [100, 100])
        self.assertEqual(self.update((1800, 900), .01), [1800, 900])


class ScreenGazePipelineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.clock = patch('monitor_demo.time.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.c = Calibration('test', desktop_cursor=True)
        self.c.matrix = np.eye(3)
        self.c.viewport = [0, 0, 1920, 1080]
        self.feed(.5, .5)

    def tearDown(self):
        self.clock.stop()

    def feed(self, x, y, confidence=.9):
        self.now += 1/30
        self.c.add_frame(frame(x, y, confidence))
        return self.c.state()

    def test_arrow_and_cursor_share_filter_but_calibration_retains_raw_sample(self):
        state = self.feed(.95, .05)
        self.assertTrue(state['gaze_smoothing']['holding_jump'])
        self.assertEqual(state['desktop_gaze'], [960, 540])
        self.assertEqual(state['gaze'], [.5, .5])
        self.assertTrue(np.allclose(state['raw_gaze'], [.95, .05]))
        self.assertEqual(self.c.samples[-1][1], [.95, .05])
        self.assertEqual(self.c.latest['result']['gaze_direction'], [.95, .05, 1])
        for _ in range(30):
            self.assertEqual(self.c.state()['desktop_gaze'], [960, 540])
        state = self.feed(.5, .5)
        self.assertFalse(state['gaze_smoothing']['holding_jump'])
        self.assertEqual(state['desktop_gaze'], [960, 540])

    def test_spike_or_lag_cannot_publish_a_click_at_raw_destination(self):
        self.c.blink_click_enabled = True
        self.feed(.95, .05)
        self.c.click_event = {'id': 1, 'point': [1824, 54], 'time': self.now}
        self.assertIsNone(self.c.state()['click_event'])
        self.feed(.95, .05)
        self.feed(.95, .05)
        self.c.click_event = {'id': 2, 'point': [1824, 54], 'time': self.now}
        self.assertIsNone(self.c.state()['click_event'])

    def test_poll_frequency_does_not_change_filter_and_stale_output_disappears(self):
        for _ in range(12):
            state = self.feed(.8, .8)
            for _ in range(10):
                self.assertEqual(self.c.state()['desktop_gaze'], state['desktop_gaze'])
        self.assertLess(np.linalg.norm(np.asarray(state['desktop_gaze']) - [1536, 864]), 20)
        self.now += .6
        self.assertFalse(self.c.state()['display_valid'])
        self.c.reset()
        self.assertIsNone(self.c.screen_motion.sample(self.now))


if __name__ == '__main__':
    unittest.main()
