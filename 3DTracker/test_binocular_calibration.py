import unittest
import numpy as np
from binocular_calibration import BinocularCalibration,SteadyReference,fuse_predictions,shared_fixation
from head_motion_map import HeadMotionMap
from quick_calibration import AnchorMap,TARGETS
from geometric_gaze import POSE_SCALE

REF=np.array([.03,-.02,.01,.5,.4,-1.2])

def observation(side,target,stamp,head=REF):
    # Different cameras have different mounting orientation and scale.
    matrix=np.array([[-.12,.02],[.01,.14]]) if side=='left' else np.array([[.16,-.01],[-.02,-.13]])
    eye=np.array([.5,.5])+matrix@(np.asarray(target)-.5)
    return {'identity':(side,0,1),'time':stamp,'eye':eye.tolist(),'head':head.tolist(),'confidence':.9}

class BinocularTests(unittest.TestCase):
    def test_both_eyes_learn_one_pass_and_keep_independent_predictions(self):
        pair=BinocularCalibration();self.addCleanup(pair.close);stamp=0
        windows=[]
        for target in TARGETS:
            start=stamp+.05
            for _ in range(8):
                stamp+=.05
                pair.record({side:observation(side,target,stamp) for side in ('left','right')},target,'onboarding',stamp,1.6,'left')
            windows.append((start,stamp))
        pair.finish_onboarding(windows)
        self.assertEqual(set(pair.maps),{'left','right'})
        for side,target in [('left',[.25,.6]),('right',[.7,.3])]:
            np.testing.assert_allclose(pair.predict(side,observation(side,target,stamp+.1)),target,atol=1e-8)
        # One explicit new fixation corrects the companion too, including its head pose.
        target=np.array([.6,.6]);head=REF.copy();head[0]+=.12
        for i in range(8):
            obs=observation('right',target,stamp+.2+i*.03,head);obs['eye'][0]+=.015
            pair.record({'right':obs},target,'cursor',stamp+.2+i*.03,1.6,'left','manual-1')
        np.testing.assert_allclose(pair.predict('right',obs),target,atol=1e-8)
        changed=observation('right',[.5,.5],stamp+.1);changed['identity']=('new-camera',180,2)
        self.assertIsNone(pair.predict('right',changed))
        self.assertIn('left',pair.maps)

    def test_arbitrary_independent_mount_rotation_scale_and_reflection_learn_from_labels(self):
        pair=BinocularCalibration();self.addCleanup(pair.close);stamp=0.;windows=[]
        transforms={'left':np.array([[-.13,.08],[.06,.17]]),
                    'right':np.array([[.05,-.19],[.12,.04]])}
        offsets={'left':np.array([.58,.35]),'right':np.array([.37,.64])}
        def row(side,target,at):
            return {'identity':(side,180 if side=='left' else 0,1),'time':at,
                    'eye':(offsets[side]+transforms[side]@(np.asarray(target)-.5)).tolist(),
                    'head':REF.tolist(),'confidence':.9}
        for target in TARGETS:
            start=stamp+.05
            for _ in range(10):
                stamp+=.05
                pair.record({side:row(side,target,stamp) for side in transforms},target,'onboarding',stamp,1.6,'left')
            windows.append((start,stamp))
        pair.finish_onboarding(windows)
        for target in ([.23,.71],[.8,.15],[.5,.5]):
            for side in transforms:
                np.testing.assert_allclose(pair.predict(side,row(side,target,stamp+.1)),target,atol=1e-8)

    def test_guided_pass_uses_separate_stable_windows_for_one_set_of_targets(self):
        pair=BinocularCalibration();self.addCleanup(pair.close);windows=[]
        for i,target in enumerate(TARGETS):
            start=i*5.;windows.append((start+1.,start+1.4))
            for side,offset in [('left',1.),('right',2.5)]:
                for j in range(12):
                    stamp=start+offset+j*.04
                    pair.collect_onboarding({side:observation(side,target,stamp)},i,start+.8,stamp)
            # Primary-eye dropout afterwards cannot discard the companion's
            # known-target evidence, and neither eye trains the other's map.
        pair.finish_onboarding(windows)
        self.assertEqual(set(pair.maps),{'left','right'})
        for side in ('left','right'):
            np.testing.assert_allclose(pair.predict(side,observation(side,[.25,.6],30)),[.25,.6],atol=1e-8)

    def test_both_mountings_learn_nods_from_the_same_cursor_blocks(self):
        pair=BinocularCalibration();self.addCleanup(pair.close)
        target=np.array([.5,.5])
        for side in ('left','right'):
            pair.identity(side,(side,0,1))
            pair.maps[side]=AnchorMap([observation(side,t,0)['eye'] for t in TARGETS])
        for index,pitch in enumerate((-.18,-.09,0.,.09,.18,-.12,.12)):
            for j in range(8):
                stamp=index+j*.07;head=REF.copy();head[1]+=pitch+(j-3.5)*.008
                views={}
                for side,gain in (('left',.9),('right',1.2)):
                    # Different image orientation and counter-rotation gain per eye.
                    views[side]=observation(side,target+[0,(head[1]-REF[1])*gain],stamp,head)
                pair.record(views,target,'cursor',stamp,1.6,'left',str(index))
        for side,gain in (('left',.9),('right',1.2)):
            self.assertGreater(pair.maps[side].head_model.rank,0)
            for pitch in (-.06,.06):
                head=REF.copy();head[1]+=pitch;goal=np.array([.7,.3])
                obs=observation(side,goal+[0,pitch*gain],20,head)
                np.testing.assert_allclose(pair.predict(side,obs),goal,atol=.025)

    def test_shared_fixation_keeps_equal_midpoint_when_maps_disagree(self):
        rows={'left':{'uv':[.48,.5],'confidence':.9},'right':{'uv':[.53,.5],'confidence':.5}}
        fused=fuse_predictions(rows,'left')
        self.assertAlmostEqual(fused[0],.505)
        self.assertEqual(shared_fixation(rows)['status'],'binocular')
        np.testing.assert_allclose(fuse_predictions({'right':rows['right']}),[.53,.5])
        rows['right']['uv']=[.8,-1.];rows['right']['confidence']=1.
        for preferred in ('left','right',None):
            np.testing.assert_allclose(fuse_predictions(rows,preferred),[.64,-.25])
        self.assertEqual(shared_fixation(rows)['status'],'disagreement')
        self.assertEqual(rows['right']['uv'],[.8,-1.],'Never overwrite raw evidence with convergence')
        self.assertIsNone(fuse_predictions({}))

    def test_disagreement_is_measured_before_fencing_and_pairing_is_bounded(self):
        rows={'left':{'uv':[2.,.5],'confidence':.9},'right':{'uv':[4.,.5],'confidence':.9}}
        np.testing.assert_allclose(fuse_predictions(rows),[3.,.5])
        rows['left'].update(uv=[.5,.5],captured_at=10.)
        rows['right'].update(uv=[.51,.5],captured_at=10.2)
        self.assertEqual(shared_fixation(rows)['status'],'unsynchronized')
        rows['right']['captured_at']=10.05
        self.assertEqual(shared_fixation(rows)['status'],'binocular')
        rows['right']['uv']=[float('nan'),.5]
        self.assertEqual(shared_fixation(rows)['status'],'monocular')

    def test_pipeline_disagreement_uses_midpoint_not_primary(self):
        from hybrid_onboarding import HybridOnboarding
        from unittest.mock import Mock
        flow=object.__new__(HybridOnboarding)
        flow.displays=[{'viewport':[0,0,1000,600]}]
        raw={'left':{'uv':[.2,.5],'confidence':.9,'desktop':[200,300]},
             'right':{'uv':[.8,.5],'confidence':.95,'desktop':[800,300]}}
        flow.raw_eye_predictions=lambda:raw
        flow.estimate_uv=Mock(return_value=[.2,.5])
        np.testing.assert_allclose(flow.desktop_point([0]*8),[500,300])
        self.assertEqual(flow.eye_predictions(),raw)
        flow.estimate_uv.assert_not_called()
        raw['right']['uv']=[.23,.51]
        shown=flow.eye_predictions()
        self.assertNotEqual(shown['left']['desktop'],shown['right']['desktop'])
        self.assertNotEqual(shown['left']['uv'],shown['right']['uv'])
        self.assertEqual(raw['left']['uv'],[.2,.5])
        self.assertIsNotNone(flow.desktop_point([0]*8))

    def test_display_midpoint_uses_each_eyes_fence_without_mutating_raw_gaze(self):
        from hybrid_onboarding import HybridOnboarding
        flow=object.__new__(HybridOnboarding)
        flow.displays=[{'viewport':[-1000,100,1000,600]}]
        raw={'left':{'uv':[-2.,.2],'confidence':.9,'captured_at':10.},
             'right':{'uv':[.8,1.4],'confidence':.5,'captured_at':10.03}}
        flow.raw_eye_predictions=lambda:raw
        # Left is fenced at (-992,220), right at (-200,692).
        np.testing.assert_allclose(flow.desktop_point(None),[-596,456])
        self.assertEqual(raw['left']['uv'],[-2.,.2])
        self.assertEqual(raw['right']['uv'],[.8,1.4])
        raw['right']['captured_at']=10.2
        self.assertIsNone(flow.desktop_point(None))
        raw.pop('left')
        np.testing.assert_allclose(flow.desktop_point(None),[-200,692])

    def test_explicit_eye_choice_does_not_change_either_map_or_substitute_missing_eye(self):
        from hybrid_onboarding import HybridOnboarding
        from monitor_demo import Calibration
        from unittest.mock import Mock
        flow=object.__new__(HybridOnboarding)
        flow.calibration=Calibration('test')
        flow.displays=[{'viewport':[0,0,1000,600]}]
        raw={'left':{'uv':[.2,.5],'confidence':.9},'right':{'uv':[.8,.5],'confidence':.95}}
        flow.raw_eye_predictions=lambda:raw
        flow.estimate_uv=Mock(return_value=[.1,.1])
        for side,x in [('left',200),('right',800)]:
            flow.calibration.set_gaze_eye_mode(side)
            np.testing.assert_allclose(flow.desktop_point([0]*8),[x,300])
            self.assertEqual(len(flow.eye_predictions()),2)
        del raw['right']
        self.assertIsNone(flow.desktop_point([0]*8))
        flow.estimate_uv.assert_not_called()
        with self.assertRaises(ValueError):flow.calibration.set_gaze_eye_mode('automatic')

    def test_companion_uses_only_final_stable_onboarding_windows(self):
        pair=BinocularCalibration();self.addCleanup(pair.close)
        windows=[]
        for i,target in enumerate(TARGETS):
            # An earlier stable-but-wrong detection was later discarded by the
            # primary eye. It must never shift the companion corner median.
            for j in range(20):
                stamp=i*3+j*.04
                pair.record({side:observation(side,[.5,.5],stamp) for side in ('left','right')},target,'onboarding',stamp,1.6,'left')
            start=i*3+1.5
            for j in range(12):
                stamp=start+j*.04
                pair.record({side:observation(side,target,stamp) for side in ('left','right')},target,'onboarding',stamp,1.6,'left')
            windows.append((start,stamp))
        self.assertEqual(pair.maps,{})
        pair.finish_onboarding(windows)
        for side in ('left','right'):
            for target in TARGETS:
                np.testing.assert_allclose(pair.predict(side,observation(side,target,16)),target,atol=1e-8)
        # Missing an eye's final block cannot be rescued by the discarded frames.
        pair.rows['right']=[r for r in pair.rows['right'] if r[0]<windows[-1][0]]
        pair.finish_onboarding(windows)
        self.assertNotIn('right',pair.maps)

    def test_accuracy_check_scores_the_same_fusion_without_clipping(self):
        from hybrid_onboarding import HybridOnboarding
        from unittest.mock import Mock
        from types import SimpleNamespace
        flow=object.__new__(HybridOnboarding)
        flow.clock=lambda:10.
        flow.calibration=SimpleNamespace(detection_threshold=.5)
        flow.observation_check=lambda result,now:((np.array([.5,.5]),REF,None),'paired')
        flow.head_fit=SimpleNamespace(correct=lambda *args,**kwargs:np.array([.5,.5]))
        flow.mapping=SimpleNamespace(project=lambda p:[.5,.5])
        check=Mock();check.done=False;check.reason='checking';flow.accuracy_check=check
        flow.binocular_estimate=lambda:({'left':{},'right':{}},{'uv':[1.1,.3]})
        flow.update_accuracy_check({'confidence':.9,'capture_time':9.95},10.)
        np.testing.assert_allclose(check.observe.call_args.args[1],[1.1,.3])
        flow.binocular_estimate=lambda:({'left':{},'right':{}},{'uv':None})
        check.observe.reset_mock()
        flow.update_accuracy_check({'confidence':.9,'capture_time':9.98},10.)
        self.assertIsNone(check.observe.call_args.args[1], 'Missing prediction must not reject a known-target fixation')

    def test_laptop_calibration_does_not_extrapolate_onto_another_monitor(self):
        from hybrid_onboarding import HybridOnboarding
        flow=object.__new__(HybridOnboarding)
        flow.displays=[{'viewport':[1000,300,1000,600]},{'viewport':[0,0,1000,900]}]
        flow.raw_eye_predictions=lambda:{}
        flow.estimate_uv=lambda feature:[-.4,-.4]
        self.assertEqual(flow.desktop_point([0]*8),[1008,308])

    def test_head_correction_preserves_eye_motion_and_handles_new_head_poses(self):
        def raw(target,head):
            x=(head-REF)/POSE_SCALE
            displacement=np.array([.012*x[0]+.01*x[3],-.016*x[1]+.008*x[4]+.004*x[5]])
            return np.array([.5,.5])+(np.asarray(target)-.5)*.15+displacement
        seeds=[(raw(t,REF),REF,t) for t in TARGETS]
        base=AnchorMap([s[0] for s in seeds]);samples=[]
        for t in np.arange(0,24,.05):
            head=REF+POSE_SCALE*np.sin(t*np.array([1.1,1.3,.7,1.7,.9,.4]))*.7
            eye=raw([.5,.5],head)
            if 4<t<4.4:eye=eye+[.12,-.09]  # Whole corrupted time block.
            samples.append((t,eye,head,np.array([.5,.5])))
        model=HeadMotionMap.fit(base,SteadyReference(REF),seeds,samples)
        for t in np.arange(24,28,.2):
            head=REF+POSE_SCALE*np.sin(t*np.array([1.1,1.3,.7,1.7,.9,.4]))*.65
            for target in ([.5,.5],[.2,.8],[.8,.2]):
                np.testing.assert_allclose(model.project_raw(raw(target,head),head),target,atol=.025)
        # Repeated center training must not produce a constant center output.
        head=samples[-1][2]
        self.assertGreater(np.linalg.norm(model.project_raw(raw([.8,.2],head),head)-[.5,.5]),.35)
        far=REF+POSE_SCALE*8
        self.assertIsNone(model.project_raw(raw([.5,.5],far),far))
        self.assertIsNone(model.project_pose_unbounded(raw([.5,.5],far),far,False))
