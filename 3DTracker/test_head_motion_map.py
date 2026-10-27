"""Coupled rotations/translations must not be reduced to independent axis squares."""
import unittest
import numpy as np
from head_motion_map import HeadMotionMap
from hybrid_onboarding import HeadCompensation
from quick_calibration import TARGETS,AnchorMap

class HeadInteractionTests(unittest.TestCase):
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
