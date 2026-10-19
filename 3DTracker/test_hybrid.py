"""Two-camera pairing and head-compensated gaze, without camera/UI side effects."""
import math
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from head_camera import HeadCamera, choose_head_camera, pose_from_landmarks, preview_irises, FacePreviewCrop
from hybrid_onboarding import HeadCompensation, HybridOnboarding, FivePointMap, TARGETS, HEAD_SCALE, ORBIT_SECONDS
from quick_calibration import target_at as circular_target, DURATION as FIRST_PAIR_SECONDS
from monitor_demo import Calibration


BASE = np.array([0.,0.,0.,.5,.4,math.log(.3)])
# Known synthetic head effect in IR image coordinates.
EFFECT = np.array([[.035,.002],[.004,.025],[.005,.002],[.004,.0],[0.,.003],[.002,.002]])


def pose(t):
    return BASE+np.array([.13*math.sin(t*1.4),.10*math.sin(t*2.1),.01*math.sin(t*.8),
                          .01*math.sin(t*1.4),.006*math.sin(t*2.1),.005*math.cos(t)])


def pupil(target,head):
    return np.array(target)*[.18,.14]+[.38,.35]+(head-BASE)/HEAD_SCALE@EFFECT


class HeadGeometryTests(unittest.TestCase):
    def test_default_builtin_selection_and_explicit_external_identity(self):
        cams=[{'type':'AVCaptureDeviceTypeExternal','id':'ir','index':0},
              {'type':'AVCaptureDeviceTypeExternal','id':'iphone','index':1},
              {'type':'AVCaptureDeviceTypeBuiltInWideAngleCamera','id':'built','index':2}]
        self.assertEqual(choose_head_camera(cams)['id'],'built')
        self.assertEqual(choose_head_camera(cams,'iphone')['id'],'iphone')
        with self.assertRaises(ValueError):choose_head_camera(cams,'missing')
        with self.assertRaises(ValueError):choose_head_camera(cams[:2])

    def test_pairing_refuses_old_and_no_face_samples(self):
        camera=HeadCamera(lambda:[])
        camera.history.append({'time':10.,'pose':{'features':BASE.tolist(),'irises':[]},'epoch':1})
        self.assertIsNotNone(camera.sample_at(10.05))
        self.assertIsNone(camera.sample_at(10.2))
        camera.history.append({'time':10.06,'pose':None,'epoch':1})
        self.assertIsNone(camera.sample_at(10.07))
        self.assertFalse(camera.status(10.08)['face_visible'])

    def test_preview_eye_anchors_follow_letterboxing_and_expire(self):
        self.assertEqual(preview_irises([[0,0],[1,1]], 1280, 720), [[0,.125],[1,.875]])
        self.assertEqual(preview_irises([[0,0],[1,1]], 480, 640), [[.21875,0],[.78125,1]])
        camera = HeadCamera(lambda: [])
        anchors = [[.4,.5],[.6,.5]]
        camera.history.append({'time':10., 'pose':{'features':BASE.tolist()},
                               'epoch':1, 'preview_irises':anchors})
        self.assertEqual(camera.status(10.1)['preview_irises'], anchors)
        self.assertEqual(camera.status(10.1)['features'], BASE.tolist())
        self.assertIsNone(camera.status(10.3)['preview_irises'])
        self.assertIsNone(camera.status(10.3)['features'])
        camera.history.append({'time':10.4,'pose':None,'epoch':1,'preview_irises':None})
        self.assertIsNone(camera.status(10.4)['preview_irises'])

    def test_closeup_crop_bounds_aspect_anchors_and_face_loss(self):
        cropper=FacePreviewCrop()
        for box in ([.35,.2,.6,.7],[0,0,.2,.4],[.8,.6,1,1]):
            crop=cropper.update(box,1280,720,10)
            x0,y0,x1,y1=crop
            self.assertTrue(0<=x0<x1<=1280 and 0<=y0<y1<=720)
            self.assertAlmostEqual((x1-x0)/(y1-y0),4/3,delta=.005)
            center=[(x0+x1)/2/1280,(y0+y1)/2/720]
            self.assertTrue(np.allclose(preview_irises([center],1280,720,crop),[[.5,.5]],atol=.002))
        self.assertEqual(cropper.update(None,1280,720,10.2),crop)
        self.assertEqual(cropper.update(None,1280,720,10.6),(0,0,1280,720))
        self.assertEqual(cropper.update(None,640,480,11),(0,0,640,480))

    def test_pairing_reports_timestamp_gap_separately_from_missing_face(self):
        camera=HeadCamera(lambda:[])
        self.assertIsNone(camera.sample_at(10))
        camera.history.append({'time':10.,'pose':None,'epoch':1})
        self.assertIsNone(camera.sample_at(10.05))
        self.assertIsNone(camera.sample_at(10.3))
        counts=camera.status(10.3)['pairing']['recent_counts']
        self.assertEqual(counts,{'no_webcam_sample':1,'no_face_in_paired_frame':1,'timestamp_gap':1})
        self.assertAlmostEqual(camera.status(10.3)['pairing']['last']['skew_ms'],-300)

    def test_pose_identity_and_translation_features(self):
        points=[SimpleNamespace(x=.5,y=.4) for _ in range(478)]
        for i,x in [(33,.4),(263,.6),(234,.35),(454,.65)]:points[i].x=x
        result=pose_from_landmarks(points,np.eye(4))
        self.assertTrue(np.allclose(result['features'],BASE))
        self.assertIsNone(pose_from_landmarks(points,np.full((4,4),np.nan)))

    def test_head_turn_and_roll_do_not_look_like_depth_translation(self):
        for aspect in (4/3,16/9):
            for yaw,roll,distance in ((0,0,1),(.45,0,1),(-.45,.35,1),(.3,-.4,1.3)):
                cy,sy=np.cos(yaw),np.sin(yaw);cz,sz=np.cos(roll),np.sin(roll)
                rotation=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])@np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
                matrix=np.eye(4);matrix[:3,:3]=rotation
                points=[SimpleNamespace(x=.5,y=.4) for _ in range(478)]
                delta=.3/distance*rotation[:2,0]*[1,aspect]
                for index,sign in ((234,-1),(454,1)):
                    points[index]=SimpleNamespace(x=.5+sign*delta[0]/2,y=.4+sign*delta[1]/2)
                packet=pose_from_landmarks(points,matrix,aspect)
                self.assertAlmostEqual(np.exp(packet['features'][5]),.3/distance)
                self.assertTrue(np.allclose(packet['features'][3:5],[.5,.4]))
                self.assertEqual(packet['feature_schema'],'rotation_corrected_face_scale_v1')

    def test_webcam_eye_rays_follow_irises_and_hide_closed_eyes(self):
        points=[SimpleNamespace(x=.5,y=.4) for _ in range(478)]
        for i,x,y in [(234,.3,.4),(454,.7,.4),(33,.35,.4),(133,.45,.4),
                      (362,.55,.4),(263,.65,.4),(159,.4,.38),(145,.4,.42),
                      (386,.6,.38),(374,.6,.42),(468,.4,.4),(473,.6,.4)]:
            points[i]=SimpleNamespace(x=x,y=y)
        rays=pose_from_landmarks(points,np.eye(4))['eye_rays']
        self.assertTrue(np.allclose(rays,[[0,0,-1],[0,0,-1]]))
        points[468].x+=.015
        rays=pose_from_landmarks(points,np.eye(4))['eye_rays']
        self.assertLess(rays[0][0],0)
        self.assertTrue(np.allclose(rays[1],[0,0,-1]))
        for dy in [-.015, .015]:
            points[468].y = points[473].y = .4 + dy
            rays=pose_from_landmarks(points,np.eye(4))['eye_rays']
            for ray in rays:
                self.assertLess(ray[1]*dy, 0, 'Image-up iris movement must give a scene-up local ray')
        points[159].y=points[145].y
        self.assertIsNone(pose_from_landmarks(points,np.eye(4))['eye_rays'][0])

    def test_learned_head_correction_recovers_unseen_eye_targets(self):
        poses=np.array([pose(t) for t in np.linspace(0,8,180)])
        eyes=np.array([pupil((.5,.5),h) for h in poses])
        model=HeadCompensation();model.fit(eyes,poses)
        for t in np.linspace(.1,7.9,20):
            h=pose(t)
            a=model.correct(pupil((.8,.2),h),h)
            b=model.correct(pupil((.8,.2),BASE),BASE)
            self.assertLess(np.linalg.norm(a-b),.002)
        self.assertIsNone(model.correct(eyes[0],BASE+[.8,0,0,0,0,0]))

    def test_unvaried_or_inconsistent_head_calibration_rejected(self):
        model=HeadCompensation()
        poses=np.tile(BASE,(80,1))
        with self.assertRaises(ValueError):model.fit(np.random.default_rng(1).random((80,2)),poses)
        poses=np.array([pose(t) for t in np.linspace(0,8,180)])
        with self.assertRaises(ValueError):model.fit(np.tile([.5,.5],(180,1)),poses)
        with self.assertRaises(ValueError):model.fit(np.random.default_rng(2).random((180,2)),poses)

    def test_diagonal_alone_is_not_a_full_head_cone(self):
        poses=np.tile(BASE,(120,1))
        poses[:,0]=np.linspace(-.15,.15,120)
        poses[:,1]=poses[:,0]*.7
        eyes=np.array([pupil((.5,.5),h) for h in poses])
        model=HeadCompensation()
        with self.assertRaises(ValueError):model.fit_cone(eyes,poses)
        self.assertIsNone(model.reference)

    def test_five_point_mapping_preserves_center_corners_and_continuity(self):
        points=np.array(TARGETS)*[.18,.14]+[.38,.35]
        points[0]+=[.008,-.005]  # Nonlinear center offset remains represented.
        mapping=FivePointMap(points)
        for source,target in zip(points,TARGETS):self.assertTrue(np.allclose(mapping.project(source),target))
        midpoint=(points[0]+points[2])/2
        self.assertLess(np.linalg.norm(np.array(mapping.project(midpoint+[1e-6,0]))-mapping.project(midpoint-[1e-6,0])),.001)
        self.assertIsNone(mapping.project([9,9]))
        points[0]=[0,0]
        with self.assertRaises(ValueError):FivePointMap(points)


