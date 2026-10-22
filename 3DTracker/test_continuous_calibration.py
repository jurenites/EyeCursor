"""Unscripted movement, robust fitting, and future observations decide updates."""
from concurrent.futures import Future
import unittest
from unittest.mock import patch
import numpy as np
from continuous_calibration import ContinuousTargetCalibration, pupil_shape_rejection
from geometric_gaze import GeometricGazeMap
from test_geometric_gaze import fixture, physical_eye, moving_head, ASPECT


class ImmediateExecutor:
    def submit(self, function, *args, **kwargs):
        result=Future()
        try:result.set_result(function(*args,**kwargs))
        except Exception as error:result.set_exception(error)
        return result
    def shutdown(self,**kwargs):pass


class ContinuousTests(unittest.TestCase):
    def make_run(self):
        base,fit,seeds=fixture()
        run=ContinuousTargetCalibration(base,fit,seeds,ASPECT,16/9,100,executor=ImmediateExecutor())
        self.addCleanup(run.close)
        return run

    def feed(self,run,start,end,away=False):
        for t in np.arange(start,end,.1):
            head=moving_head(t)
            target=[.85,.2] if away and run.phase=='validate' else [.5,.5]
            run.observe((physical_eye(target,head),head),100+t,100+t)

    def test_applies_only_after_future_check_and_continues_until_stopped(self):
        run=self.make_run();original=run.base_mapping
        self.feed(run,.1,9.2)
        self.assertEqual(run.phase,'validate')
        validation_start=run.validation_started
        frozen=run.candidate.coefficients.copy();training_stamps={s[0] for s in run.training_snapshot}
        self.assertIs(run.base_mapping,original)
        self.feed(run,9.2,13.5)
        self.assertTrue(run.applied,run.state(118.5))
        self.assertEqual(run.revision,1)
        self.assertEqual(run.progress(118.5),1)
        self.assertFalse(run.done)
        np.testing.assert_array_equal(run.result.coefficients,frozen)
        self.assertTrue(all(s[0] not in training_stamps for s in run.samples if s[0]>=validation_start))
        result=run.result;count=run.total_samples
        run.pause(118.5);self.feed(run,19,20)
        self.assertEqual(run.total_samples,count)
        self.assertIs(run.result,result)
        run.resume(120);run.executor=ImmediateExecutor()
        self.feed(run,20.1,35)
        self.assertGreater(run.total_samples,count)
        self.assertTrue(run.applied)
        self.assertFalse(run.done)

    def test_bad_check_and_indefinite_dropouts_retain_the_original_map(self):
        run=self.make_run();original=run.base_mapping
        self.feed(run,.1,35,away=True)
        self.assertGreater(run.check_failures,0)
        self.assertIs(run.base_mapping,original)
        self.assertFalse(run.applied)
        for now in np.arange(140,200,.1):run.observe(None,now,now)
        self.assertFalse(run.done)
        self.assertGreater(run.rejected,500)

    def test_fit_failure_is_reported_and_finish_does_not_claim_success(self):
        run=self.make_run();original=run.base_mapping
        with patch('continuous_calibration.fit_head_candidate',side_effect=ValueError('Head/eye measurements do not fit the geometric model')):
            self.feed(run,.1,20)
        report=run.state(120)
        self.assertGreater(report['fit_failures'],0)
        self.assertIn('geometric model',report['last_fit_error'])
        self.assertEqual(report['applied_updates'],0)
        self.assertEqual(run.progress(120),0)
        run.pause(120)
        self.assertIn('without a new head correction',run.message)
        self.assertIs(run.base_mapping,original)

    def test_robust_fit_keeps_real_motion_and_rejects_corrupted_time_blocks(self):
        base,fit,seeds=fixture();samples=[]
        for t in np.arange(0,12,.05):
            head=moving_head(t);eye=physical_eye([.5,.5],head)
            # Whole corrupted stretches plus isolated corrupted frames.
            if 2<=t<2.8 or 7.2<=t<8 or int(round(t/.05))%19==0:eye=eye+[.18,-.15]
            samples.append((t,eye,head,np.array([.5,.5])))
        model=GeometricGazeMap.fit(base,fit,seeds,samples,ASPECT,robust=True)
        self.assertGreater(model.fit_metrics['rejected_blocks'],0)
        for t in (1.,3.,6.,9.):
            for target in ([.5,.5],[.2,.8],[.8,.2]):
                np.testing.assert_allclose(model.project_raw(physical_eye(target,moving_head(t)),moving_head(t)),target,atol=.035)

    def test_shape_gate_only_rejects_gross_disagreement_with_a_supported_iris(self):
        row={'pupil_ellipse':{'axes':[30,80],'angle_degrees':0},
             'iris_ellipse':{'axes':[100,105],'angle_degrees':90},'iris_support':.9}
        self.assertIsNotNone(pupil_shape_rejection(row))
        row['iris_support']=.2
        self.assertIsNone(pupil_shape_rejection(row))
        row['iris_support']=.9;row['pupil_ellipse']['axes']=[70,80]
        self.assertIsNone(pupil_shape_rejection(row))
        row['pupil_ellipse']['axes']=[40,80];row['iris_ellipse']['axes']=[70,130]
        self.assertIsNotNone(pupil_shape_rejection(row))
        row['pupil_ellipse']['angle_degrees']=90
        self.assertIsNone(pupil_shape_rejection(row))

    def test_training_window_is_bounded_and_stale_data_cannot_start_a_fit(self):
        run=self.make_run();run.next_fit=10000
        self.feed(run,.1,230)
        self.assertLessEqual(len(run.samples),1201)
        self.assertGreater(run.total_samples,len(run.samples))
        run.next_fit=0;run.tick(400)
        self.assertEqual(run.phase,'collect')
