import unittest
from unittest.mock import patch
import cv2
import numpy as np
from pupil_stabilization import PupilStabilizer, border_candidate
from test_raster_hold import eye
import Orlosky3DEyeTracker as tracker


class StabilizationTests(unittest.TestCase):
    def test_unchanged_pixels_reduce_alternating_diameter_and_center_noise(self):
        smoother=PupilStabilizer();frame=cv2.cvtColor(eye(),cv2.COLOR_BGR2GRAY)
        outputs=[]
        for i in range(30):
            sign=1 if i%2 else -1
            measured=((320+sign*2,240),(80+sign*5,64+sign*4),179 if sign==1 else 1)
            result,info=smoother.update(frame,measured,.9,i/30)
            outputs.append(result)
        self.assertLess(np.ptp([p[1][0] for p in outputs[10:]]),3)
        self.assertLess(np.ptp([p[0][0] for p in outputs[10:]]),2)
        self.assertTrue(info['smoothed'])
        self.assertGreater(abs(result[2]-90),80,'Wrapped ellipse angles must not average to 90 degrees')

    def test_real_image_motion_and_dilation_bypass_smoothing(self):
        smoother=PupilStabilizer();frame=cv2.cvtColor(eye(),cv2.COLOR_BGR2GRAY)
        initial=((320,240),(80,64),0)
        smoother.update(frame,initial,.9,0)
        moved=((340,240),(80,64),0)
        result,info=smoother.update(cv2.cvtColor(eye(340),cv2.COLOR_BGR2GRAY),moved,.9,.033)
        self.assertEqual(result,moved);self.assertFalse(info['smoothed'])
        changed=cv2.cvtColor(eye(340),cv2.COLOR_BGR2GRAY)
        cv2.ellipse(changed,(340,240),(46,37),0,0,360,20,-1)
        dilation=((340,240),(92,74),0)
        result,info=smoother.update(changed,dilation,.9,.066)
        self.assertEqual(result,dilation);self.assertFalse(info['smoothed'])

    def test_blinks_low_confidence_and_long_gaps_do_not_create_measurements(self):
        smoother=PupilStabilizer();frame=cv2.cvtColor(eye(),cv2.COLOR_BGR2GRAY)
        pupil=((320,240),(80,64),0)
        smoother.update(frame,pupil,.9,0)
        self.assertIsNone(smoother.update(frame,None,0,.03)[0])
        weak=((322,240),(84,68),0)
        self.assertEqual(smoother.update(frame,weak,.2,.06)[0],weak)
        smoother.update(frame,pupil,.9,.09)
        self.assertEqual(smoother.update(frame,weak,.9,1)[0],weak)

    def test_independent_eyes_and_reset_do_not_share_smoothing(self):
        from binocular_tracking import independent_detector
        left=tracker;right=independent_detector()
        self.assertIsNot(left._pupil_stabilizer,right._pupil_stabilizer)
        frame=cv2.cvtColor(eye(),cv2.COLOR_BGR2GRAY)
        left._pupil_stabilizer.update(frame,((320,240),(80,64),0),.9,0)
        right.reset_tracking_state()
        self.assertIsNotNone(left._pupil_stabilizer.previous)
        left.reset_tracking_state()
        self.assertIsNone(left._pupil_stabilizer.previous)

    def test_border_guard_rejects_corners_and_clipped_ellipses_not_off_center_eye(self):
        for center in ((20,240),(620,240),(320,15),(320,465),(20,20)):
            self.assertTrue(border_candidate((center,(30,20),0),(480,640)))
        self.assertTrue(border_candidate(((70,240),(150,60),0),(480,640)))
        self.assertFalse(border_candidate(((150,160),(90,60),45),(480,640)))

    def test_high_scoring_border_iris_cannot_train_eye_model(self):
        tracker.reset_tracking_state();self.addCleanup(tracker.reset_tracking_state)
        frame=eye();gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        bad=((20,20),(30,24),0)
        guide={'ellipse':((30,30),(80,70),0),'support':.99}
        with patch.object(tracker,'detect_pupil_in_iris',return_value={'ellipse':bad,'confidence':.99}), \
                patch.object(tracker,'update_eye_sphere_radius') as model:
            tracker.process_frames(None,None,None,frame,gray,None,False,False,guide,0)
        row=tracker.get_last_tracking_result()
        self.assertEqual(row['temporal_tracking']['reason'],'frame-border')
        self.assertEqual(row['confidence'],0)
        self.assertEqual(tracker.ray_lines,[])
        model.assert_not_called()

    def test_pipeline_preserves_measurement_and_uses_stabilized_ellipse(self):
        tracker.reset_tracking_state();self.addCleanup(tracker.reset_tracking_state)
        gray=cv2.cvtColor(eye(),cv2.COLOR_BGR2GRAY)
        guide={'ellipse':((320,240),(200,160),0),'support':.95}
        with patch.object(tracker,'DISPLAY_ENABLED',False), \
                patch.object(tracker,'eye_sphere_adjustment_enabled',False):
            for i,width in enumerate((80,88)):
                pupil=((320,240),(width,width*.8),0)
                edges={'ellipse':pupil,'confidence':.9,'edge_points':[]}
                with patch.object(tracker,'detect_pupil_in_iris',return_value=edges):
                    tracker.process_frames(None,None,None,cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR),
                                           gray,None,False,False,guide,i/30)
        row=tracker.get_last_tracking_result()
        self.assertEqual(row['measured_pupil_ellipse']['axes'],[88,70.4])
        self.assertTrue(row['pupil_stabilization']['smoothed'])
        self.assertGreater(row['pupil_ellipse']['axes'][0],80)
        self.assertLess(row['pupil_ellipse']['axes'][0],84)
