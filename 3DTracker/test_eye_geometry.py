"""Geometric rejection, iris support, and display-only threshold hysteresis."""
import math
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from eye_geometry import fit_eye_center, trace_iris, ellipse_normal, DetectionLatch, refine_pupil_with_iris, iris_supported_confidence


def rays(center=(310, 225), noise=0):
    rng = np.random.default_rng(4)
    return [((center[0]+55*math.cos(math.radians(a))+rng.normal(0, noise),
              center[1]+55*math.sin(math.radians(a))+rng.normal(0, noise)), (28, 40), a)
            for a in range(0, 360, 8)]


class GeometryTests(unittest.TestCase):
    def test_robust_center_ignores_outliers_and_is_deterministic(self):
        observations = rays(noise=.5)
        observations += [((90+i*2, 80+i), (20, 40), i*17) for i in range(15)]
        fitted = fit_eye_center(observations, (480, 640))
        self.assertIsNotNone(fitted)
        self.assertLess(np.linalg.norm(np.array(fitted['center']) - [310,225]), 2)
        self.assertEqual(fitted, fit_eye_center(observations, (480,640)))

    def test_circular_parallel_stationary_and_sparse_rays_cannot_estimate_center(self):
        cases = [rays()[:8], [((x[0]), (39,40), x[2]) for x in rays()],
                 [(x[0], x[1], 10) for x in rays()], [((310,225),(20,40),i*12) for i in range(30)]]
        for sample in cases:
            with self.subTest(sample=sample[:1]):
                self.assertIsNone(fit_eye_center(sample, (480,640)))

    def test_minor_axis_normal_handles_swapped_opencv_axes(self):
        first = ellipse_normal(((300,200),(20,40),15))[0]
        other = ellipse_normal(((300,200),(40,20),105))[0]
        self.assertAlmostEqual(abs(float(first @ other)), 1)
        self.assertIsNone(ellipse_normal(((300,200),(40,40),71)))

    def eye(self, iris=True):
        image=np.full((480,640),180,dtype=np.uint8)
        if iris: cv2.ellipse(image,((320,240),(190,150),12),65,-1)
        cv2.ellipse(image,((320,240),(72,56),12),12,-1)
        cv2.circle(image,(309,248),4,255,-1)
        cv2.circle(image,(325,247),4,255,-1)
        return image

    def test_enclosing_iris_with_ir_glints_is_traced(self):
        iris=trace_iris(self.eye(),((320,240),(72,56),12))
        self.assertIsNotNone(iris)
        self.assertLess(np.linalg.norm(np.array(iris['ellipse'][0])-[320,240]),2)
        self.assertLess(np.max(np.abs(np.sort(iris['ellipse'][1])-[150,190])),4)
        self.assertGreater(iris['support'],.5)

    def test_missing_iris_and_eyelid_only_edges_are_rejected(self):
        for image in [self.eye(False),np.full((480,640),120,dtype=np.uint8)]:
            cv2.line(image,(100,185),(500,185),220,3)
            cv2.line(image,(100,295),(500,295),220,3)
            self.assertIsNone(trace_iris(image,((320,240),(72,56),12)))

    def test_partial_eyelid_occlusion_retains_supported_iris(self):
        image=self.eye()
        image[:185]=180
        iris=trace_iris(image,((320,240),(72,56),12))
        self.assertIsNotNone(iris)
        self.assertLess(np.linalg.norm(np.array(iris['ellipse'][0])-[320,240]),5)

    def test_hysteresis_requires_entry_score_and_releases_after_loss(self):
        latch=DetectionLatch()
        self.assertFalse(latch.update(.47,True,.5,0))
        self.assertTrue(latch.update(.51,True,.5,.1))
        for i in range(1,20):
            self.assertTrue(latch.update(.47 if i%2 else .51,True,.5,.1+i/30))
        self.assertFalse(latch.update(.47,False,.5,1))
        self.assertFalse(latch.update(.47,True,.5,1.1))
        self.assertTrue(latch.update(.51,True,.5,1.2))
        latch.reset()
        self.assertFalse(latch.update(.47,True,.5,1.3))


