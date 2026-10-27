"""Independent physical fixtures: rotate the eye against head motion toward B."""
import unittest
import numpy as np
from geometric_gaze import GeometricGazeMap, FixedTargetCalibration, head_rotation, eye_origin, screen_point, motion_coverage
from hybrid_onboarding import HeadCompensation
from quick_calibration import AnchorMap,TARGETS
from cursor_calibration import PoseAnchorMap

BASE=np.array([.06,-.04,.02,.49,.43,np.log(.30)])
ASPECT=1.6
DEPTH=1.4
MATRIX=np.array([[1.7,.23],[-.12,1.45]])
OFFSET=np.array([.10,-.07])


def physical_eye(target,head,eye_side="right"):
    origin=eye_origin(head,DEPTH,BASE[5],ASPECT,eye_side=eye_side)
    local=head_rotation(head).T@(screen_point(target,ASPECT)-origin)
    q=local[:2]/-local[2]
    return np.array([.48,.43])+np.linalg.solve(MATRIX,q-OFFSET)


def moving_head(t):
    return BASE+np.array([.15*np.sin(t*1.5),.09*np.cos(t*1.8),.025*np.sin(t*.7),
                          .023*np.sin(t*1.1),.017*np.cos(t*1.3),.055*np.sin(t*.8)])


def fixture():
    seeds=[(physical_eye(t,BASE),BASE.copy(),t) for t in TARGETS]
    base=AnchorMap([p[0] for p in seeds])
    fit=HeadCompensation();fit.fit_steady([seeds[0][0]]*10,[BASE]*10)
    return base,fit,seeds


