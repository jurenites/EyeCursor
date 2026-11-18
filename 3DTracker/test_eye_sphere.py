"""Scale comes from shared rotation geometry, independently for each camera."""
import math
import unittest
import numpy as np
import cv2
from eye_geometry import fit_eye_sphere, sphere_direction
from monitor_demo import render_diagnostic_frame
from binocular_tracking import independent_detector


def observations(scale=1.,angle_offset=0.,noise=0.):
    pupils=[];irises=[];rng=np.random.default_rng(8)
    center=np.array([320.,240.]);length=100*scale
    for angle in range(0,360,8):
        phi=math.radians(angle+angle_offset)
        theta=math.radians(25+20*(.5+.5*math.sin(math.radians(angle*3))))
        q=math.cos(theta);p=center+length*math.sin(theta)*np.array([math.cos(phi),math.sin(phi)])
        p+=rng.normal(0,noise,2)
        pupils.append((tuple(p),(40*scale*q,40*scale),angle+angle_offset))
        irises.append((tuple(p),(100*scale*q,100*scale),angle+angle_offset))
    return pupils,irises


class SphereTests(unittest.TestCase):
    def test_recovers_scale_independently_of_camera_zoom_and_rotation(self):
        for scale,rotation in ((.6,0),(1,180),(1.4,37)):
            pupils,irises=observations(scale,rotation,.2)
            fit=fit_eye_sphere(pupils,(480,640),irises)
            self.assertIsNotNone(fit)
            self.assertLess(np.linalg.norm(np.array(fit['center'])-[320,240]),1)
            self.assertAlmostEqual(fit['rotation_radius_px'],100*scale,delta=1)
            self.assertAlmostEqual(fit['radius_px'],math.hypot(100,50)*scale,delta=1)
            direction=sphere_direction(pupils[0],fit['center'],fit['rotation_radius_px'])
            self.assertAlmostEqual(direction[2],min(pupils[0][1])/max(pupils[0][1]),delta=.02)

    def test_outlier_cannot_permanently_inflate_radius(self):
        pupils,irises=observations()
        clean=fit_eye_sphere(pupils,(480,640),irises)
        bad=list(pupils)
        for i in range(5):
            p=np.array(bad[i][0]);bad[i]=(tuple([320,240]+3*(p-[320,240])),bad[i][1],bad[i][2])
        fit=fit_eye_sphere(bad,(480,640),irises)
        self.assertAlmostEqual(fit['radius_px'],clean['radius_px'],delta=1)

    def test_missing_iris_and_inconsistent_scale_do_not_become_eyeball(self):
        pupils,irises=observations()
        self.assertIsNone(fit_eye_sphere(pupils,(480,640)))
        bad=[]
        for i,(p,axes,a) in enumerate(pupils):
            scale=(.4,1.,2.)[i%3]
            bad.append((tuple(np.array([320,240])+scale*(np.array(p)-[320,240])),axes,a))
        self.assertIsNone(fit_eye_sphere(bad,(480,640),irises))
        self.assertIsNone(fit_eye_sphere(pupils[:8],(480,640),irises[:8]))

    def test_direction_has_named_axes_and_rejects_outside_sphere(self):
        pupil=((340,230),(30,40),0)
        direction=sphere_direction(pupil,(320,240),100)
        np.testing.assert_allclose(direction[:2],[.2,.1])
        self.assertAlmostEqual(np.linalg.norm(direction),1)
        self.assertIsNone(sphere_direction(pupil,(320,240),10))

    def test_pupil_remains_accepted_without_an_invented_sphere_direction(self):
        frame=np.zeros((480,640,3),np.uint8)
        result={'pupil_ellipse':{'center':[320,240],'axes':[40,50],'angle_degrees':0},'confidence':.9}
        image=render_diagnostic_frame(frame,result,hybrid=True)
        self.assertTrue(np.array_equal(image[240,320],[40,220,40]))
        self.assertFalse(np.any(np.all(image==[255,230,60],axis=2)))

    def test_real_detector_recovers_one_model_from_rotating_eye_pixels(self):
        tracker=independent_detector()
        tracker.DISPLAY_ENABLED=False;tracker.GL_SPHERE_AVAILABLE=False
        tracker.pupil_confidence_threshold=.5;tracker.pupil_confidence_threshold_sphere=.5
        pupils,irises=observations()
        for i,(pupil,iris) in enumerate(list(zip(pupils,irises))*2):
            frame=np.full((480,640,3),180,np.uint8)
            cv2.ellipse(frame,iris,(65,65,65),-1)
            cv2.ellipse(frame,pupil,(10,10,10),-1)
            tracker.process_frame(frame,timestamp=i/30)
        result=tracker.get_last_tracking_result()
        self.assertTrue(result['eye_model_estimated'])
        self.assertAlmostEqual(result['sphere_radius'],math.hypot(100,50),delta=2)
        fit=result['eye_sphere_fit'];p=result['pupil_ellipse']
        expected=sphere_direction((p['center'],p['axes'],p['angle_degrees']),result['eye_center'],fit['rotation_radius_px'])
        np.testing.assert_allclose(result['gaze_direction'],expected)
        tracker.reset_tracking_state()
        self.assertEqual(tracker.compute_gaze_vector(320,240,320,240),(None,None))

    def test_detector_instances_reset_geometry_separately(self):
        left=independent_detector();right=independent_detector()
        left.last_sphere_fit={'radius_px':160};left.sphere_iris_history.append('left')
        self.assertIsNone(right.last_sphere_fit);self.assertEqual(right.sphere_iris_history,[])
        left.reset_tracking_state();self.assertIsNone(left.last_sphere_fit)
        self.assertEqual(left.sphere_iris_history,[])

if __name__=='__main__':unittest.main()
