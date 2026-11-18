import unittest
from preview_reference import PreviewReference


class PreviewReferenceTests(unittest.TestCase):
    def test_separate_eyes_frozen_target_and_current_samples(self):
        capture=PreviewReference(['right','left'])
        self.assertEqual(capture.eye,'left')
        capture.set_target('right',[.9,.9],0)
        self.assertIsNone(capture.target)
        for side in ('left','right'):
            start=0 if side=='left' else 10
            capture.set_target(side,[.2,.3],start)
            capture.set_target(side,[.8,.7],start+1)
            self.assertEqual(capture.target,[.2,.3])
            self.assertFalse(capture.observe({side:{'time':start+1}},start+1))
            for i in range(50):
                now=start+2+i*.08
                self.assertTrue(capture.observe({side:{'time':now,'eye':[.4,.5],'head':[0]*6}},now))
                self.assertFalse(capture.observe({side:{'time':now}},now))
            self.assertFalse(capture.ready(start+5.9))
            self.assertTrue(capture.ready(start+6))
            capture.advance()
        self.assertIsNone(capture.eye)
        self.assertEqual(set(capture.references),{'left','right'})
        self.assertIsNot(capture.references['left']['samples'],capture.references['right']['samples'])

    def test_no_progress_from_stale_samples_or_time_alone(self):
        capture=PreviewReference(['left']);capture.set_target('left',[.5,.5],0)
        self.assertFalse(capture.observe({'left':{'time':2}},10))
        self.assertFalse(capture.ready(20))
        self.assertEqual(capture.state(20)['progress'],0)
        with self.assertRaises(ValueError):
            PreviewReference(['left']).set_target('left',[float('nan'),0],0)
