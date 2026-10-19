import unittest
import numpy as np
from quick_calibration import QuickCalibration, AnchorMap, target_at, TARGETS, DURATION, STEP, TRAVEL
from cursor_calibration import CursorCalibration, PoseAnchorMap

class QuickTests(unittest.TestCase):
    def collect(self,drop=False):
        flow=QuickCalibration([.47,.42],100.)
        for i,t in enumerate(np.arange(0,DURATION+.1,1/30)):
            if drop and i%3==0:continue
            target=np.array(target_at(t-.1))
            flow.observe(target*[.18,.14]+[.38,.35],100+t,100+t)
        return flow

    def test_short_pass_survives_dropout_and_maps_unseen_gaze(self):
        flow=self.collect(drop=True);mapping=flow.fit()
        self.assertLess(DURATION,8)
        for target in ([.5,.5],[.23,.8],[.84,.22]):
            self.assertTrue(np.allclose(mapping.project(np.array(target)*[.18,.14]+[.38,.35]),target))
        self.assertIsNone(mapping.project([.9,.1]))

    def test_piecewise_mapping_accepts_consistent_non_affine_eye_geometry(self):
        eyes=np.array([[.47,.42],[.405,.352],[.59,.364],[.548,.503],[.398,.482]])
        mapping=AnchorMap(eyes)
        for eye,target in zip(eyes,TARGETS):self.assertTrue(np.allclose(mapping.project(eye),target))
        eye=.4*eyes[0]+.3*eyes[1]+.3*eyes[2]
        self.assertTrue(np.allclose(mapping.project(eye),.4*TARGETS[0]+.3*TARGETS[1]+.3*TARGETS[2]))
        with self.assertRaises(ValueError):AnchorMap(eyes[[0,1,3,2,4]])

    def test_missing_stationary_and_duplicate_samples_cannot_produce_map(self):
        flow=QuickCalibration([.47,.42],100.)
        for _ in range(100):flow.observe([.47,.42],101.,101.)
        self.assertEqual(len(flow.samples),1)
        with self.assertRaises(ValueError):flow.fit()
        for t in np.arange(0,DURATION,1/30):flow.observe([.47,.42],100+t,100+t)
        with self.assertRaises(ValueError):flow.fit()

    def test_travel_is_not_captured_and_completed_pass_never_repeats(self):
        flow=QuickCalibration([.47,.42],100.)
        for t in np.arange(0,TRAVEL,1/60):self.assertFalse(flow.observe([.4,.4],100+t,100+t))
        self.assertTrue(np.allclose(target_at(100),TARGETS[-1]))
        for i in range(4):
            self.assertTrue(np.allclose(target_at(i*STEP+TRAVEL),TARGETS[i+1]))

    def test_missing_corner_waits_then_retry_preserves_completed_measurements(self):
        flow=QuickCalibration([.47,.42],100.)
        for t in np.arange(0,6,1/30):
            target=np.array(flow.target(100+t))
            flow.observe(target*[.18,.14]+[.38,.35],100+t,100+t)
        self.assertEqual(flow.index,3)
        saved=[list(b) for b in flow.blocks[:3]]
        start=flow.corner_started_at
        flow.advance(start+3)
        self.assertFalse(flow.finished)
        self.assertFalse(flow.timed_out)
        self.assertTrue(np.allclose(flow.target(start+3),TARGETS[4]))
        self.assertEqual(flow.progress_at(start+3),0)
        flow.advance(start+8.01)
        self.assertTrue(flow.timed_out)
        flow.retry(120.)
        self.assertEqual(flow.index,3)
        for a,b in zip(saved,flow.blocks[:3]):
            self.assertTrue(np.array_equal([p[1] for p in a],[p[1] for p in b]))
        for t in np.arange(0,2.1,1/30):
            flow.observe(TARGETS[4]*[.18,.14]+[.38,.35],120+t,120+t)
        self.assertTrue(flow.finished)
        self.assertTrue(np.allclose(flow.fit().project(TARGETS[4]*[.18,.14]+[.38,.35]),TARGETS[4]))

    def test_delayed_good_samples_advance_without_restarting_the_whole_pass(self):
        flow=QuickCalibration([.47,.42],100.)
        flow.advance(103.)
        self.assertEqual(flow.index,0)
        self.assertEqual(flow.progress_at(103.),0)
        for t in np.arange(3,3.6,1/30):
            flow.observe(TARGETS[1]*[.18,.14]+[.38,.35],100+t,100+t)
        self.assertEqual(flow.index,1)
        self.assertEqual(flow.coverage,1)


