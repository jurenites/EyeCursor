"""Image-evidence and real-pipeline checks for the pupil inside an IR iris."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import Orlosky3DEyeTracker as tracker
from eye_geometry import detect_pupil_in_iris, detect_reflected_pupil


def eye(angle=20, center=(324, 238), scale=.4):
    gray = np.full((480, 640), 180, np.uint8)
    iris = {'ellipse': ((320, 240), (200, 160), angle), 'support': .95}
    pupil = (center, (200*scale, 160*scale), angle)
    cv2.ellipse(gray, iris['ellipse'], 80, -1)
    cv2.ellipse(gray, pupil, 30, -1)
    return gray, iris, pupil


def reflected_eye(angle=20):
    gray, iris, pupil = eye(angle)
    yy, xx = np.indices(gray.shape)
    theta = np.radians(angle)
    u = (xx-324)*np.cos(theta)+(yy-238)*np.sin(theta)
    mask = gray == 30
    # Unsaturated broad reflections become brighter than the surrounding iris.
    # Their outer boundary has reversed contrast; the central dark patch narrows.
    gray[mask] = (20+160*(u[mask]/40)**4).clip(0, 220).astype(np.uint8)
    cv2.circle(gray, (314, 229), 3, 255, -1)
    return cv2.GaussianBlur(gray, (5, 5), 1), iris, pupil


class IrisEdgeTests(unittest.TestCase):
    def test_reversed_contrast_arcs_recover_full_ellipse_without_forcing_circle(self):
        for angle in (0, 20, 65, 110, 165):
            with self.subTest(angle=angle):
                gray, iris, pupil = reflected_eye(angle)
                result = detect_reflected_pupil(gray, iris)
                self.assertIsNotNone(result)
                self.assertEqual(result['source'], 'reflection-edge')
                self.assertGreaterEqual(result['confidence'], .65)
                self.assertLess(np.linalg.norm(np.array(result['ellipse'][0])-pupil[0]), 1)
                self.assertLess(np.max(np.abs(np.sort(result['ellipse'][1])-np.sort(pupil[1]))), 3)
                self.assertLess(min(result['ellipse'][1])/max(result['ellipse'][1]), .85)
                self.assertEqual(result, detect_reflected_pupil(gray, iris))

    def test_reflection_fit_requires_dark_core_and_distributed_current_edges(self):
        gray, iris, pupil = reflected_eye()
        for kind in ('bright-core', 'saturated', 'blink', 'crescent'):
            with self.subTest(kind=kind):
                image = gray.copy()
                if kind == 'bright-core': cv2.ellipse(image, pupil, 160, -1)
                if kind == 'saturated': cv2.ellipse(image, pupil, 255, -1)
                if kind == 'blink': image[:] = 180
                if kind == 'crescent': image[:250] = 180
                self.assertIsNone(detect_reflected_pupil(image, iris))
        self.assertIsNone(detect_reflected_pupil(gray, {**iris, 'support': .5}))
    def test_circle_inside_ellipse_has_independent_center_and_matching_curvature(self):
        for angle in (0, 20, 65, 110, 165):
            for scale in (.22, .4, .65):
                with self.subTest(angle=angle, scale=scale):
                    gray, iris, pupil = eye(angle, scale=scale)
                    result = detect_pupil_in_iris(gray, iris)
                    self.assertIsNotNone(result)
                    self.assertLess(np.linalg.norm(np.array(result['ellipse'][0])-pupil[0]), 1)
                    self.assertLess(np.max(np.abs(np.array(result['ellipse'][1])-pupil[1])), 2)
                    self.assertAlmostEqual(result['ellipse'][1][1]/result['ellipse'][1][0], .8)
                    self.assertEqual(result['ellipse'][2], angle)
                    self.assertEqual(result, detect_pupil_in_iris(gray, iris))

    def test_darker_distractions_and_glints_do_not_select_a_black_patch(self):
        gray, iris, pupil = eye()
        cv2.rectangle(gray, (20, 20), (180, 150), 0, -1)
        cv2.rectangle(gray, (373, 225), (388, 252), 0, -1)  # Within iris, outside pupil.
        cv2.rectangle(gray, (316, 237), (335, 250), 0, -1)  # Darkest patch inside pupil.
        cv2.circle(gray, (314, 229), 5, 255, -1)
        result = detect_pupil_in_iris(gray, iris)
        self.assertIsNotNone(result)
        self.assertLess(np.linalg.norm(np.array(result['ellipse'][0])-pupil[0]), 1)
        self.assertLess(np.max(np.abs(np.array(result['ellipse'][1])-pupil[1])), 2)

    def test_reflection_gradient_and_blur_use_boundary_not_dark_core(self):
        gray, iris, pupil = eye()
        yy, xx = np.indices(gray.shape)
        mask = gray == 30
        gray[mask] = (20+40*((xx[mask]-324)/40)**2).clip(0, 75).astype(np.uint8)
        gray = cv2.GaussianBlur(gray, (9, 9), 1.8)
        result = detect_pupil_in_iris(gray, iris)
        self.assertIsNotNone(result)
        self.assertLess(np.linalg.norm(np.array(result['ellipse'][0])-pupil[0]), 1.5)
        self.assertLess(np.max(np.abs(np.array(result['ellipse'][1])-pupil[1])), 4)

    def test_no_pupil_eyelids_wrong_shape_and_wrong_location_are_rejected(self):
        for kind in ('iris-only', 'blank', 'eyelid', 'narrow', 'outside', 'rectangle', 'crescent'):
            with self.subTest(kind=kind):
                gray, iris, _ = eye()
                cv2.ellipse(gray, iris['ellipse'], 80, -1)
                if kind == 'blank': gray[:] = 80
                if kind == 'eyelid': cv2.line(gray, (240, 220), (400, 220), 10, 10)
                if kind == 'narrow': cv2.ellipse(gray, ((324, 238), (80, 30), 20), 20, -1)
                if kind == 'outside': cv2.circle(gray, (460, 240), 30, 0, -1)
                if kind == 'rectangle': cv2.rectangle(gray, (285, 215), (355, 265), 10, -1)
                if kind == 'crescent':
                    cv2.ellipse(gray, ((324, 238), (80, 64), 20), 20, -1)
                    gray[:250] = 180
                self.assertIsNone(detect_pupil_in_iris(gray, iris))

    def test_invalid_weak_and_swapped_iris(self):
        gray, iris, _ = eye()
        for guide in (None, {**iris, 'support': .4},
                      {'ellipse': ((320, 240), (0, 160), 20), 'support': .9}):
            self.assertIsNone(detect_pupil_in_iris(gray, guide))
        first = detect_pupil_in_iris(gray, iris)['ellipse']
        second = detect_pupil_in_iris(gray, {**iris, 'ellipse': ((320, 240), (160, 200), 110)})['ellipse']
        self.assertTrue(np.allclose(first[0], second[0], atol=.1))
        self.assertTrue(np.allclose(sorted(first[1]), sorted(second[1]), atol=.1))


class IrisEdgePipelineTests(unittest.TestCase):
    def setUp(self):
        tracker.reset_tracking_state()
        self.display = patch.object(tracker, 'DISPLAY_ENABLED', False)
        self.display.start()

    def tearDown(self):
        self.display.stop()
        tracker.reset_tracking_state()

    def process(self, gray):
        tracker.process_frame(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
        return tracker.get_last_tracking_result()

    def test_reflection_recovery_survives_repeated_frames_then_blink(self):
        gray, _, pupil = reflected_eye()
        for _ in range(12):
            result = self.process(gray)
            self.assertIsNotNone(result)
            self.assertEqual(result['pupil_shape_source'], 'reflection-edge')
            self.assertGreaterEqual(result['confidence'], .5)
            self.assertLess(np.linalg.norm(np.array(result['pupil_ellipse']['center'])-pupil[0]), 1.5)
        self.assertIsNone(self.process(np.full_like(gray, 180)))
        self.assertEqual(self.process(gray)['pupil_shape_source'], 'reflection-edge')

    def test_verified_iris_skips_dark_search_and_follows_pupil_motion(self):
        gray, _, _ = eye()
        self.assertEqual(self.process(gray)['pupil_shape_source'], 'iris-edge')
        gray, _, pupil = eye(center=(329, 243))
        cv2.rectangle(gray, (215, 195), (243, 255), 0, -1)
        with patch.object(tracker, 'get_darkest_area', side_effect=AssertionError('dark search used')):
            result = self.process(gray)
        self.assertEqual(result['pupil_shape_source'], 'iris-edge')
        self.assertIsNone(result['raw_pupil_ellipse'])
        self.assertEqual(result['raw_pupil_confidence'], 0)
        self.assertLess(np.linalg.norm(np.array(result['pupil_ellipse']['center'])-pupil[0]), 1)
        self.assertTrue(result['pupil_edge_points'])

    def test_visible_iris_without_pupil_cannot_fall_back_to_dark_blob(self):
        gray, iris, _ = eye()
        self.assertIsNotNone(self.process(gray))
        cv2.ellipse(gray, iris['ellipse'], 80, -1)
        with patch.object(tracker, 'get_darkest_area', side_effect=AssertionError('dark search used')):
            for _ in range(3):
                self.assertIsNone(self.process(gray))
            recovered, _, _ = eye()
            self.assertEqual(self.process(recovered)['pupil_shape_source'], 'iris-edge')

    def test_blink_clears_detection_and_reacquires_without_stale_outline(self):
        gray, _, _ = eye()
        self.assertIsNotNone(self.process(gray))
        self.assertIsNone(self.process(np.full_like(gray, 180)))
        self.assertIsNone(tracker._iris_search_pupil)
        self.assertEqual(self.process(gray)['pupil_shape_source'], 'iris-edge')
        tracker.reset_tracking_state()
        self.assertIsNone(tracker._iris_search_pupil)


if __name__ == '__main__':
    unittest.main()
