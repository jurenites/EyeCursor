import unittest
import numpy as np
from accuracy_check import AccuracyCheck, CHECK_TARGETS
from quick_calibration import QuickCalibration


class AccuracyTests(unittest.TestCase):
    def run_check(self,offset=(0,0)):
        check=AccuracyCheck([0,0,1000,500],100.)
        now=100.
        while not check.done and now<140:
            now+=1/30
            target=np.array(check.target)
            check.observe(target*[.18,.14]+[.38,.35],target+offset,now,now)
            check.tick(now)
        return check

    def test_unseen_targets_measure_bias_in_screen_points_without_refitting(self):
        check=self.run_check((.1,0))
        report=check.state(140.)
        self.assertEqual(report['status'],'complete')
        self.assertAlmostEqual(report['mean_error_points'],100)
        self.assertAlmostEqual(report['worst_error_points'],100)
        self.assertTrue(all(r['precision_points']<1e-8 for r in report['rows']))
        self.assertEqual(len(check.rows),5)
        self.assertFalse(any(np.allclose(t,[.5,.5]) for t in CHECK_TARGETS))

    def test_missing_prediction_does_not_block_capturing_or_advancing_targets(self):
        check=AccuracyCheck([0,0,1000,500],100.)
        now=100.
        while not check.done and now<110:
            now+=1/30
            check.observe(np.asarray(check.target)*.1,None,now,now)
            check.tick(now)
        self.assertTrue(check.done)
        self.assertEqual(check.status,'incomplete')
        self.assertTrue(all(r['captured_samples']>=6 and r['samples']==0 for r in check.rows))
        self.assertIsNone(check.state(now)['mean_error_points'])

    def test_off_screen_predictions_are_not_clipped(self):
        check=self.run_check((1,0))
        self.assertAlmostEqual(check.state(140.)['mean_error_points'],1000)
        self.assertGreater(check.rows[0]['measured'][0],1)

    def test_missing_capture_is_reported_not_counted_as_zero_error(self):
        check=AccuracyCheck([0,0,1000,500],100.)
        for i in range(5):check.tick(108.1+i*8.1)
        report=check.state(150.)
        self.assertEqual(report['status'],'incomplete')
        self.assertIsNone(report['mean_error_points'])
        self.assertTrue(all(r['measured'] is None for r in report['rows']))

    def test_blink_duplicate_and_delayed_frames_cannot_fill_a_fixation(self):
        check=AccuracyCheck([0,0,1000,500],100.)
        for i in range(8):check.observe([.4,.4],[.25,.25],101.,101.)
        self.assertEqual(len(check.block),1)
        check.reject('blink')
        self.assertFalse(check.block)
        check.observe([.4,.4],[.25,.25],101.1,102.)
        self.assertFalse(check.block)
        check.tick(102.)
        self.assertEqual(check.index,0)

    def test_jitter_and_slow_drift_cannot_complete_target_capture(self):
        for motion in ('jitter','drift'):
            flow=QuickCalibration([.47,.42],100.)
            for i in range(180):
                now=101+i/30
                x=.4+(.025*(i%2) if motion=='jitter' else .001*i)
                flow.observe([x,.4],now,now)
            self.assertEqual(flow.index,0,motion)
            self.assertFalse(flow.ready(flow.blocks[0]),motion)

    def test_blink_resets_only_current_corner(self):
        flow=QuickCalibration([.47,.42],100.)
        flow.blocks[0]=[(100.,np.array([.4,.4]))]
        flow.index=1;flow.blocks[1]=[(102.,np.array([.5,.4]))]
        flow.reject('blink')
        self.assertEqual(len(flow.blocks[0]),1)
        self.assertEqual(len(flow.blocks[1]),0)
