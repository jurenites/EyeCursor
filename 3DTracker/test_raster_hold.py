import unittest
from unittest.mock import patch
import cv2
import numpy as np
from raster_hold import RasterHold
from monitor_demo import usable
import Orlosky3DEyeTracker as tracker


def eye(x=320):
    frame=np.full((480,640,3),140,dtype=np.uint8)
    cv2.ellipse(frame,(x,240),(40,32),0,0,360,(20,20,20),-1)
    cv2.circle(frame,(x+8,248),3,(255,255,255),-1)
    return frame


def result(confidence=.9):
    return {'pupil_ellipse':{'center':[320,240],'axes':[80,64],'angle_degrees':0},
            'confidence':confidence,'gaze_direction':[0,0,1],
            'temporal_tracking':{'accepted':True},'eye_model_updated':True}


class RasterHoldTests(unittest.TestCase):
    def setUp(self):
        self.hold=RasterHold();self.frame=eye()
        self.hold.update(self.frame,result(),10,.5)

    def test_static_pixels_bridge_failed_detector_without_promoting_raw_evidence(self):
        failed=result(.2);row=self.hold.update(self.frame,failed,10.03,.5)
        self.assertIsNot(row,failed)
        self.assertEqual(row['confidence'],.2)
        self.assertFalse(usable(row))
        self.assertEqual(row['display_hold']['pupil_ellipse']['center'],[320,240])
        self.assertEqual(row['display_hold']['measured_at'],10)
        self.assertFalse(row['display_hold']['eye_model_updated'])
        for stamp in (10.06,10.09):
            row=self.hold.update(self.frame,row,stamp,.5)
            self.assertEqual(row['display_hold']['measured_at'],10)
        self.assertNotIn('display_hold',self.hold.update(self.frame,failed,10.13,.5))

    def test_changed_eye_blink_saccade_and_lighting_do_not_hold(self):
        blink=self.frame.copy();blink[190:290,265:375]=140
        for image in (blink,eye(335),np.clip(self.frame.astype(int)+25,0,255).astype('uint8')):
            with self.subTest(image_mean=image.mean()):
                self.assertNotIn('display_hold',self.hold.update(image,result(.1),10.03,.5))

    def test_small_sensor_noise_does_not_interrupt_but_background_cannot_mask_eye_motion(self):
        rng=np.random.default_rng(2)
        noisy=np.clip(self.frame.astype(int)+rng.integers(-2,3,self.frame.shape),0,255).astype('uint8')
        self.assertIn('display_hold',self.hold.update(noisy,result(.1),10.03,.5))
        self.assertNotIn('display_hold',self.hold.update(eye(330),result(.1),10.06,.5))

    def test_reset_and_reversed_time_cannot_reuse_another_camera(self):
        self.hold.reset()
        self.assertIsNone(self.hold.update(self.frame,None,10.03,.5))
        self.hold.update(self.frame,result(),11,.5)
        self.assertIsNone(self.hold.update(self.frame,None,10,.5))

    def test_both_detector_instances_use_guard_and_reset_it(self):
        from binocular_tracking import independent_detector
        for module in (tracker,independent_detector()):
            module.reset_tracking_state()
            def detect(frame,timestamp=None):module.last_tracking_result=result();return None
            with patch.object(module,'_process_frame',side_effect=detect):module.process_frame(self.frame.copy(),10)
            def fail(frame,timestamp=None):module.last_tracking_result=result(.1);return None
            with patch.object(module,'_process_frame',side_effect=fail):module.process_frame(self.frame.copy(),10.03)
            self.assertIn('display_hold',module.get_last_tracking_result())
            module.reset_tracking_state()
            self.assertIsNone(module._raster_hold.stamp)