class FakeHead:
    epoch=1
    visible=True
    def status(self,now=None):
        return {'face_visible':self.visible,'connected':self.visible,'epoch':self.epoch,'error':None,'fps':30,'name':'test webcam'}


class HybridFlowTests(unittest.TestCase):
    def setUp(self):
        self.now=100.
        clock=patch('monitor_demo.time.monotonic',side_effect=lambda:self.now);clock.start();self.addCleanup(clock.stop)
        self.head=FakeHead()
        self.c=Calibration('USB Camera')
        self.flow=HybridOnboarding(self.c,self.head,clock=lambda:self.now)
        self.c.onboarding=self.flow;self.c.head_camera=self.head
        self.flow.configure([{'id':'laptop','viewport':[-1440,100,1440,900]}])
        self.last_result=None

    def feed(self,target=(.5,.5),head=None,confidence=.9):
        self.now+=1/30
        head=BASE if head is None else head
        eye=pupil(target,head)
        result={'confidence':confidence,'pupil_ellipse':{'center':(eye*[640,480]).tolist()},
                'gaze_direction':[0,0,1],'capture_time':self.now,
                'head_pose':{'time':self.now-.015,'features':head.tolist(),'epoch':self.head.epoch}}
        self.last_result=result
        self.c.add_frame(result)

    def start_head(self):
        for _ in range(30):self.feed()
        self.assertEqual(self.flow.phase,'head')
        self.now+=.6

    def test_countdown_follows_real_deadlines_and_stops_when_inactive(self):
        self.assertIsNone(self.flow.state()['remaining_seconds'])
        self.start_head()
        state=self.flow.state()
        self.assertAlmostEqual(state['step_remaining_seconds'],30-(self.now-self.flow.head_started))
        self.assertAlmostEqual(state['remaining_seconds'],60-(self.now-self.flow.started_at))
        # A late head step cannot promise more time than the overall deadline.
        self.flow.started_at=self.now-55
        self.assertAlmostEqual(self.flow.state()['step_remaining_seconds'],5)
        self.now+=5.1
        state=self.flow.state()
        self.assertEqual(state['phase'],'paused')
        self.assertEqual(state['stopped_stage'],'head')
        self.assertIsNone(state['remaining_seconds'])
        self.assertIsNone(state['step_remaining_seconds'])
        self.flow.arm()
        self.assertIsNone(self.flow.state()['remaining_seconds'])

    def finish(self):
        self.start_head()
        for i in range(450):
            self.feed()
            if self.flow.phase=='screen':break
        self.assertEqual(self.flow.phase,'screen',self.flow.message)
        self.finish_circle()

    def finish_circle(self):
        started=self.flow.screen_circle.started_at
        for _ in range(400):
            if self.flow.phase!='screen':break
            self.feed(circular_target(self.now+1/30-started-.1))
        self.assertEqual(self.flow.phase,'verify',self.flow.message)
        self.assertLessEqual(self.now-started,FIRST_PAIR_SECONDS+4)
        self.finish_accuracy()

    def finish_accuracy(self):
        mapping=self.flow.mapping
        for _ in range(300):
            if self.flow.phase!='verify':break
            self.feed(self.flow.accuracy_check.target)
        self.assertEqual(self.flow.phase,'complete',self.flow.message)
        self.assertEqual(self.flow.accuracy_check.status,'complete')
        self.assertIs(self.flow.mapping,mapping)

    def test_accuracy_timeout_without_camera_frames_keeps_the_mapping(self):
        self.finish()
        mapping=self.flow.mapping
        self.flow.start_accuracy_check()
        for _ in range(5):
            self.now+=8.1
            self.flow.state()
        self.assertEqual(self.flow.phase,'complete')
        self.assertEqual(self.flow.accuracy_check.status,'incomplete')
        self.assertEqual(len(self.flow.accuracy_check.rows),5)
        self.assertIs(self.flow.mapping,mapping)

    def test_accuracy_stop_keeps_map_and_retest_uses_fresh_samples(self):
        self.finish()
        mapping=self.flow.mapping
        self.flow.start_accuracy_check()
        self.assertFalse(self.flow.has_screen_mapping, 'Hide cursor feedback during independent checks')
        self.flow.stop_step()
        self.assertEqual(self.flow.accuracy_check.status,'incomplete')
        self.assertIs(self.flow.mapping,mapping)
        self.flow.start_accuracy_check()
        self.assertEqual(self.flow.accuracy_check.rows,[])
        self.finish_accuracy()

    def test_single_flow_finishes_and_head_turn_keeps_cursor_at_gaze_target(self):
        self.finish()
        self.assertLess(self.now-100,20)
        # Screen feedback intentionally settles after a newly confirmed fixation.
        for _ in range(20):
            self.feed((.75,.25))
        # Short calibration supports the observed range, not an unmeasured full turn.
        for _,_,head in self.flow.pairs[::max(1,len(self.flow.pairs)//12)]:
            self.feed((.75,.25),head+np.array([.001,0,0,0,0,0]))
            state=self.c.state()
            self.assertTrue(state['display_valid'])
            self.assertLess(np.linalg.norm(np.array(state['desktop_gaze'])-[-360,325]),30)
        self.assertEqual(self.c.eye_model.phase,'collecting')
        self.assertGreater(len(self.c.eye_model.pupils),30)

    def test_stop_screen_hides_target_and_does_not_advance_until_retry(self):
        self.start_head()
        while self.flow.phase=='head':self.feed()
        head_fit=self.flow.head_fit
        center=list(self.flow.fixations)
        circle=self.flow.screen_circle
        self.flow.stop_step()
        for _ in range(600):self.feed()
        state=self.flow.state()
        self.assertEqual(state['phase'],'paused')
        self.assertEqual(state['stopped_stage'],'screen')
        self.assertIsNone(state['target'])
        self.assertFalse(state['sample_accepted'])
        self.assertEqual(len(circle.samples),0)
        self.assertIs(self.flow.head_fit,head_fit)
        self.assertEqual(self.flow.fixations,center)
        self.flow.retry_step()
        self.assertIs(self.flow.head_fit,head_fit)
        self.assertEqual(self.flow.fixations,center)
        self.finish_circle()

    def test_stop_waiting_or_head_cannot_auto_resume_even_after_reconnect(self):
        for phase in ('waiting','head'):
            self.flow.arm()
            if phase=='head':self.start_head()
            self.flow.stop_step()
            for _ in range(100):self.feed()
            self.assertEqual(self.flow.phase,'paused')
            self.assertEqual(self.flow.stopped_stage,'head')
            self.head.epoch+=1
            self.feed()
            self.assertEqual(self.flow.phase,'paused')
            self.assertEqual(self.flow.stopped_stage,'head')
            self.flow.retry_step()
            self.assertEqual(self.flow.phase,'head')

    def test_late_stop_cannot_discard_a_just_completed_map(self):
        self.finish()
        mapping=self.flow.mapping
        self.flow.stop_step()
        self.assertEqual(self.flow.phase,'complete')
        self.assertIs(self.flow.mapping,mapping)

    def test_retry_timed_out_head_keeps_eye_model_and_can_finish(self):
        self.start_head()
        model=self.c.eye_model
        for _ in range(20):self.feed()
        self.now+=31
        self.assertEqual(self.flow.state()['phase'],'paused')
        self.now+=300  # Time spent paused must not consume the new attempt.
        self.flow.retry_step()
        self.assertIs(self.c.eye_model,model)
        self.assertEqual(self.flow.phase,'head')
        self.assertEqual(self.flow.pairs,[])
        self.assertEqual(self.flow.state()['step_remaining_seconds'],30)
        for i in range(450):
            self.feed()
            if self.flow.phase=='screen':break
        self.assertEqual(self.flow.phase,'screen',self.flow.message)
        self.finish_circle()
        self.assertTrue(self.c.state()['calibrated'])

    def test_retry_circle_keeps_head_fit_and_center(self):
        self.finish()
        self.flow.phase='paused';self.flow.stopped_stage='screen';self.flow.mapping=None
        self.flow.retry_step()
        previous=list(self.flow.fixations)
        head_fit=self.flow.head_fit
        self.now+=1
        self.flow.retry_step()
        self.assertIs(self.flow.head_fit,head_fit)
        self.assertEqual(self.flow.index,1)
        self.assertEqual(self.flow.fixations,previous)
        self.assertLess(self.flow.state()['remaining_seconds'],9)
        self.finish_circle()

    def test_repeated_rejection_cannot_confirm_an_unsettled_corner(self):
        self.start_head()
        while self.flow.phase=='head':self.feed()
        for i in range(300):
            if self.flow.phase!='screen':break
            self.feed(self.flow.screen_circle.target(self.now+1/30),confidence=.1 if i%4==0 else .9)
        self.assertEqual(self.flow.phase,'paused')
        self.assertIsNone(self.flow.mapping)
        self.flow.retry_step()
        self.finish_circle()

    def test_inconsistent_short_pass_stops_and_retries_only_the_four_dots(self):
        self.start_head()
        while self.flow.phase=='head':self.feed()
        for _ in range(270):self.feed()  # Never followed the corner targets.
        state=self.flow.state()
        self.assertEqual(state['phase'],'paused')
        self.assertEqual(state['stopped_stage'],'screen')
        self.assertFalse(state['cursor_calibration']['active'])
        self.assertFalse(self.flow.has_screen_mapping)
        self.assertIn('too similar',state['blocker'])
        self.assertIsNotNone(self.flow.head_fit.reference)
        self.flow.retry_step()
        self.assertEqual(self.flow.phase,'screen')
        self.assertEqual(len(self.flow.screen_circle.samples),0)
        self.finish_circle()
        self.assertFalse(self.flow.cursor_calibration.active)

    def test_camera_epoch_change_at_circle_deadline_cannot_commit_old_samples(self):
        self.finish()
        self.flow.phase='screen';self.flow.mapping=None
        self.head.epoch+=1
        self.assertEqual(self.flow.state()['phase'],'waiting')
        self.assertIsNone(self.flow.mapping)
        self.assertIsNone(self.flow.screen_circle)

    def test_failed_map_retries_circle_and_camera_change_discards_old_fit(self):
        self.finish()
        center=self.flow.fixations[0]
        head_fit=self.flow.head_fit
        self.flow.phase='paused';self.flow.stopped_stage='screen';self.flow.mapping=None
        self.flow.retry_step()
        self.assertEqual(self.flow.index,1)
        self.assertEqual(self.flow.fixations,[center])
        self.assertIs(self.flow.head_fit,head_fit)
        self.head.epoch+=1
        self.flow.retry_step()
        self.assertEqual(self.flow.phase,'waiting')
        self.assertIsNone(self.flow.head_fit.reference)

    def test_retry_center_restarts_only_its_capture(self):
        self.start_head()
        for _ in range(10):self.feed()
        self.assertGreater(len(self.flow.pairs),0)
        self.flow.retry_step()
        self.assertEqual(self.flow.phase,'head')
        self.assertEqual(self.flow.pairs,[])
        self.assertEqual(self.flow.state()['elapsed'],0)
        self.assertIsNone(self.flow.head_cue)

    def test_fixed_target_head_calibration_preserves_map_until_fresh_check_and_resumes(self):
        from test_geometric_gaze import physical_eye,moving_head
        with patch(__name__+'.pupil',side_effect=physical_eye):
            self.finish();original=self.flow.mapping
            self.flow.start_head_refinement()
            started=self.now
            self.assertEqual(self.flow.cursor_calibration.fixed_target,[.5,.5])
            for _ in range(100):
                self.feed(head=moving_head(self.now-started));self.flow.cursor_sample([.9,.1])
            practice=self.flow.head_refinement
            count=len(practice.samples)
            self.assertGreater(count,30)
            self.assertFalse(practice.done)
            self.assertEqual(sum(r['source']=='geometry-training' for r in self.flow.state()['calibration_rays']),count,
                             'Accepted head calibration measurements must appear while collecting, not only after a successful fit')
            self.assertIs(self.flow.mapping,original)
            self.flow.finish_cursor_calibration();self.now+=30
            self.assertEqual(len(practice.samples),count)
            self.flow.start_head_refinement()
            self.assertIs(self.flow.head_refinement,practice)
            for _ in range(450):
                self.feed(head=moving_head(self.now-started));self.flow.cursor_sample([.1,.9])
                if practice.done:break
                self.assertIs(self.flow.mapping,original)
            self.assertTrue(practice.applied,practice.message)
            self.assertFalse(self.flow.cursor_calibration.active)
            self.assertEqual(self.flow.state()['head_correction_status'],'geometric')
            self.assertIsNotNone(self.flow.state()['geometry_model'])
            self.assertTrue(any(r['source']=='geometry-check' for r in self.flow.calibration_rays))
            for t in (1.,2.,3.):
                self.feed([.7,.3],moving_head(t))
                uv=self.flow.estimate_uv(self.flow.feature(self.last_result))
                self.assertTrue(np.allclose(uv,[.7,.3],atol=.03),uv)

    def test_manual_cursor_map_can_learn_both_turns_and_translations_without_guided_dots(self):
        from test_geometric_gaze import physical_eye,BASE as PHYSICAL_BASE
        from test_cursor_calibration import TARGETS as MOUSE_TARGETS
        with patch(__name__+'.pupil',side_effect=physical_eye):
            self.flow.start_cursor_calibration()
            for target in MOUSE_TARGETS:
                for _ in range(95):
                    self.feed(target,PHYSICAL_BASE);self.flow.cursor_sample(target.tolist())
            self.flow.finish_cursor_calibration()
            self.assertEqual(self.flow.phase,'complete')
            self.assertFalse(any(r['source']=='onboarding' for r in self.flow.calibration_rays))
            self.assertGreaterEqual(len(self.flow.geometry_seeds()),5)
            self.flow.start_head_refinement();start=self.now
            for _ in range(470):
                t=self.now-start
                head=PHYSICAL_BASE.copy()
                if t<5 or 10<=t<12.5:head[0]+=.14*np.sin(t*3.)
                else:head[3]+=.024*np.sin(t*3.)
                self.feed(head=head);self.flow.cursor_sample([.5,.5])
                if self.flow.head_refinement.done:break
            run=self.flow.head_refinement
            self.assertTrue(run.applied,run.message)
            self.assertTrue(all(run.checked_motion.values()),run.state(self.now))
            for delta in ([.10,0,0,0,0,0],[0,0,0,.018,0,0],[.08,0,0,-.012,0,0]):
                head=PHYSICAL_BASE+delta
                self.feed([.65,.4],head)
                uv=self.flow.estimate_uv(self.flow.feature(self.last_result))
                self.assertTrue(np.allclose(uv,[.65,.4],atol=.035),uv)

    def test_fixed_target_requires_working_map_and_failed_capture_keeps_previous_fit(self):
        with self.assertRaises(ValueError):self.flow.start_head_refinement()
        self.finish();previous=self.flow.mapping
        self.flow.start_head_refinement()
        for _ in range(500):
            self.feed(confidence=.1);self.flow.cursor_sample([.5,.5])
        self.assertTrue(self.flow.head_refinement.done)
        self.assertFalse(self.flow.head_refinement.applied)
        self.assertFalse(self.flow.cursor_calibration.active)
        self.assertIs(self.flow.mapping,previous)
        self.assertTrue(self.flow.has_screen_mapping)

    def cursor_center(self):
        for i in range(60):
            if self.flow.cursor_calibration.stage=='positions':break
            self.feed();self.flow.cursor_sample([.5,.5])
        self.assertEqual(self.flow.cursor_calibration.stage,'positions',self.flow.cursor_calibration.message)
        self.assertEqual(self.flow.cursor_head_fit.mode,'steady')

    def test_cursor_alignment_keeps_old_map_until_explicit_finish(self):
        from test_cursor_calibration import TARGETS as MOUSE_TARGETS
        self.finish()
        previous=self.flow.mapping
        self.flow.start_cursor_calibration()
        self.cursor_center()
        for target in MOUSE_TARGETS:
            for _ in range(40):
                self.feed(target)
                self.flow.cursor_sample(target.tolist())
        self.assertIs(self.flow.mapping,previous)
        self.assertIsNotNone(self.flow.cursor_calibration.candidate,self.flow.cursor_calibration.message)
        self.flow.finish_cursor_calibration()
        self.assertIsNot(self.flow.mapping,previous)
        self.assertEqual(self.flow.phase,'complete')

    def test_incomplete_cursor_alignment_preserves_previous_calibration(self):
        self.finish()
        previous=self.flow.mapping
        self.flow.start_cursor_calibration()
        self.flow.finish_cursor_calibration()
        self.assertIs(self.flow.mapping,previous)
        self.assertEqual(self.flow.phase,'complete')

    def test_live_cursor_offset_is_used_before_finish_and_survives_head_motion(self):
        self.finish()
        old=self.flow.mapping
        self.flow.start_cursor_calibration();self.cursor_center()
        # The wearer fixates a target whose old mapping has a small offset.
        for _ in range(40):
            self.feed((.54,.47));self.flow.cursor_sample([.5,.5])
        self.assertEqual(len(self.flow.cursor_calibration.points),1)
        self.assertIs(self.flow.mapping,old)
        self.assertTrue(self.flow.cursor_calibration.state()['live_preview'])
        display=self.flow.displays[0]['viewport']
        expected=np.array(display[:2])+np.array([.5,.5])*display[2:]
        for t in (1.,3.,5.):
            self.feed((.54,.47),BASE+np.array([.001*t,0,0,0,0,0]))
            self.assertTrue(np.allclose(self.c.state()['desktop_gaze'],expected,atol=20))
        self.flow.finish_cursor_calibration()
        self.assertIsNot(self.flow.mapping,old)

    def test_cursor_learning_adds_a_new_head_pose_and_retains_it_after_finish(self):
        self.finish()
        turned=BASE+np.array([.17,0,0,0,0,0])
        self.feed([.5,.5],turned)
        self.assertIsNone(self.flow.desktop_point(self.flow.feature(self.last_result)))
        self.flow.start_cursor_calibration()
        for _ in range(50):
            self.feed([.5,.5],turned);self.flow.cursor_sample([.5,.5])
        self.assertEqual(self.flow.cursor_calibration.state()['saved_anchors'],1)
        expected=np.array([-720,550])
        self.assertTrue(np.allclose(self.flow.desktop_point(self.flow.feature(self.last_result)),expected))
        self.flow.finish_cursor_calibration()
        self.assertTrue(np.allclose(self.flow.desktop_point(self.flow.feature(self.last_result)),expected))
        self.flow.start_cursor_calibration()
        self.assertEqual(len(self.flow.cursor_calibration.pose_points),1)
        self.flow.finish_cursor_calibration()

    def test_offscreen_estimate_fences_desktop_but_keeps_raw_ray_and_lost_face_invalid(self):
        self.finish()
        self.feed([1.3,-.2])
        feature=self.flow.feature(self.last_result)
        self.assertTrue(np.allclose(self.flow.estimate_uv(feature),[1.3,-.2]))
        x,y,w,h=self.flow.displays[0]['viewport']
        self.assertTrue(np.allclose(self.flow.desktop_point(feature),[x+w-8,y+8]))
        self.assertIsNone(self.flow.desktop_point(None))

    def test_external_screen_uses_laptop_map_and_topology_changes_preserve_calibration(self):
        self.finish()
        mapping = self.flow.mapping
        laptop = self.flow.displays[0]
        self.flow.configure([laptop, {'id':'external','viewport':[0,100,1920,1080]}])
        self.assertIs(self.flow.mapping,mapping)
        self.assertEqual(self.flow.phase,'complete')
        self.feed([1.3,.5])
        self.assertTrue(np.allclose(self.flow.desktop_point(self.flow.feature(self.last_result)),[432,550]))
        self.flow.configure([laptop])
        self.assertIs(self.flow.mapping,mapping)
        self.assertTrue(np.allclose(self.flow.desktop_point(self.flow.feature(self.last_result)),[-8,550]))

    def test_saved_cursor_reference_retains_capture_pose_target_and_original_prediction(self):
        self.finish()
        initial=len(self.flow.calibration_rays)
        self.flow.start_cursor_calibration()
        for _ in range(55):
            self.feed([.55,.5]);self.flow.cursor_sample([.5,.5])
        captured=self.flow.calibration_rays[initial:]
        self.assertGreaterEqual(len(captured),6)
        self.assertEqual(len({p['captured_at'] for p in captured}),len(captured))
        self.assertEqual(len({p['fixation_id'] for p in captured}),1)
        self.assertIsNotNone(captured[0]['fixation_id'])
        saved=dict(self.flow.calibration_rays[-1])
        self.assertEqual(saved['source'],'cursor')
        self.assertTrue(np.allclose(saved['head'],BASE))
        self.assertTrue(np.allclose(saved['predicted_before'],[.55,.5]))
        self.flow.finish_cursor_calibration()
        self.feed([.2,.8],pose(2))
        self.assertEqual(self.flow.state()['calibration_rays'][-1],saved)

    def test_each_accepted_onboarding_frame_is_retained_and_journaled_across_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            self.flow.diagnostic_path=Path(folder)/'head.json'
            self.flow.arm()
            self.finish()
            samples=self.flow.calibration_rays
            self.assertGreater(len(samples),80, 'Do not discard all but the last 80 observations')
            self.assertEqual([s['id'] for s in samples],list(range(1,len(samples)+1)))
            self.assertEqual(len(samples),len(self.flow.screen_circle.samples)+len(self.flow.fixations[0]))
            for target in TARGETS:
                self.assertGreaterEqual(sum(np.allclose(s['target'],target) for s in samples),6)
            journal=self.flow.reference_log
            self.assertEqual([json.loads(line) for line in journal.read_text().splitlines()],samples)
            old_session=self.flow.state()['calibration_session_id']
            old_contents=journal.read_text()
            self.flow.arm()
            self.assertNotEqual(self.flow.state()['calibration_session_id'],old_session)
            self.assertEqual(journal.read_text(),old_contents)
            self.assertEqual(self.flow.calibration_rays,[])

    def test_same_mouse_target_at_new_head_origin_rearms_and_saves_every_frame(self):
        self.finish()
        self.flow.start_cursor_calibration()
        target=[.5,.5]
        initial=len(self.flow.calibration_rays)
        for _ in range(55):
            self.feed(target);self.flow.cursor_sample(target)
        session=self.flow.cursor_calibration
        self.assertEqual(session.saved_count,1)
        first=list(self.flow.calibration_rays[initial:])
        moved=BASE+np.array([.07,-.02,.01,.04,.02,-.05])
        self.feed(target,moved);self.flow.cursor_sample(target)
        self.assertFalse(session.target_complete)
        for _ in range(55):
            self.feed(target,moved);self.flow.cursor_sample(target)
        second=self.flow.calibration_rays[initial+len(first):]
        self.assertEqual(session.saved_count,2)
        self.assertGreaterEqual(len(second),6)
        self.assertNotEqual(first[0]['fixation_id'],second[0]['fixation_id'])
        self.assertTrue(all(np.allclose(s['head'],moved) and np.allclose(s['target'],target) for s in second))
        self.assertEqual(self.flow.calibration_rays[initial:initial+len(first)],first)
        for _ in range(55):
            self.feed(target,moved);self.flow.cursor_sample(target)
        self.assertEqual(session.saved_count,2, 'No repeated self-training at the unchanged pose')
        self.flow.finish_cursor_calibration()
        self.assertTrue(np.allclose(self.flow.estimate_uv(self.flow.feature(self.last_result)),target))
        self.feed(target)
        self.assertTrue(np.allclose(self.flow.estimate_uv(self.flow.feature(self.last_result)),target))

    def test_preview_alignment_keeps_target_fixed_and_learns_distinct_head_poses(self):
        self.finish()
        target=[.15,.25]
        self.flow.start_preview_alignment(target)
        for _ in range(60):
            self.feed(target);self.flow.cursor_sample([.9,.8])
        session=self.flow.cursor_calibration
        self.assertEqual(session.state()['fixed_target'],target)
        self.assertEqual(session.saved_count,1)
        for _ in range(60):
            self.feed(target);self.flow.cursor_sample([.1,.9])
        self.assertEqual(session.saved_count,1, 'Stationary pose must not repeatedly train itself')
        turned=BASE+np.array([.17,0,0,0,0,0])
        for _ in range(65):
            self.feed(target,turned);self.flow.cursor_sample([.9,.8])
        self.assertEqual(session.saved_count,2)
        self.assertEqual(len(session.pose_points),2)
        self.assertTrue(all(np.allclose(p[2],target) for p in session.pose_points))
        self.flow.finish_cursor_calibration()
        viewport=self.flow.displays[0]['viewport']
        expected=np.array(viewport[:2])+np.array(target)*viewport[2:]
        self.assertTrue(np.allclose(self.flow.desktop_point(self.flow.feature(self.last_result)),expected))
        self.assertFalse(session.active)

    def test_preview_alignment_requires_a_screen_map_and_valid_target(self):
        with self.assertRaises(ValueError):self.flow.start_preview_alignment([.2,.3])
        self.finish()
        for target in (None,[1.1,.2],[float('nan'),.3],[True,.2]):
            with self.assertRaises(ValueError):self.flow.start_preview_alignment(target)
        self.assertFalse(self.flow.cursor_calibration.active)

    def test_moving_mouse_restarts_the_head_fixation_sweep(self):
        self.flow.start_cursor_calibration()
        for i in range(30):
            self.feed(head=pose(i/30));self.flow.cursor_sample([.5,.5])
        self.flow.cursor_sample([.8,.2])
        self.assertLessEqual(len(self.flow.cursor_reference),1)
        self.assertEqual(self.flow.cursor_calibration.stage,'center')

    def test_cursor_alignment_establishes_a_steady_reference_and_previews_before_finish(self):
        from test_cursor_calibration import TARGETS as MOUSE_TARGETS
        self.flow.start_cursor_calibration()
        self.cursor_center()
        for target in MOUSE_TARGETS:
            for _ in range(65):
                self.feed(target)
                self.flow.cursor_sample(target.tolist())
        self.assertEqual(self.flow.cursor_head_fit.mode,'steady')
        self.assertTrue(self.c.state()['calibrated'])
        self.assertTrue(self.flow.cursor_calibration.state()['live_preview'])
        self.assertTrue(self.c.state()['display_valid'])
        self.assertIsNotNone(self.flow.cursor_calibration.candidate,self.flow.cursor_calibration.message)
        self.flow.finish_cursor_calibration()
        self.assertTrue(self.c.state()['calibrated'])

    def test_manual_cursor_button_can_replace_running_or_failed_guided_steps(self):
        from test_cursor_calibration import TARGETS as MOUSE_TARGETS
        for mode in ('fresh','running','failed'):
            self.flow.arm()
            if mode!='fresh':
                self.start_head()
                while self.flow.phase=='head':self.feed()
                if mode=='failed':self.flow.stop_step()
            self.flow.start_cursor_calibration()
            self.assertEqual(self.flow.phase,'cursor')
            if self.flow.cursor_calibration.stage=='center':self.cursor_center()
            for target in MOUSE_TARGETS:
                for _ in range(65):
                    self.feed(target);self.flow.cursor_sample(target.tolist())
            self.assertTrue(self.flow.cursor_calibration.state()['ready'],mode)
            self.flow.finish_cursor_calibration()
            self.assertEqual(self.flow.phase,'complete')
            self.assertTrue(self.c.state()['display_valid'])

    def test_manual_log_records_initial_state_rejections_measurements_and_model(self):
        from test_cursor_calibration import TARGETS as MOUSE_TARGETS
        with tempfile.TemporaryDirectory() as folder:
            self.flow.diagnostic_path=Path(folder)/'head.json';self.flow.arm()
            self.flow.start_cursor_calibration()
            for _ in range(12):
                self.feed(confidence=.1);self.flow.cursor_sample([.5,.5])
            self.cursor_center()
            self.assertEqual(self.flow.cursor_calibration.saved_count,1)
            self.assertTrue(self.flow.cursor_calibration.target_complete)
            for target in MOUSE_TARGETS:
                for _ in range(65):
                    self.feed(target);self.flow.cursor_sample(target.tolist())
            self.flow.finish_cursor_calibration()
            rows=[json.loads(line) for line in self.flow.audit.path.read_text().splitlines()]
            self.assertEqual(rows[0]['event'],'session_started')
            contexts={r['context_id']:r for r in rows if r['event']=='context'}
            for row in rows:
                if 'context_id' in row:self.assertIn(row['context_id'],contexts)
            self.assertTrue(any(r.get('decision')=='below_confidence_threshold' for r in rows))
            measures=[r for r in rows if r['event']=='measurement']
            self.assertEqual(len(measures),len(self.flow.calibration_rays))
            self.assertTrue(all(r['beam']['origin'] is None for r in measures),
                            'An empirical cursor fit must not invent a physical ray')
            final=next(r for r in reversed(rows) if r['event']=='cursor_finished')
            self.assertTrue(final['applied'])
            model=contexts[final['context_id']]['gaze_model']
            self.assertEqual(model['type'],'PoseAnchorMap')
            raw=model['base'];self.assertEqual(raw['type'],'CursorMap')
            prediction=np.r_[MOUSE_TARGETS[0]*[.18,.14]+[.38,.35],1]@np.array(raw['coefficients'])
            self.assertTrue(np.isfinite(prediction).all())
            previous=self.flow.audit.path;contents=previous.read_text()
            self.flow.arm();self.assertEqual(previous.read_text(),contents)

    def test_eye_geometry_collects_and_freezes_alongside_head_calibration(self):
        self.start_head()
        self.assertEqual(self.flow.phase,'head')
        self.assertEqual(self.c.eye_model.phase,'collecting')
        self.assertGreater(len(self.c.eye_model.pupils),0)
        with patch.object(self.c.eye_model,'status',return_value={'can_freeze':True}):
            self.feed()
        self.assertEqual(self.c.eye_model.phase,'ready')
        self.assertEqual(self.flow.phase,'head')
        self.flow.cancel()
        self.assertEqual(self.c.eye_model.phase,'uncalibrated')

    def test_target_feedback_rejects_low_confidence_and_stale_frames(self):
        self.start_head()
        for i in range(20):self.feed(head=pose(i/30))
        self.assertEqual(self.flow.phase,'head')
        self.assertTrue(self.flow.state()['sample_accepted'])
        self.feed(confidence=.1)
        self.assertFalse(self.flow.state()['sample_accepted'])
        self.feed(head=pose(2.2))
        self.assertTrue(self.flow.state()['sample_accepted'])
        self.now+=.2
        self.assertFalse(self.flow.state()['sample_accepted'])

    def test_stationary_center_enables_screen_targets_without_head_gymnastics(self):
        self.start_head()
        for _ in range(90):
            self.feed()
            if self.flow.phase=='screen':break
        self.assertEqual(self.flow.phase,'screen')
        self.assertEqual(self.flow.head_fit.mode,'steady')
        self.assertLess(self.now-self.flow.head_started,3)
        self.assertTrue(np.all(self.flow.head_fit.coefficients==0))
        self.assertEqual(len(self.flow.fixations),1)

    def test_initial_calibration_does_not_accept_a_large_moving_head(self):
        self.start_head()
        for i in range(180):self.feed(head=pose(i/15))
        self.assertEqual(self.flow.phase,'head')
        self.assertIsNone(self.flow.head_fit.reference)

    def test_steady_fallback_rejects_noisy_eye_or_moving_head(self):
        model=HeadCompensation()
        poses=np.tile(BASE,(30,1))
        with self.assertRaises(ValueError):
            model.fit_steady(np.random.default_rng(2).random((30,2)),poses)
        poses[:,1]=np.linspace(-.1,.1,30)
        with self.assertRaises(ValueError):
            model.fit_steady(np.tile([.5,.5],(30,1)),poses)
        self.assertIsNone(model.reference)

    def test_sparse_good_center_samples_can_finish_without_a_full_cone(self):
        self.start_head();self.now+=6
        for _ in range(8):
            self.now+=.2;self.feed()
        self.assertEqual(self.flow.phase,'screen')
        self.assertEqual(self.flow.head_fit.mode,'steady')

    def test_onboarding_starts_with_center_instead_of_circular_sweep(self):
        for _ in range(30):self.feed()
        self.assertEqual(self.flow.phase,'head')
        self.assertEqual(self.flow.state()['target'],[.5,.5])
        self.assertIsNone(self.flow.head_cue)
        self.assertEqual(self.c.eye_model.phase,'collecting')

    def test_camera_space_direction_requires_a_real_fresh_eye_model(self):
        self.feed()
        self.assertIsNone(self.c.state()['eye_direction'])
        self.last_result.update(eye_model_estimated=True,eye_center=[310,240],gaze_direction=[.6,0,.8])
        direction=self.c.state()['eye_direction']
        self.assertAlmostEqual(direction['yaw_degrees'],36.86989765)
        self.assertEqual(direction['pitch_degrees'],0)
        self.assertFalse(direction['model_ready'])
        self.assertEqual(direction['center'], [310,240])
        self.assertEqual(direction['pupil'], self.last_result['pupil_ellipse']['center'])
        self.assertEqual(direction['head_features'], self.last_result['head_pose']['features'])
        self.now+=.6
        self.assertIsNone(self.c.state()['eye_direction'])

    def test_completed_fit_survives_status_gap_and_cursor_returns(self):
        self.finish()
        self.feed((.75,.25),BASE)
        state=self.c.state()
        self.assertTrue(state['desktop_cursor'])
        self.assertEqual(state['cursor_message'],'Holding gaze while a sudden jump is checked')
        mapping=self.flow.mapping
        self.now+=1.2
        state=self.c.state()
        self.assertTrue(state['calibrated'])
        self.assertFalse(state['display_valid'])
        self.assertIn('Waiting for the eye camera',state['cursor_message'])
        self.assertIs(self.flow.mapping,mapping)
        self.feed((.75,.25),BASE)
        self.assertTrue(self.c.state()['display_valid'])
        self.assertEqual(self.c.state()['cursor_message'],'Eye cursor active')
        self.feed((.75,.25),BASE+[.8,0,0,0,0,0])
        self.assertTrue(self.c.state()['calibrated'])
        self.assertIn('outside the calibrated range',self.c.state()['cursor_message'])
        self.flow.cancel()
        self.assertFalse(self.c.state()['calibrated'])
        self.assertIn('Calibration cancelled',self.c.state()['cursor_message'])

    def test_failed_screen_step_reports_actual_stage_and_reason(self):
        self.start_head()
        for i in range(450):
            self.feed()
            if self.flow.phase=='screen':break
        self.assertEqual(self.flow.phase,'screen')
        self.now+=.6
        self.feed(TARGETS[1],BASE+[.8,0,0,0,0,0])
        self.assertEqual(self.flow.state()['blocker'],'Head outside the calibrated range')
        self.assertTrue(self.flow.state()['head_ready'])
        self.assertEqual(self.flow.state()['screen_points'],1)
        self.now=self.flow.started_at+61
        state=self.flow.state()
        self.assertEqual(state['phase'],'paused')
        self.assertIsNone(state['remaining_seconds'])
        self.now+=600
        self.assertEqual(self.flow.state()['phase'],'paused')
        self.assertEqual(state['stopped_stage'],'screen')
        self.assertIn('Too few clear samples',state['blocker'])
        self.assertFalse(state['cursor_calibration']['active'])

    def test_dropout_cannot_erase_the_last_head_fit_failure(self):
        self.start_head()
        for i in range(140):self.feed(head=pose(i/15))
        self.assertIsNotNone(self.flow.last_fit_error)
        fit_error=self.flow.last_fit_error
        self.feed(confidence=.1)
        self.assertEqual(self.flow.blocker,fit_error)
        diagnostics=self.flow.state()['head_diagnostics']
        self.assertEqual(diagnostics['last_sample_rejection'],'low_pupil_confidence')
        self.assertEqual(diagnostics['last_fit_error'],fit_error)
        self.assertGreater(diagnostics['sample_counts']['low_pupil_confidence'],0)
        result=dict(self.last_result,head_pose=None)
        self.c.add_frame(result)
        self.assertEqual(self.flow.state()['head_diagnostics']['last_sample_rejection'],'no_paired_head')
        self.assertEqual(self.flow.blocker,fit_error)

    def test_waiting_does_not_call_low_confidence_a_sync_failure(self):
        self.feed(confidence=.1)
        self.assertIn('IR pupil confidence',self.flow.message)
        self.assertEqual(self.flow.state()['head_diagnostics']['waiting_counts']['low_pupil_confidence'],1)
        self.head.visible=False
        self.feed(confidence=.9)
        self.assertIn('visible face',self.flow.message)

    def test_head_loss_never_falls_back_to_uncompensated_cursor(self):
        self.finish();self.feed()
        self.head.visible=False
        self.assertFalse(self.c.state()['display_valid'])
        self.assertIsNone(self.c.state()['click_event'])
        self.head.visible=True
        self.now+=.4
        self.assertFalse(self.c.state()['display_valid'])
        self.feed()
        self.assertTrue(self.c.state()['display_valid'])

    def test_reconnect_invalidates_fit_and_missing_face_never_starts(self):
        self.head.visible=False
        for _ in range(40):self.feed()
        self.assertEqual(self.flow.phase,'waiting')
        self.head.visible=True
        self.finish()
        self.head.epoch+=1
        self.c.state()
        self.assertEqual(self.flow.phase,'waiting')
        self.assertIsNone(self.flow.mapping)

    def test_stale_mismatched_pose_and_duplicate_samples_cannot_calibrate(self):
        self.feed()
        result=self.last_result.copy()
        result['head_pose']={**result['head_pose'],'time':self.now-.18}
        self.assertIsNone(self.flow.feature(result))
        for _ in range(30):self.feed()
        self.now+=1
        result=self.last_result
        for _ in range(100):self.c.add_frame(result)
        self.assertEqual(len(self.flow.pairs),0)

if __name__=='__main__':unittest.main()
