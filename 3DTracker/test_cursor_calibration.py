import unittest
import numpy as np
from cursor_calibration import CursorCalibration, CursorMap

TARGETS=np.array([[.1,.1],[.9,.1],[.9,.9],[.1,.9],[.5,.5],[.5,.15],[.8,.5]])

class CursorCalibrationTests(unittest.TestCase):
    def test_fit_recovers_unseen_positions(self):
        model=CursorMap(TARGETS*[.18,.14]+[.38,.35],TARGETS)
        for point in ([.7,.3],[.2,.65]):
            self.assertTrue(np.allclose(model.project(np.array(point)*[.18,.14]+[.38,.35]),point))
        self.assertIsNone(model.project([2,2]))

    def test_inconsistent_or_narrow_positions_rejected(self):
        for targets,eyes in [(TARGETS,TARGETS[::-1]**2),
                             (TARGETS*.2,TARGETS),
                             (np.column_stack((np.linspace(.1,.9,7),)*2),TARGETS)]:
            with self.assertRaises(ValueError):CursorMap(eyes,targets)

    def test_only_explicit_mode_collects_stable_distinct_positions(self):
        flow=CursorCalibration();now=0.
        for _ in range(20):
            now+=.1;flow.observe([.1,.1],[.4,.4],now,now)
        self.assertEqual(flow.points,[])
        flow.active=True
        for target in TARGETS:
            for _ in range(15):
                now+=.1;flow.observe(target,target*[.18,.14]+[.38,.35],now,now)
        self.assertEqual(len(flow.points),len(TARGETS))
        self.assertIsNotNone(flow.candidate)
        count=len(flow.points)
        for _ in range(20):
            now+=.1;flow.observe(TARGETS[-1],TARGETS[-1]*[.18,.14]+[.38,.35],now,now)
        self.assertEqual(len(flow.points),count)

    def test_duplicate_frames_cannot_fill_a_target(self):
        flow=CursorCalibration();flow.active=True
        for i in range(40):flow.observe([.1,.1],[.4,.4],1.,i*.1)
        self.assertEqual(flow.points,[])

    def test_saved_target_stays_complete_through_tracking_loss_until_pointer_leaves_radius(self):
        flow=CursorCalibration(viewport_size=(2000,1000));flow.active=True
        for i in range(20):flow.observe([.5,.5],[.4,.4],i*.1,i*.1)
        self.assertTrue(flow.state()['target_complete'])
        for eye,stamp in ((None,None),([float('nan'),.4],2.),([.4,.4],1.9)):
            flow.observe([.502,.502],eye,stamp,3.) # sqrt(4^2+2^2) < 5 px
            self.assertTrue(flow.state()['target_complete'])
            self.assertEqual(flow.progress,1.)
            self.assertEqual(flow.saved_count,1)
        flow.observe([.503,.5],None,None,4.) # 6 px from the saved point
        self.assertFalse(flow.state()['target_complete'])
        self.assertEqual(flow.progress,0.)
        for i in range(20):
            now=4.+i*.1;flow.observe([.503,.5],[.401,.4],now,now)
        self.assertTrue(flow.state()['target_complete'])
        self.assertEqual(flow.saved_count,2)
        flow.observe([2,.5],None,None,7.)
        self.assertFalse(flow.state()['target_complete'])

    def test_five_pixel_radius_is_independent_of_display_resolution(self):
        for size in ((1280,800),(3024,1964)):
            flow=CursorCalibration(viewport_size=size);flow.active=True
            for i in range(20):flow.observe([.5,.5],[.4,.4],i*.1,i*.1)
            flow.observe([.5,.5+4.9/size[1]],None,None,3.)
            self.assertTrue(flow.target_complete)
            flow.observe([.5,.5+5.1/size[1]],None,None,4.)
            self.assertFalse(flow.target_complete)

    def test_missing_eye_never_becomes_a_cursor_sample(self):
        flow=CursorCalibration();flow.active=True
        for i in range(40):flow.observe([.1,.1],None,None,i*.1)
        self.assertEqual(flow.points,[])

    def test_existing_fit_updates_from_one_fixation_without_faking_mouse_position(self):
        base=CursorMap(TARGETS*[.18,.14]+[.38,.35],TARGETS)
        flow=CursorCalibration(base);flow.active=True
        target=np.array([.5,.5]);eye=(target+[.08,-.04])*[.18,.14]+[.38,.35]
        for i in range(20):flow.observe(target,eye,i*.1,i*.1)
        self.assertEqual(len(flow.points),1)
        self.assertTrue(flow.state()['live_preview'])
        self.assertTrue(np.allclose(flow.candidate.project(eye),target))
        other=np.array([.7,.3]);other_eye=(other+[.08,-.04])*[.18,.14]+[.38,.35]
        self.assertTrue(np.allclose(flow.candidate.project(other_eye),other))
        self.assertFalse(np.allclose(flow.candidate.project(other_eye),target))
        self.assertTrue(np.allclose(base.project(eye),target+[.08,-.04]),'Saved fit stays unchanged until finish')

    def test_moving_cursor_or_missing_frames_do_not_train_an_offset(self):
        base=CursorMap(TARGETS*[.18,.14]+[.38,.35],TARGETS)
        flow=CursorCalibration(base);flow.active=True
        for i in range(20):flow.observe([.3+.02*i,.5],[.5,.5],i*.1,i*.1)
        self.assertIsNone(flow.candidate)
        for i in range(20,40):
            flow.observe([.5,.5],[.5,.5] if i%6==0 else None,i*.1,i*.1)
        self.assertIsNone(flow.candidate)

class MovingCursorTargetTests(unittest.TestCase):
    def test_stationary_pointer_learns_continuous_nodding_and_stops_on_toggle(self):
        base=CursorMap(TARGETS*[.18,.14]+[.38,.35],TARGETS)
        flow=CursorCalibration(base);flow.active=True
        ref=np.array([0.,0.,0.,.5,.4,-1.5]);target=np.array([.5,.5])
        for t in np.arange(0,14,.1):
            head=ref.copy();head[1]=.22*np.sin(t*1.2)
            eye=(target+[0,head[1]*1.1])*[.18,.14]+[.38,.35]
            flow.observe(target,eye,t,t,pose=head)
        self.assertGreater(flow.saved_count,8)
        self.assertGreater(flow.candidate.head_model.rank,0)
        for pitch in (-.13,.09):
            head=ref.copy();head[1]=pitch
            unseen=np.array([.7,.3]);eye=(unseen+[0,pitch*1.1])*[.18,.14]+[.38,.35]
            np.testing.assert_allclose(flow.candidate.project_pose(eye,head,False),unseen,atol=.025)
        count=flow.saved_count;flow.active=False
        for t in np.arange(15,18,1/30):flow.observe([.2,.8],[.6,.5],t,t,pose=ref)
        self.assertEqual(flow.saved_count,count)
        resumed=CursorCalibration(flow.candidate)
        self.assertFalse(resumed.active)
        self.assertEqual(len(resumed.pose_points),len(flow.pose_points))

    def test_short_motion_blocks_reject_abrupt_pupil_failures(self):
        from cursor_calibration import motion_block_is_coherent,PoseAnchorMap
        times=np.arange(10)/30
        eyes=np.c_[.5+times*.06,.4+times*.12]
        heads=np.zeros((10,6));heads[:,1]=times*.3
        self.assertTrue(motion_block_is_coherent(times,eyes,heads,PoseAnchorMap.pose_scale))
        eyes[5:]+=[.06,-.08]
        self.assertFalse(motion_block_is_coherent(times,eyes,heads,PoseAnchorMap.pose_scale))
