import unittest
from eye_gestures import FixationDoubleBlink


class BlinkTests(unittest.TestCase):
    def setUp(self):
        self.gesture = FixationDoubleBlink()
        self.now = 0
        self.clicks = []

    def feed(self, count, point=(500, 300), missing=False):
        for _ in range(count):
            self.now += 1/30
            result = self.gesture.update(self.now, point, missing)
            if result is not None:
                self.clicks.append(result)

    def blink(self):
        self.feed(5, None, True)
        self.feed(5)

    def test_double_blink_after_fixation_emits_one_click(self):
        self.feed(35)
        self.blink()
        self.blink()
        self.feed(15)
        self.assertEqual(self.clicks, [[500, 300]])

    def test_no_fixation_no_click(self):
        self.blink()
        self.blink()
        self.feed(10)
        self.assertEqual(self.clicks, [])

    def test_single_blink_and_late_second_do_not_click(self):
        self.feed(35)
        self.blink()
        self.feed(25)
        self.blink()
        self.feed(10)
        self.assertEqual(self.clicks, [])

    def test_movement_between_blinks_aborts(self):
        self.feed(35)
        self.blink()
        self.feed(2, (600, 300))
        self.blink()
        self.feed(10)
        self.assertEqual(self.clicks, [])

    def test_camera_stall_and_long_loss_do_not_click(self):
        self.feed(35)
        self.now += .5
        self.blink()
        self.blink()
        self.feed(10)
        self.assertEqual(self.clicks, [])
        self.feed(35)
        self.feed(20, None, True)
        self.feed(5)
        self.blink()
        self.feed(10)
        self.assertEqual(self.clicks, [])

    def test_low_confidence_visible_pupil_is_not_a_blink(self):
        self.feed(35)
        self.feed(5, None, False)
        self.feed(5)
        self.blink()
        self.feed(10)
        self.assertEqual(self.clicks, [])

    def test_new_movement_after_second_blink_aborts(self):
        self.feed(35)
        self.blink()
        self.blink()
        self.feed(1, (600, 300))
        self.feed(10)
        self.assertEqual(self.clicks, [])


if __name__ == '__main__':
    unittest.main()