class IrisPupilCorrectionTests(unittest.TestCase):
    def damaged_eye(self, angle=20, clip=24):
        image = np.full((480,640),180,np.uint8)
        iris = {'ellipse': ((320,240),(200,160),angle), 'support': .9}
        pupil = ((324,238),(80,64),angle)
        cv2.ellipse(image,iris['ellipse'],65,-1)
        cv2.ellipse(image,pupil,12,-1)
        yy,xx = np.indices(image.shape)
        theta = math.radians(angle)
        local_y = -(xx-324)*math.sin(theta)+(yy-238)*math.cos(theta)
        image[(image==12)&(np.abs(local_y)>clip)] = 120
        mask = (image<30).astype(np.uint8)*255
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        return image,iris,cv2.fitEllipse(contours[0]),contours[0]

    def test_reflections_recover_shared_ratio_and_separate_pupil_center(self):
        for angle in (0,20,65,110,165):
            with self.subTest(angle=angle):
                image,iris,raw,contour = self.damaged_eye(angle)
                result = refine_pupil_with_iris(image,raw,iris,contour)
                self.assertIsNotNone(result)
                center,axes,rotation = result['ellipse']
                self.assertLess(np.linalg.norm(np.array(center)-[324,238]),1)
                self.assertLess(np.max(np.abs(np.array(axes)-[80,64])),2)
                self.assertAlmostEqual(min(axes)/max(axes),.8)
                self.assertEqual(rotation,angle)
                self.assertGreater(result['edge_support'],.55)
                self.assertEqual(result,refine_pupil_with_iris(image,raw,iris,contour))

    def test_broad_reflection_gradient_recovers_edges_outside_dark_contour(self):
        for angle in (0,30,80):
            for blur in (0,1.2):
                with self.subTest(angle=angle,blur=blur):
                    image=np.full((480,640),180,np.uint8)
                    iris={'ellipse':((320,240),(200,180),angle),'support':.9}
                    cv2.ellipse(image,iris['ellipse'],80,-1)
                    mask=np.zeros_like(image)
                    cv2.ellipse(mask,((323,238),(80,72),angle),255,-1)
                    y,x=np.indices(image.shape)
                    u=(x-323)*math.cos(math.radians(angle))+(y-238)*math.sin(math.radians(angle))
                    image[mask>0]=(12+55*(u[mask>0]/40)**2).clip(0,255).astype(np.uint8)
                    cv2.circle(image,(318,249),3,255,-1)
                    if blur: image=cv2.GaussianBlur(image,(5,5),blur)
                    contours,_=cv2.findContours((image<35).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
                    contour=max(contours,key=cv2.contourArea)
                    raw=cv2.fitEllipse(contour)
                    self.assertLess(min(raw[1])/max(raw[1]),.8)
                    fixed=refine_pupil_with_iris(image,raw,iris,contour)
                    self.assertIsNotNone(fixed)
                    center,axes,rotation=fixed['ellipse']
                    self.assertLess(np.linalg.norm(np.array(center)-[323,238]),1.5)
                    self.assertLess(np.max(np.abs(np.array(axes)-[80,72])),4)
                    self.assertAlmostEqual(min(axes)/max(axes),.9)
                    self.assertEqual(rotation,angle)
                    self.assertGreater(fixed['edge_support'],.75)
                    self.assertIsNone(refine_pupil_with_iris(np.full_like(image,80),raw,iris,contour))

    def test_swapped_iris_axes_produce_same_pupil_shape(self):
        image,iris,raw,contour = self.damaged_eye()
        first = refine_pupil_with_iris(image,raw,iris,contour)['ellipse']
        iris['ellipse'] = ((320,240),(160,200),110)
        second = refine_pupil_with_iris(image,raw,iris,contour)['ellipse']
        self.assertTrue(np.allclose(first[0],second[0]))
        self.assertTrue(np.allclose(sorted(first[1]),sorted(second[1])))

    def test_no_correction_without_current_pupil_or_strong_iris(self):
        image,iris,raw,contour = self.damaged_eye()
        self.assertIsNone(refine_pupil_with_iris(image,None,iris,contour))
        self.assertIsNone(refine_pupil_with_iris(image,raw,None,contour))
        self.assertIsNone(refine_pupil_with_iris(image,raw,{**iris,'support':.3},contour))
        self.assertIsNone(refine_pupil_with_iris(image,raw,iris,contour[:5]))

    def test_blink_excessive_glare_and_wrong_iris_cannot_reconstruct_pupil(self):
        image,iris,raw,contour = self.damaged_eye(clip=16)
        self.assertIsNone(refine_pupil_with_iris(image,raw,iris,contour))
        image,iris,raw,contour = self.damaged_eye()
        self.assertIsNone(refine_pupil_with_iris(np.full_like(image,80),raw,iris,contour))
        iris['ellipse'] = ((320,240),(200,160),80)
        self.assertIsNone(refine_pupil_with_iris(image,raw,iris,contour))

    def test_genuinely_narrow_pupil_and_matching_shapes_stay_unchanged(self):
        image,iris,_,_ = self.damaged_eye()
        for axes in ((80,42),(80,64),(80,75)):
            cv2.ellipse(image,iris['ellipse'],65,-1)
            pupil = ((324,238),axes,20)
            cv2.ellipse(image,pupil,12,-1)
            contours,_ = cv2.findContours((image<30).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
            raw = cv2.fitEllipse(contours[0])
            self.assertIsNone(refine_pupil_with_iris(image,raw,iris,contours[0]))

    def test_real_detector_preserves_raw_score_and_uses_stronger_evidence(self):
        import Orlosky3DEyeTracker as tracker
        gray,_,_,_ = self.damaged_eye(angle=65)
        frame = cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
        with patch.object(tracker,'DISPLAY_ENABLED',False), patch.object(tracker,'eye_sphere_adjustment_enabled',False):
            tracker.reset_tracking_state()
            tracker.process_frame(frame.copy())
            corrected = tracker.get_last_tracking_result()
            tracker.reset_tracking_state()
            with patch.object(tracker,'trace_iris',return_value=None):
                tracker.process_frame(frame.copy())
                original = tracker.get_last_tracking_result()
            tracker.reset_tracking_state()
        self.assertEqual(corrected['pupil_shape_source'],'iris-edge')
        self.assertEqual(original['pupil_shape_source'],'pupil')
        self.assertEqual(corrected['raw_pupil_confidence'],original['raw_pupil_confidence'])
        self.assertEqual(corrected['confidence'],corrected['iris_pupil_confidence'])
        self.assertEqual(corrected['raw_pupil_ellipse'],original['pupil_ellipse'])
        ratio = lambda e: min(e['axes'])/max(e['axes'])
        self.assertAlmostEqual(ratio(corrected['pupil_ellipse']),ratio(corrected['iris_ellipse']))
        self.assertLess(np.linalg.norm(np.array(corrected['pupil_ellipse']['center'])-[324,238]),1)

    def test_supported_repair_can_rescue_a_low_contour_score(self):
        image,iris,raw,contour=self.damaged_eye(65)
        fixed=refine_pupil_with_iris(image,raw,iris,contour)['ellipse']
        score=iris_supported_confidence(image,fixed,iris,.35)
        self.assertGreaterEqual(score,.60)
        self.assertLessEqual(score,.9)

    def test_moderate_focus_blur_still_requires_visible_edges(self):
        image,iris,_,_=self.damaged_eye(clip=100)
        pupil=((324,238),(80,64),20)
        blurred=cv2.GaussianBlur(image,(9,9),2)
        self.assertGreater(iris_supported_confidence(blurred,pupil,iris,.4),.6)
        self.assertEqual(iris_supported_confidence(np.full_like(image,65),pupil,iris,.4),0)

    def test_iris_or_dark_patch_alone_cannot_raise_confidence(self):
        image,iris,raw,contour=self.damaged_eye()
        fixed=refine_pupil_with_iris(image,raw,iris,contour)['ellipse']
        for pupil,guide,score in [(None,iris,.4),(fixed,None,.4),
                                  (fixed,{**iris,'support':.5},.4),(fixed,iris,.1)]:
            self.assertEqual(iris_supported_confidence(image,pupil,guide,score),0)
        cv2.ellipse(image,iris['ellipse'],65,-1)  # No dark pupil remains.
        self.assertEqual(iris_supported_confidence(image,fixed,iris,.4),0)

    def test_clipped_or_incompatible_shapes_cannot_gain_iris_confidence(self):
        image,iris,raw,contour=self.damaged_eye(clip=16)
        self.assertEqual(iris_supported_confidence(image,raw,iris,.4),0)
        image,iris,raw,contour=self.damaged_eye()
        self.assertEqual(iris_supported_confidence(image,((400,300),(80,64),20),iris,.4),0)
        self.assertEqual(iris_supported_confidence(image,((324,238),(80,20),20),iris,.4),0)

if __name__ == '__main__': unittest.main()