class PoseAnchorTests(unittest.TestCase):
    def setUp(self):
        self.base=AnchorMap(TARGETS*[.18,.14]+[.38,.35])
        self.pose=np.array([0.,0.,0.,.5,.4,-1.2])

    def test_correction_persists_across_eye_motion_but_respects_unobserved_head_poses(self):
        target=np.array([.5,.5]);eye=np.array([.56,.47])*[.18,.14]+[.38,.35]
        turned=self.pose+np.array([.17,0,0,0,0,0])
        learned=PoseAnchorMap(self.base,[(eye,turned,target)])
        self.assertTrue(np.allclose(learned.project_pose(eye,turned,False),target))
        other_head=learned.project_pose(eye,self.pose)
        self.assertGreater(other_head[0],.5, 'An unobserved head pose must not receive the full correction')
        distant=np.array([.08,.08])*[.18,.14]+[.38,.35]
        self.assertTrue(np.allclose(learned.project_pose(distant,turned),[.02,.11]),
                        'Moving the eyes must not silently throw away a measured screen offset')
        self.assertIsNone(learned.project_pose(eye,self.pose+[.7,0,0,0,0,0],False))

    def test_repeated_target_head_changes_generalize_to_unseen_gaze_and_pose(self):
        anchors=[]
        for yaw,pitch in ((0,0),(-.14,0),(.14,0),(0,-.12),(0,.12)):
            head=self.pose+np.array([yaw,pitch,0,0,0,0])
            offset=np.array([yaw*.8,pitch*.65])
            target=np.array([.5,.5])
            eye=(target+offset)*[.18,.14]+[.38,.35]
            anchors.append((eye,head,target))
        learned=PoseAnchorMap(self.base,anchors)
        self.assertEqual(learned.head_model.rank,2)
        self.assertEqual(learned.head_model.status,'learned')
        for target in ([.7,.3],[.15,.8]):
            head=self.pose+np.array([.065,-.05,0,0,0,0])
            eye=(np.array(target)+[.065*.8,-.05*.65])*[.18,.14]+[.38,.35]
            self.assertTrue(np.allclose(learned.project_pose(eye,head,False),target,atol=.01))
        self.assertIsNone(learned.project_pose(eye,head+[0,0,.7,0,0,0],False))

    def test_different_screen_targets_do_not_invent_head_compensation(self):
        anchors=[]
        for i,target in enumerate(TARGETS):
            head=self.pose+np.array([i*.08,0,0,0,0,0])
            anchors.append((target*[.18,.14]+[.38,.35],head,target))
        self.assertEqual(PoseAnchorMap(self.base,anchors).head_model.rank,0)
        self.assertEqual(PoseAnchorMap(self.base,anchors).head_model.status,'insufficient_repeats')

    def test_inconsistent_head_effect_reports_rejection_without_erasing_local_anchors(self):
        anchors=[]
        for yaw,offset in ((-.28,.20),(-.14,-.15),(0,.20),(.14,-.15),(.28,.20)):
            head=self.pose+np.array([yaw,0,0,0,0,0])
            target=np.array([.5,.5])
            eye=(target+[offset,0])*[.18,.14]+[.38,.35]
            anchors.append((eye,head,target))
        learned=PoseAnchorMap(self.base,anchors)
        self.assertEqual(learned.head_model.rank,0)
        self.assertEqual(learned.head_model.status,'inconsistent')
        self.assertGreater(learned.head_model.fit_error,.08)
        self.assertGreaterEqual(learned.head_model.pair_count,3)
        self.assertIsNone(learned.head_model.error)
        for eye,head,target in anchors:
            self.assertTrue(np.allclose(learned.project_pose(eye,head,False),target,atol=.001))

    def test_one_second_fixation_saves_paired_pose_and_survives_finish_restart(self):
        session=CursorCalibration(self.base);session.active=True
        eye=np.array([.56,.47])*[.18,.14]+[.38,.35]
        for i in range(12):session.observe([.5,.5],eye,i*.1,i*.1,pose=self.pose)
        self.assertIsNone(session.candidate)
        for i in range(12,17):session.observe([.5,.5],eye,i*.1,i*.1,pose=self.pose)
        self.assertEqual(session.state()['saved_anchors'],1)
        self.assertEqual(session.progress,1)
        self.assertTrue(np.allclose(session.pose_points[0][1],self.pose))
        resumed=CursorCalibration(session.candidate)
        self.assertEqual(len(resumed.pose_points),1)
        self.assertFalse(resumed.active)

    def test_conflicting_fixation_rejected_and_previous_map_kept(self):
        eye=np.array([.5,.5])*[.18,.14]+[.38,.35]
        with self.assertRaises(ValueError):PoseAnchorMap(self.base,[(eye,self.pose,[.5,.5]),(eye,self.pose,[.8,.8])])
        session=CursorCalibration(PoseAnchorMap(self.base,[(eye,self.pose,[.5,.5])]))
        session.active=True
        for i in range(16):session.observe([.8,.8],eye,i*.1,i*.1,pose=self.pose)
        self.assertEqual(len(session.pose_points),1)
        self.assertIn('conflicts',session.message)
