"""Desktop union geometry, independent of connected hardware."""
import unittest
from gaze_mapping import desktop_fence
from screen_gaze import ScreenGazeMotion


class DisplayArrangementTests(unittest.TestCase):
    def test_shared_seam_is_open_on_both_sides(self):
        screens = [[0, 0, 1000, 800], [1000, 0, 1200, 900]]
        for x in (990, 999, 1000, 1001, 1010):
            self.assertEqual(desktop_fence([x, 400], screens), [x, 400])
        self.assertEqual(desktop_fence([3000, 400], screens), [2192, 400])

    def test_negative_and_stacked_arrangements(self):
        screens = [[0, 0, 1000, 800], [-1200, -100, 1200, 900], [0, -900, 1000, 900]]
        self.assertEqual(desktop_fence([-500, 400], screens), [-500, 400])
        self.assertEqual(desktop_fence([500, -400], screens), [500, -400])
        self.assertEqual(desktop_fence([500, -1], screens), [500, -1])
        self.assertEqual(desktop_fence([-2000, 400], screens), [-1192, 400])

    def test_offset_seam_and_empty_corner_stay_on_screens(self):
        screens = [[0, 0, 1000, 800], [1000, 300, 1200, 900]]
        self.assertEqual(desktop_fence([999, 500], screens), [999, 500])
        self.assertEqual(desktop_fence([1001, 100], screens), [992, 100])
        self.assertEqual(desktop_fence([1600, 100], screens), [1600, 308])
        self.assertIsNone(desktop_fence([float('nan'), 0], screens))
        self.assertIsNone(desktop_fence(None, screens))
        self.assertIsNone(desktop_fence([0, 0], []))

    def test_mirrored_rectangles_do_not_create_an_extra_edge(self):
        self.assertEqual(desktop_fence([1200, 400], [[0, 0, 1000, 800]] * 2), [992, 400])

    def test_nearby_monitor_transition_eases_across_seam(self):
        motion = ScreenGazeMotion()
        motion.update([998, 400], [0, 0, 1000, 800], 0, 'same-map')
        for i in range(1, 5):
            motion.update([1010, 400], [1000, 0, 1200, 900], i/30, 'same-map')
        self.assertTrue(1000 < motion.sample(4/30)[0] < 1010)
        self.assertTrue(motion.accepted)
