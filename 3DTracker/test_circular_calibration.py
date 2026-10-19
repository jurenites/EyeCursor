import unittest
import numpy as np
from circular_calibration import CircularCalibration, circular_target, FIRST_PAIR_SECONDS, ENTRY, LAP

class CircularTests(unittest.TestCase):
    def make(self,lag=0.,drop=False,wrong=False):
        model=CircularCalibration([.47,.42],100.)
        rng=np.random.default_rng(10)
        for i,t in enumerate(np.arange(0,FIRST_PAIR_SECONDS+.34,1/30)):
            if drop and (i%4==0 or 3<t<3.3):continue
            target=np.array(circular_target(max(0,t-lag)))
            eye=target*[.18,.14]+[.38,.35]+rng.normal(0,.0005,2)
            if wrong:eye=rng.uniform(.3,.6,2)
            model.observe(eye,100+t,100+t+.02)
        return model

    def test_continuous_entry_reversal_and_unlimited_passes(self):
        self.assertTrue(np.allclose(circular_target(0),[.5,.5]))
        for t in (ENTRY,ENTRY+LAP/4,ENTRY+LAP/2,ENTRY+LAP,FIRST_PAIR_SECONDS,ENTRY+5*LAP):
            self.assertLess(np.linalg.norm(np.array(circular_target(t-.001))-circular_target(t+.001)),.001)
        self.assertFalse(np.allclose(circular_target(103),circular_target(FIRST_PAIR_SECONDS)))
        self.assertTrue(np.allclose(circular_target(ENTRY+5*LAP+4),circular_target(ENTRY+LAP+4)))

    def test_larger_rectangle_visits_all_corners_without_jumps(self):
        for i,point in enumerate(([.08,.08],[.92,.08],[.92,.92],[.08,.92])):
            self.assertTrue(np.allclose(circular_target(ENTRY+i*LAP/4),point))
        self.assertTrue(np.allclose(circular_target(ENTRY+LAP+LAP/4),[.08,.92]))
        self.assertTrue(np.allclose(circular_target(ENTRY+LAP/8),[.5,.08]))

    def test_full_coverage_is_not_claimed_as_a_successful_fit(self):
        model=self.make(wrong=True)
        self.assertEqual(model.progress,1.)
        with self.assertRaises(ValueError):model.fit()
        self.assertTrue(model.fit_attempted)
        self.assertIn('disagree',model.fit_status)
        self.assertIsNone(model.error)

    def test_delayed_pursuit_with_dropout_recovers_unseen_targets(self):
        model=self.make(lag=.15,drop=True);mapping=model.fit()
        self.assertAlmostEqual(model.lag,.15,delta=.051)
        for target in ([.7,.3],[.25,.65],[.5,.5]):
            eye=np.array(target)*[.18,.14]+[.38,.35]
            self.assertTrue(np.allclose(mapping.project(eye),target,atol=.04))
        self.assertLess(model.error,.05)

    def test_stationary_random_and_one_sided_gaze_cannot_pass(self):
        with self.assertRaises(ValueError):self.make(wrong=True).fit()
        for fixed in (True,False):
            model=CircularCalibration([.47,.42],100.)
            for t in np.arange(0,FIRST_PAIR_SECONDS,1/30):
                if not fixed and circular_target(t)[0]<.5:continue
                eye=[.47,.42] if fixed else np.array(circular_target(t))*[.18,.14]+[.38,.35]
                model.observe(eye,100+t,100+t)
            with self.assertRaises(ValueError):model.fit()

    def test_sparse_sections_accumulate_across_many_laps(self):
        model=CircularCalibration([.47,.42],100.)
        for lap in range(8):
            for t in np.arange(ENTRY+lap*LAP+.01,ENTRY+(lap+1)*LAP,1/30):
                direction,sector=model.sector(t)
                # Only two sectors in each lap have a usable pupil.
                if sector//2 != lap//2:continue
                eye=np.array(circular_target(t))*[.18,.14]+[.38,.35]
                model.observe(eye,100+t,100+t)
            if lap<2:
                with self.assertRaises(ValueError):model.fit()
        mapping=model.fit()
        self.assertEqual(model.coverage,16)
        self.assertTrue(np.allclose(mapping.project([.47,.42]),[.5,.5],atol=.04))
        self.assertLessEqual(len(model.samples),16*96)
        before=len(model.samples)
        for i in range(10000):
            t=ENTRY+8*LAP+i/30
            model.observe([.47,.42],100+t,100+t)
        self.assertLessEqual(len(model.samples),16*96)
        self.assertGreaterEqual(len(model.samples),before)

    def test_duplicate_and_stale_capture_frames_do_not_add_coverage(self):
        model=CircularCalibration([.47,.42],100.)
        for _ in range(20):model.observe([.5,.5],100+ENTRY+.1,100+ENTRY+.11)
        self.assertEqual(len(model.samples),1)
        model.observe([.5,.5],102.,103.)
        self.assertEqual(len(model.samples),1)

if __name__=='__main__':unittest.main()
