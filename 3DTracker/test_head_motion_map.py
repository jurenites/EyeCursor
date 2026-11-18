"""Coupled rotations/translations must not be reduced to independent axis squares."""
import unittest
import numpy as np
from head_motion_map import HeadMotionMap
from hybrid_onboarding import HeadCompensation
from quick_calibration import TARGETS,AnchorMap

class HeadInteractionTests(unittest.TestCase):
    def test_local_nonlinear_head_effect_keeps_response_to_unseen_eye_targets(self):
        from geometric_gaze import POSE_SCALE
        ref=np.array([0.,0.,0.,.5,.4,-1.2]);scale=np.array([-.18,.14]);offset=np.array([.58,.35])
        seeds=[(t*scale+offset,ref,t) for t in TARGETS]
        base=AnchorMap([s[0] for s in seeds]);fit=HeadCompensation()
        fit.fit_steady([seeds[0][0]]*10,[ref]*10)
        def pose(t):return ref+POSE_SCALE*np.array([np.sin(.7*t),np.cos(1.1*t),0,.3*np.sin(1.7*t),0,0])
        def shift(h):
            x=(h-ref)/POSE_SCALE
            return np.array([.025*np.sin(3*x[0])+.01*x[1],.02*np.sin(2*x[1])+.01*x[0]])
        center=np.array([.5,.5])
        samples=[(t,center*scale+offset+shift(pose(t)),pose(t),center) for t in np.arange(0,60,.1)]
        model=HeadMotionMap.fit(base,fit,seeds,samples)
        self.assertIsNotNone(model.kernel_centers)
        errors=[]
        for t in np.arange(61,70,.3):
            for target in (np.array([.2,.7]),np.array([.8,.3])):
                predicted=model.evaluate_raw(target*scale+offset+shift(pose(t)),pose(t))
                errors.append(np.linalg.norm(predicted-target))
        self.assertLess(np.percentile(errors,80),.06)

    def test_counterrotation_with_coupled_head_motion_preserves_unseen_targets(self):
        ref=np.array([0.,0.,0.,.5,.4,-1.2]);scale=np.array([.18,.14]);offset=np.array([.38,.35])
        seeds=[(t*scale+offset,ref,t) for t in TARGETS]
        base=AnchorMap([s[0] for s in seeds]);fit=HeadCompensation()
        fit.fit_steady([seeds[0][0]]*10,[ref]*10)
        def head(t):return ref+[.15*np.sin(t*.7),.14*np.cos(t*1.1),0,.025*np.sin(t*1.7),0,0]
        def eye(target,h):
            d=h-ref
            return target*scale+offset+[d[0]*d[1]*1.6,d[0]*d[3]*7]
        center=np.array([.5,.5])
        samples=[(t,eye(center,head(t)),head(t),center) for t in np.arange(0,45,.1)]
        model=HeadMotionMap.fit(base,fit,seeds,samples)
        self.assertEqual(model.degree,2)
        for t in (46.,47.,48.,49.):
            for target in (np.array([.7,.3]),np.array([.2,.8])):
                np.testing.assert_allclose(model.evaluate_raw(eye(target,head(t)),head(t)),target,atol=.005)
        # Historical model snapshots with square-only coefficients stay readable.
        model.quadratic_interactions=False
        self.assertEqual(model.design(ref).shape,(13,))
