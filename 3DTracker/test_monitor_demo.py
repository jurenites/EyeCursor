"""Desktop coordinate and tracking-loss checks without a camera."""
import time
import unittest
from unittest.mock import patch
import cv2
import numpy as np

from monitor_demo import Calibration, TARGETS, AUTO_TARGETS, render_diagnostic_frame
import Orlosky3DEyeTracker as tracker


def frame(x, y, confidence=0.9):
    return {"pupil_ellipse": [1], "gaze_direction": [x, y, 1], "confidence": confidence}


class EyeDiagnosticsTests(unittest.TestCase):
    def test_raw_diagnostic_frame_keeps_unannotated_pixels_and_owns_copy(self):
        image = np.full((480, 640, 3), 100, dtype=np.uint8)
        calibration = Calibration("test eye camera")
        calibration.set_diagnostic_frame(image, None)
        self.assertTrue(np.all(calibration.diagnostic_raw_frame == 100))
        image[:] = 0
        self.assertTrue(np.all(calibration.diagnostic_raw_frame == 100))
        preview = cv2.imdecode(np.frombuffer(calibration.diagnostic_jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertTrue(np.all(preview[:59] == 100), "Preview must preserve the image above the pupil without a text strip")

    def tearDown(self):
        tracker.eye_region = None
        tracker.reset_tracking_state()

    def test_eye_region_excludes_dark_camera_corner(self):
        image = np.full((480, 640, 3), 190, dtype=np.uint8)
        cv2.rectangle(image, (20, 20), (180, 150), (0, 0, 0), -1)
        cv2.circle(image, (320, 230), 32, (18, 18, 18), -1)
        calibration = Calibration("test eye camera")
        self.assertLess(tracker.get_darkest_area(image)[0], 200)
        calibration.set_eye_region([0.38, 0.3, 0.64, 0.7])
        pupil_seed = tracker.get_darkest_area(image)
        self.assertTrue(280 <= pupil_seed[0] <= 360)
        self.assertTrue(190 <= pupil_seed[1] <= 270)

    def test_vectorized_dark_search_matches_original_sampling(self):
        image = np.random.default_rng(7).integers(0, 256, (480,640,3), dtype=np.uint8)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        expected = min(((sum(int(gray[y+dy,x+dx]) for dy in range(0,20,5)
                             for dx in range(0,20,5)), (x+10,y+10))
                        for y in range(20,461,10) for x in range(20,621,10)), key=lambda item:item[0])[1]
        self.assertEqual(tracker.get_darkest_area(image), expected)

    def test_iris_search_hint_excludes_remote_dark_patch(self):
        image = np.full((480, 640, 3), 190, dtype=np.uint8)
        cv2.rectangle(image, (20, 20), (180, 150), (0, 0, 0), -1)
        cv2.circle(image, (320, 230), 32, (18, 18, 18), -1)
        pupil_seed = tracker.get_darkest_area(image, [.35, .25, .7, .75])
        self.assertTrue(280 <= pupil_seed[0] <= 360)
        self.assertTrue(190 <= pupil_seed[1] <= 270)

    def test_diagnostic_marks_detection_and_model_direction(self):
        image = np.full((480, 640, 3), 100, dtype=np.uint8)
        result = {"pupil_ellipse": {"center": [340, 240], "axes": [30, 25],
                                    "angle_degrees": 15},
                  "eye_center": [320, 240], "gaze_direction": [0.2, 0.1, 0.97],
                  "confidence": 0.9, "seed_point": [338, 240], "eye_model_estimated": True}
        unready = render_diagnostic_frame(image, result)
        self.assertEqual(int(unready[240, 370, 1]), 100, "Unready sphere must not draw a gaze ray")
        rendered = render_diagnostic_frame(image, result, eye_model_ready=True)
        self.assertEqual(rendered.shape, image.shape)
        self.assertTrue(np.array_equal(rendered[:59], image[:59]), "Detection overlays must not add a text banner")
        self.assertGreater(int(rendered[240, 355, 1]), 200)
        with patch('monitor_demo.cv2.arrowedLine', wraps=cv2.arrowedLine) as arrow:
            for offset in (3, 20, 100):
                result['pupil_ellipse']['center'] = [320+offset,240]
                render_diagnostic_frame(image, result, eye_model_ready=True)
                self.assertEqual(arrow.call_args.args[1], (320,240))
                self.assertEqual(arrow.call_args.args[2], (320+min(2*offset,140),240))


class DesktopGazeTests(unittest.TestCase):
    def calibrate(self, viewport):
        calibration = Calibration("test eye camera", desktop_cursor=True)
        for name, (x, y) in TARGETS.items():
            for _ in range(8):
                calibration.add_frame(frame(x, y))
            calibration.capture(name, viewport)
        calibration.add_frame(frame(0.5, 0.5))
        return calibration

    def test_offset_monitor_and_toolbar_mapping(self):
        calibration = self.calibrate([-1920, -1022, 1920, 1022])
        point = calibration.state()["desktop_gaze"]
        self.assertAlmostEqual(point[0], -960, places=3)
        self.assertAlmostEqual(point[1], -511, places=3)

    def test_no_cursor_before_calibration_or_after_reset(self):
        calibration = Calibration("test eye camera", desktop_cursor=True)
        calibration.add_frame(frame(0.5, 0.5))
        self.assertIsNone(calibration.state()["desktop_gaze"])
        calibration = self.calibrate([0, 58, 1920, 1022])
        calibration.reset()
        self.assertIsNone(calibration.state()["desktop_gaze"])
        self.assertIsNone(calibration.viewport)

    def test_invalid_stale_and_off_area_gaze_hidden(self):
        calibration = self.calibrate([0, 58, 1920, 1022])
        calibration.add_frame(frame(0.5, 0.5, confidence=0.1))
        self.assertTrue(calibration.state()["display_bridged"])
        calibration.last_accepted["time"] = time.monotonic() - .26
        self.assertIsNone(calibration.state()["desktop_gaze"])
        calibration.add_frame(frame(0.5, 0.5))
        calibration.latest["time"] = time.monotonic() - 1
        self.assertIsNone(calibration.state()["desktop_gaze"])
        calibration.add_frame(frame(1.2, 0.5))
        self.assertIsNone(calibration.state()["desktop_gaze"])

    def test_bridging_never_accepts_rejected_samples_or_clicks(self):
        calibration = self.calibrate([0, 0, 1920, 1080])
        before = len(calibration.samples)
        calibration.blink_click_enabled = True
        calibration.add_frame(frame(.8, .8, confidence=.1))
        calibration.click_event = {"id": 1, "point": [960, 540], "time": time.monotonic()}
        state = calibration.state()
        self.assertTrue(state['display_valid'])
        self.assertTrue(state['display_bridged'])
        self.assertFalse(state['valid'])
        self.assertIsNone(state['click_event'])
        self.assertEqual(len(calibration.samples), before)
        self.assertTrue(np.allclose(state['desktop_gaze'], [960, 540]))
        calibration.add_frame(frame(.6, .6))
        self.assertFalse(calibration.state()['display_bridged'])
        self.assertTrue(np.allclose(calibration.state()['raw_desktop_gaze'], [1152, 648]))
        self.assertTrue(np.allclose(calibration.state()['desktop_gaze'], [960, 540]),
                        'One new point cannot pull the cursor away from the fixation')
        calibration.interrupt_stream()
        self.assertFalse(calibration.state()['display_valid'])

    def test_hysteresis_changes_display_only_not_calibration_acceptance(self):
        calibration = self.calibrate([0, 0, 1920, 1080])
        with patch('monitor_demo.time.monotonic', return_value=100):
            calibration.add_frame(frame(.5, .5, .6))
        before = len(calibration.samples)
        with patch('monitor_demo.time.monotonic', return_value=100.1):
            calibration.add_frame(frame(.6, .6, .47))
            state = calibration.state()
        self.assertFalse(state['valid'])
        self.assertTrue(state['display_valid'])
        self.assertTrue(np.allclose(state['raw_desktop_gaze'], [1152, 648]))
        self.assertTrue(np.allclose(state['desktop_gaze'], [960, 540]))
        self.assertEqual(len(calibration.samples), before)

    def test_threshold_validation_and_consistency(self):
        calibration = Calibration('test eye camera')
        for bad in (None, True, '0.4', .19, .96, float('nan')):
            with self.assertRaises(ValueError):
                calibration.set_detection_threshold(bad)
        calibration.set_detection_threshold(.4)
        self.assertTrue(calibration.usable(frame(.5, .5, .4)))
        self.assertFalse(calibration.usable(frame(.5, .5, .39)))
        calibration.start_eye_model()
        self.assertEqual(calibration.eye_model.threshold, .4)
        calibration.reset_eye_model()
        self.assertEqual(calibration.eye_model.threshold, .4)
        self.assertEqual(calibration.state()['detection_threshold'], .4)

    def test_geometry_change_requires_recalibration(self):
        calibration = self.calibrate([0, 58, 1920, 1022])
        with self.assertRaisesRegex(ValueError, "area changed"):
            calibration.capture("center", [1920, 58, 1920, 1022])

    def test_invalid_geometry_rejected(self):
        calibration = Calibration("test eye camera", desktop_cursor=True)
        for viewport in (None, [], [0, 0, 0, 1080], [0, float("nan"), 1920, 1080]):
            with self.subTest(viewport=viewport), self.assertRaises(ValueError):
                calibration.capture("top_left", viewport)

    def test_page_only_mode_needs_no_desktop_geometry(self):
        calibration = Calibration("test eye camera")
        for name, (x, y) in TARGETS.items():
            for _ in range(8):
                calibration.add_frame(frame(x, y))
            calibration.capture(name)
        self.assertTrue(calibration.state()["calibrated"])
        self.assertIsNone(calibration.state()["desktop_gaze"])


class AutomaticCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        clock = patch("monitor_demo.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.calibration = Calibration("synthetic eye camera")
        # These tests isolate monitor mapping after the eye-model stage.
        self.calibration.eye_model.phase = "ready"
        self.calibration.start_native([1920, 0, 1920, 1080])

    def feed(self, x, y, count=1, confidence=0.9):
        for _ in range(count):
            self.now += 1 / 30
            self.calibration.add_frame(frame(x, y, confidence))

    def complete_point(self, x, y):
        step = self.calibration.native["step"]
        for _ in range(90):
            self.feed(x, y)
            if self.calibration.native["step"] != step or self.calibration.native["phase"] != "collecting":
                return
        self.fail("Steady gaze did not advance calibration")

    def test_target_travel_time_never_contributes_samples(self):
        self.feed(.5, .5, count=15)
        self.assertEqual(self.calibration.native['progress'], 0)
        self.assertEqual(len(self.calibration.samples), 0)
        self.assertEqual(len(self.calibration.hold_frames), 0)

    def test_full_sequence_and_center_check(self):
        for name in AUTO_TARGETS:
            self.assertFalse(self.calibration.state()["calibrated"])
            self.assertIsNone(self.calibration.state()["desktop_gaze"])
            self.complete_point(*TARGETS.get(name, (0.5, 0.5)))
        self.feed(.5, .5)
        state = self.calibration.state()
        self.assertTrue(state["desktop_cursor"])
        self.assertTrue(state["calibrated"])
        self.assertEqual(state["calibration"]["phase"], "complete")
        self.assertEqual(state["center_error"], [0, 0])
        self.assertAlmostEqual(state["raw_desktop_gaze"][0], 2880, places=3)
        self.feed(.5, .5, count=30)
        self.assertAlmostEqual(self.calibration.state()["desktop_gaze"][0], 2880, delta=.1)

    def test_full_second_and_blink_do_not_capture_early(self):
        self.feed(.5, .5, count=27)
        self.assertIsNone(self.calibration.center_sample)
        self.feed(.5, .5, count=7, confidence=0)
        self.feed(.5, .5, count=20)
        self.assertIsNone(self.calibration.center_sample)
        self.complete_point(.5, .5)
        self.assertEqual(self.calibration.native["step"], 1)
        self.assertEqual(self.calibration.center_sample, [.5, .5])

    def test_brief_miss_pauses_progress_without_counting_bad_coordinates(self):
        self.feed(.5, .5, count=20)
        before = self.calibration.native["progress"]
        message = self.calibration.native["message"]
        self.feed(.9, .1, confidence=.4)
        self.assertAlmostEqual(self.calibration.native["progress"], before)
        self.assertEqual(self.calibration.native["message"], message)
        self.assertIsNone(self.calibration.center_sample)
        self.complete_point(.5, .5)
        self.assertEqual(self.calibration.center_sample, [.5, .5])

    def test_occasional_misses_allow_all_five_points(self):
        for name in AUTO_TARGETS:
            point = TARGETS.get(name, (.5, .5))
            step = self.calibration.native["step"]
            for index in range(90):
                self.feed(*point, confidence=.4 if index % 20 == 10 else .9)
                if self.calibration.native["step"] != step or self.calibration.native["phase"] != "collecting":
                    break
            else:
                self.fail("Occasional detection misses blocked calibration")
        self.assertTrue(self.calibration.state()["calibrated"])
        self.assertEqual(self.calibration.center_error, [0, 0])

    def test_camera_gap_restarts_hold(self):
        self.feed(.5, .5, count=25)
        self.now += .6
        self.assertFalse(self.calibration.state()["camera_connected"])
        self.feed(.5, .5)
        self.assertEqual(self.calibration.native["progress"], 0)
        self.feed(.5, .5, count=15)
        self.assertIsNone(self.calibration.center_sample)

    def test_gaze_shift_after_brief_miss_restarts_hold(self):
        self.feed(.5, .5, count=25)
        self.feed(.5, .5, confidence=0)
        self.feed(.8, .8)
        self.assertEqual(self.calibration.native["progress"], 0)
        self.assertIsNone(self.calibration.center_sample)

    def test_connected_camera_with_intermittent_detection_waits_for_steady_gaze(self):
        for index in range(90):
            self.feed(.5, .5, confidence=.9 if index % 3 == 0 else .4)
            self.assertTrue(self.calibration.state()["camera_connected"])
        self.assertEqual(self.calibration.native["step"], 0)
        self.assertIsNone(self.calibration.center_sample)
        self.complete_point(.5, .5)
        self.assertEqual(self.calibration.native["step"], 1)

    def test_unstable_gaze_does_not_advance(self):
        for index in range(120):
            self.feed(.08 + (index % 2) * .15, .08)
        self.assertEqual(self.calibration.corners, {})

    def test_stationary_pupil_cannot_follow_new_target(self):
        self.complete_point(.5, .5)
        self.feed(.5, .5, count=120)
        self.assertEqual(self.calibration.native["step"], 1)
        self.assertEqual(self.calibration.corners, {})
        self.complete_point(.08, .08)
        self.assertEqual(list(self.calibration.corners), ["top_left"])

    def test_crossed_corners_require_retry(self):
        self.complete_point(.5, .5)
        for point in ((.08, .08), (.08, .92), (.92, .08), (.92, .92)):
            self.complete_point(*point)
        self.assertEqual(self.calibration.native["phase"], "retry")
        self.assertFalse(self.calibration.state()["calibrated"])

    def test_bad_initial_center_never_exposes_calibrated_gaze(self):
        self.complete_point(.9, .9)
        for x, y in TARGETS.values():
            self.complete_point(x, y)
        self.assertEqual(self.calibration.native["phase"], "retry")
        self.assertIsNone(self.calibration.state()["desktop_gaze"])

    def test_cancel_clears_pending_sequence(self):
        self.complete_point(.08, .08)
        self.calibration.reset()
        self.feed(.92, .08, count=90)
        self.assertIsNone(self.calibration.native)
        self.assertEqual(self.calibration.corners, {})

    def test_sample_video_cannot_start(self):
        with self.assertRaisesRegex(ValueError, "Sample video"):
            Calibration("video demo").start_native([0, 0, 1920, 1080])

    def test_blink_click_is_opt_in_and_event_expires(self):
        for name in AUTO_TARGETS:
            self.complete_point(*TARGETS.get(name, (.5, .5)))
        self.assertFalse(self.calibration.state()["blink_click_enabled"])
        self.calibration.blink_click_enabled = True
        self.feed(.5, .5, count=35)
        for _ in range(2):
            for _ in range(5):
                self.now += 1/30
                self.calibration.add_frame(None)
            self.feed(.5, .5, count=5)
        self.feed(.5, .5, count=5)
        event = self.calibration.state()["click_event"]
        self.assertIsNotNone(event)
        self.assertAlmostEqual(event["point"][0], 2880, places=3)
        self.feed(.5, .5, count=15)
        self.assertIsNone(self.calibration.state()["click_event"])
        self.calibration.reset()
        self.assertIsNone(self.calibration.click_event)


if __name__ == "__main__":
    unittest.main()