class GeometricTests(unittest.TestCase):
    def test_left_eye_geometry_fits_and_projects_from_left_origin(self):
        seeds=[(physical_eye(t,BASE,"left"),BASE.copy(),t) for t in TARGETS]
        base=AnchorMap([p[0] for p in seeds])
        fit=HeadCompensation();fit.fit_steady([seeds[0][0]]*10,[BASE]*10)
        samples=[(t,physical_eye([.5,.5],moving_head(t),"left"),moving_head(t),np.array([.5,.5]))
                 for t in np.arange(0,10,.1)]
        model=GeometricGazeMap.fit(base,fit,seeds,samples,ASPECT,eye_side="left")
        self.assertEqual(model.geometry()['eye_side'],'left')
        for t in (1.,3.,6.):
            head=moving_head(t)
            target=[.25,.7]
            raw=physical_eye(target,head,"left")
            origin,_,uv=model.ray(raw,head)
            right=eye_origin(head,model.depth,model.reference_width,ASPECT)
            np.testing.assert_allclose(right-origin,head_rotation(head)@np.array([6.4/30.2,0,0]))
            np.testing.assert_allclose(uv,target,atol=.025)
        run=FixedTargetCalibration(base,fit,seeds,ASPECT,16/9,0,eye_side="left")
        run.samples=samples
        run.tick(10)
        self.assertEqual(run.candidate.eye_side,'left')

    def test_wide_webcam_geometry_is_learned_instead_of_forced_to_45_degrees(self):
        def measured(target,head):
            origin=eye_origin(head,DEPTH,BASE[5],ASPECT,vertical_fov_degrees=75.)
            local=head_rotation(head).T@(screen_point(target,ASPECT)-origin)
            return np.array([.48,.43])+np.linalg.solve(MATRIX,local[:2]/-local[2]-OFFSET)
        seeds=[(measured(t,BASE),BASE.copy(),t) for t in TARGETS]
        base=AnchorMap([s[0] for s in seeds]);fit=HeadCompensation()
        fit.fit_steady([seeds[0][0]]*10,[BASE]*10)
        samples=[(t,measured([.5,.5],moving_head(t)),moving_head(t),np.array([.5,.5])) for t in np.arange(0,10,.1)]
        model=GeometricGazeMap.fit(base,fit,seeds,samples,ASPECT)
        self.assertEqual(model.vertical_fov_degrees,75.)
        self.assertTrue(model.geometry()['assumed_optics'],'Effective FOV is not measured camera calibration')
        for t in [1.3,3.4,6.7]:
            for target in ([.2,.7],[.8,.3]):
                np.testing.assert_allclose(model.project_raw(measured(target,moving_head(t)),moving_head(t)),target,atol=.025)

    def test_combined_rotation_translation_and_eye_counterrotation_recover_unseen_targets(self):
        base,fit,seeds=fixture()
        samples=[(t,physical_eye([.5,.5],moving_head(t)),moving_head(t),np.array([.5,.5])) for t in np.arange(0,10,.1)]
        model=GeometricGazeMap.fit(base,fit,seeds,samples,ASPECT)
        self.assertAlmostEqual(model.depth,DEPTH,delta=.12)
        for t in np.arange(1,8,.7):
            h=moving_head(t)
            for target in ([.5,.5],[.25,.7],[.8,.3]):
                eye=physical_eye(target,h)
                self.assertTrue(np.allclose(model.project_pose_unbounded(eye,h,False),target,atol=.025))
        # Eye rotation is evidence, not replaced by the known target.
        self.assertGreater(np.linalg.norm(model.project_raw(physical_eye([.5,.5],BASE),moving_head(2))-[.5,.5]),.05)
        far=BASE+[1.,0,0,0,0,0]
        self.assertIsNone(model.project_pose_unbounded(seeds[0][0],far,False))
        self.assertIsNone(model.project_pose_unbounded([np.nan,.4],BASE))
        self.assertIsNone(model.project_pose_unbounded([.4,.4],[0,1]))

    def test_rotation_is_proper_and_translation_changes_origin_without_changing_target(self):
        a=eye_origin(BASE,DEPTH,BASE[5],ASPECT)
        shifted=BASE.copy();shifted[3]+=.05
        b=eye_origin(shifted,DEPTH,BASE[5],ASPECT)
        self.assertLess(b[0],a[0])
        r=head_rotation(moving_head(2))
        self.assertTrue(np.allclose(r.T@r,np.eye(3)))
        self.assertAlmostEqual(np.linalg.det(r),1.)
        head=np.zeros(6);head[0]=.3
        self.assertTrue(np.allclose(head_rotation(head)@[0,0,-1],[-np.sin(.3),0,-np.cos(.3)]))
        head=np.zeros(6);head[1]=-.2
        self.assertTrue(np.allclose(head_rotation(head)@[0,0,-1],[0,np.sin(.2),-np.cos(.2)]))

    def test_existing_head_correction_is_undone_before_geometric_projection(self):
        base,fit,seeds=fixture()
        fit.coefficients[0]=[.02,-.005]
        samples=[(t,physical_eye([.5,.5],moving_head(t)),moving_head(t),np.array([.5,.5])) for t in np.arange(0,10,.1)]
        model=GeometricGazeMap.fit(base,fit,seeds,samples,ASPECT)
        head=moving_head(2);eye=physical_eye([.7,.3],head)
        corrected=fit.correct(eye,head,enforce_bounds=False)
        self.assertTrue(np.allclose(model.project_pose_unbounded(corrected,head),[.7,.3],atol=.025))

    def test_finite_run_uses_later_validation_and_works_in_one_movement_direction(self):
        base,fit,seeds=fixture()
        for one_axis in (False,True):
            run=FixedTargetCalibration(base,fit,seeds,ASPECT,16/9,100.)
            coefficients=None
            for t in np.arange(.1,15.2,.1):
                head=BASE.copy() if one_axis else moving_head(t)
                if one_axis:head[0]+=.15*np.sin(t*1.5)
                run.observe((physical_eye([.5,.5],head),head),100+t,100+t)
                if run.phase=='validate' and coefficients is None:coefficients=run.candidate.coefficients.copy()
            self.assertTrue(run.applied,run.message)
            self.assertEqual(run.phase,'complete')
            self.assertLess(run.validation_error,.025)
            self.assertLess(run.validation_error,run.baseline_error)
            self.assertTrue(np.array_equal(run.result.coefficients,coefficients))
            self.assertTrue(set(p[0] for p in run.samples).isdisjoint(p[0] for p in run.validation))
            # Cursor alignment can still add a pose-dependent correction afterwards.
            head=moving_head(3) if not one_axis else BASE.copy()
            eye=physical_eye([.52,.5],head)
            corrected=PoseAnchorMap(run.result,[(eye,head,np.array([.5,.5]))])
            self.assertTrue(np.allclose(corrected.project_pose_unbounded(eye,head),[.5,.5]))

    def test_separate_rotation_translation_and_fixed_eye_ray_intersections(self):
        base,fit,seeds=fixture()
        samples=[(t,physical_eye([.5,.5],moving_head(t)),moving_head(t),np.array([.5,.5])) for t in np.arange(0,10,.1)]
        model=GeometricGazeMap.fit(base,fit,seeds,samples,ASPECT)
        fixed_eye=physical_eye([.5,.5],BASE)
        reference=model.ray(fixed_eye,BASE)
        for delta in ([.10,0,0,0,0,0],[0,-.07,.02,0,0,0],[0,0,0,.018,0,0],[0,0,0,0,.015,.04]):
            head=BASE+delta
            compensated=physical_eye([.5,.5],head)
            self.assertTrue(np.allclose(model.project_raw(compensated,head),[.5,.5],atol=.025))
            ray=model.ray(fixed_eye,head)
            # A depth/vertical shift may partly follow the current beam, so its
            # screen effect can be smaller than a pure lateral shift.
            self.assertGreater(np.linalg.norm(ray[2]-reference[2]),.001,
                               'An unchanged pupil must not pin gaze while the head moves')
            if not np.any(np.array(delta)[:3]):
                self.assertTrue(np.allclose(ray[1],reference[1]),'Translation must not rotate the beam')
                offset=ray[0]-reference[0]
                plane_shift=offset[:2]-offset[2]*reference[1][:2]/reference[1][2]
                self.assertTrue(np.allclose(ray[2]-reference[2],plane_shift*[1,-ASPECT]))
            else:
                expected=head_rotation(head)@head_rotation(BASE).T@reference[1]
                self.assertTrue(np.allclose(ray[1],expected),'Head and eye rotations must compose in one frame')

    def test_rotation_correlated_position_change_is_not_independent_translation_coverage(self):
        rows=[]
        for t in np.arange(0,10,.1):
            head=BASE.copy();head[0]+=.15*np.sin(t);head[3]+=.03*np.sin(t)
            rows.append((t,[.5,.5],head,[.5,.5]))
        self.assertEqual(motion_coverage(rows),{'rotation':True,'translation':False})
        for t in np.arange(10,20,.1):
            head=BASE.copy();head[3]+=.03*np.sin(t*1.7)
            rows.append((t,[.5,.5],head,[.5,.5]))
        self.assertEqual(motion_coverage(rows),{'rotation':True,'translation':True})

    def test_validation_looking_away_does_not_commit_training_fit(self):
        base,fit,seeds=fixture();run=FixedTargetCalibration(base,fit,seeds,ASPECT,16/9,100.)
        for t in np.arange(.1,15.2,.1):
            h=moving_head(t);target=[.5,.5] if t<10 else [.85,.2]
            run.observe((physical_eye(target,h),h),100+t,100+t)
        self.assertEqual(run.phase,'failed')
        self.assertIsNone(run.result)
        self.assertFalse(run.applied)
        self.assertIs(run.base_mapping,base)

    def test_dropouts_duplicates_and_no_motion_do_not_fake_completion(self):
        base,fit,seeds=fixture()
        run=FixedTargetCalibration(base,fit,seeds,ASPECT,16/9,100.)
        for t in np.arange(.1,16,.1):run.observe((seeds[0][0],BASE),100.1,100+t)
        self.assertEqual(len(run.samples),1)
        self.assertTrue(run.done)
        self.assertFalse(run.applied)
        run=FixedTargetCalibration(base,fit,seeds,ASPECT,16/9,100.)
        for t in np.arange(.1,16,.1):run.observe((seeds[0][0],BASE),100+t,100+t)
        self.assertFalse(run.applied)
        self.assertIn('No clear head movement',run.message)

    def test_pause_preserves_data_and_excludes_elapsed_pause_from_deadline(self):
        base,fit,seeds=fixture();run=FixedTargetCalibration(base,fit,seeds,ASPECT,16/9,100.)
        for t in np.arange(.1,4,.1):run.observe((physical_eye([.5,.5],moving_head(t)),moving_head(t)),100+t,100+t)
        count=len(run.samples);run.pause(104);run.tick(1000)
        self.assertEqual(run.elapsed(1000),4.)
        self.assertEqual(len(run.samples),count)
        run.resume(1000);self.assertEqual(run.elapsed(1001),5.)
