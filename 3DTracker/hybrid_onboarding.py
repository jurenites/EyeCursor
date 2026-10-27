"""One laptop, two cameras: a steady center plus a short screen-anchor pass.

The initial map needs no assumed eye-camera mounting angle or anatomical sphere.
A fixed-target follow-up can fit head-local eye rays and an approximate depth
scale, with a separate fresh-data check. This is not metric triangulation.
"""
from binocular_calibration import BinocularCalibration, shared_fixation
from head_motion_map import HeadMotionMap
from collections import deque, Counter
import math
import json
from pathlib import Path
import time
import uuid
import cv2
import numpy as np
from head_camera import FACE_MAX_SECONDS, PAIR_MAX_SECONDS
from onboarding import validate_displays
from cursor_calibration import CursorCalibration, PoseAnchorMap
from dot_learning import DotLearning
from accuracy_check import AccuracyCheck
from quick_calibration import AnchorMap, QuickCalibration, target_at, DURATION as QUICK_DURATION, STEP as QUICK_STEP, MAX_CORNER_SECONDS
from gaze_mapping import project_unbounded, desktop_fence, fence
from geometric_gaze import GeometricGazeMap, screen_point
from continuous_calibration import ContinuousTargetCalibration, pupil_shape_rejection
from calibration_log import CalibrationLog, model_snapshot

TARGETS = ((.5,.5),(.08,.08),(.92,.08),(.92,.92),(.08,.92))
HEAD_SCALE = np.array([.12,.12,.12,.05,.05,.15])
ORBIT_SECONDS = 2 * math.pi / .75  # One sweep, matching the native 60 Hz animation.
HEAD_MARGIN = np.array([.055,.055,.07,.025,.025,.10])
HEAD_MIN_SAMPLES = 30
HEAD_MIN_SECONDS = 1.5
HEAD_YAW = math.radians(4)
HEAD_PITCH = math.radians(3)
HEAD_STEADY_AFTER = 6.


def head_cone_progress(poses):
    """Coverage while the eyes stay on one fixed target; four corners disambiguate yaw/pitch."""
    poses=np.asarray(poses)
    names=('top-left','top-right','bottom-right','bottom-left')
    if len(poses)<8:return 0.,'cone',[False]*4
    angles=poses[:,:2]
    low,high=np.percentile(angles,[5,95],axis=0)
    span=high-low
    midpoint=(low+high)/2
    delta=angles-midpoint
    # Camera pose: positive yaw turns left; negative pitch raises the chin.
    threshold=np.maximum(span*.2,np.radians([1.5,1.]))
    corners=((1,-1),(-1,-1),(-1,1),(1,1))
    covered=[int(np.sum((delta[:,0]*x>=threshold[0]) & (delta[:,1]*y>=threshold[1])))>=3 for x,y in corners]
    range_score=min(1,span[0]/math.radians(6))*min(1,span[1]/math.radians(4))
    progress=.15*min(1,len(poses)/HEAD_MIN_SAMPLES)+.25*range_score+.6*sum(covered)/4
    ready=range_score>=1 and all(covered) and len(poses)>=HEAD_MIN_SAMPLES
    cue=next((name for name,done in zip(names,covered) if not done),'cone')
    return (1. if ready else min(.95,progress)),cue,covered


class HeadCompensation:
    def __init__(self):
        self.reference = None
        self.coefficients = None
        self.bounds = None
        self.error = None
        self.metrics = {}
        self.mode = None

    def fit(self, eyes, poses):
        eyes, poses = np.asarray(eyes), np.asarray(poses)
        self.metrics = {"samples":len(eyes)}
        if len(eyes) < HEAD_MIN_SAMPLES or eyes.shape != (len(poses),2) or poses.shape[1:] != (6,):
            raise ValueError('Collect more paired eye and head samples')
        if not np.isfinite(eyes).all() or not np.isfinite(poses).all():
            raise ValueError('Invalid camera samples')
        eye_spread=np.ptp(np.percentile(eyes,[5,95],axis=0),axis=0)
        self.metrics['eye_span_px']=(eye_spread*[640,480]).tolist()
        if np.max(eye_spread) < .004:
            raise ValueError('Keep looking at the center while turning your head')
        spread = np.ptp(np.percentile(poses,[5,95],axis=0),axis=0)
        self.metrics['head_span_degrees']=np.degrees(spread[:3]).tolist()
        if spread[0] < HEAD_YAW and spread[1] < HEAD_PITCH:
            raise ValueError('Make a small left/right turn; nodding is optional')
        reference = np.median(poses,axis=0)
        x = (poses-reference)/HEAD_SCALE
        condition=float(np.linalg.cond(np.cov(x[:,:2].T)))
        self.metrics['motion_condition']=condition if math.isfinite(condition) else None
        # Only learn axes that were observed. A missing nod must not create a
        # speculative pitch correction from almost constant samples.
        observed=spread>=np.array([HEAD_YAW,HEAD_PITCH,math.radians(3),.008,.008,.03])
        if observed[0] and observed[1] and condition>20:
            observed[int(spread[0]>=spread[1])]=False
        x[:,~observed]=0
        design = np.column_stack((np.ones(len(x)),x))
        # Independent holdout samples reject an inconsistent head/eye relationship.
        test = np.arange(len(x)) % 4 == 0
        penalty = np.diag([0,.03,.03,.03,.03,.03,.03])
        coefficients = np.linalg.solve(design[~test].T@design[~test]+penalty,
                                       design[~test].T@eyes[~test])
        error = np.linalg.norm(design[test]@coefficients-eyes[test],axis=1)
        self.metrics['holdout_error_p90']=float(np.percentile(error,90))
        self.metrics['holdout_limit']=.012
        if np.percentile(error,90) > .012:
            raise ValueError('Eye/head samples are inconsistent; a steady-head retry is available')
        weights = np.ones(len(x))
        for _ in range(3):
            coefficients = np.linalg.solve(design.T@(weights[:,None]*design)+penalty,
                                           design.T@(weights[:,None]*eyes))
            residual = np.linalg.norm(design@coefficients-eyes,axis=1)
            weights = np.minimum(1,.006/np.maximum(residual,.0001))
        self.metrics['inlier_fraction']=float(np.mean(residual<.012))
        if np.mean(residual < .012) < .85:
            raise ValueError('Head and eye samples did not agree')
        self.reference, self.coefficients = reference, coefficients[1:]
        self.bounds = np.percentile(poses,[2,98],axis=0)
        self.error = float(np.percentile(error,90))
        self.mode='compensated'
        self.metrics['observed_axes']=observed.tolist()
        return eyes-x@self.coefficients

    def fit_cone(self,eyes,poses):
        progress,_,covered=head_cone_progress(poses)
        self.metrics={'samples':len(eyes),'cone_corners':covered,'cone_progress':float(progress),
                      'eye_span_px':(np.ptp(np.percentile(eyes,[5,95],axis=0),axis=0)*[640,480]).tolist()}
        if progress<1:
            raise ValueError('Keep eyes fixed; sweep your face through all four corner directions')
        # A diagonal alone cannot independently identify yaw and pitch.
        angles=np.asarray(poses)[:,:2]
        if np.linalg.cond(np.cov(angles.T))>20:
            raise ValueError('Include both diagonal directions in the head sweep')
        corrected=self.fit(eyes,poses)
        self.metrics['cone_corners']=covered
        return corrected

    def fit_steady(self,eyes,poses):
        """A stable center reference with no claimed head compensation."""
        eyes,poses=np.asarray(eyes),np.asarray(poses)
        if len(eyes)<8 or eyes.shape!=(len(poses),2) or poses.shape[1:]!=(6,):
            raise ValueError('Hold still briefly while watching the center dot')
        if not np.isfinite(eyes).all() or not np.isfinite(poses).all():
            raise ValueError('Waiting for stable eye and head samples')
        spread=np.ptp(np.percentile(poses,[5,95],axis=0),axis=0)
        limit=np.array([math.radians(3),math.radians(3),math.radians(4),.012,.012,.04])
        error=np.linalg.norm(eyes-np.median(eyes,axis=0),axis=1)
        if np.any(spread>limit) or np.percentile(error,90)>.012:
            raise ValueError('Hold your head still and watch the center dot')
        self.reference=np.median(poses,axis=0)
        self.coefficients=np.zeros((6,2))
        self.bounds=np.percentile(poses,[2,98],axis=0)
        self.error=float(np.percentile(error,90))
        self.mode='steady'
        self.metrics={'samples':len(eyes),'mode':'steady','center_error_p90':self.error}
        return eyes

    def correct(self, eye, pose, enforce_bounds=True):
        if self.reference is None:
            return None
        eye, pose = np.asarray(eye),np.asarray(pose)
        if eye.shape != (2,) or pose.shape != (6,) or not np.isfinite(np.r_[eye,pose]).all():
            return None
        if enforce_bounds and np.any((pose < self.bounds[0]-HEAD_MARGIN) | (pose > self.bounds[1]+HEAD_MARGIN)):
            return None
        return eye-(pose-self.reference)/HEAD_SCALE@self.coefficients


class FivePointMap:
    def __init__(self, points):
        points=np.asarray(points,dtype=float)
        if points.shape != (5,2) or not np.isfinite(points).all():
            raise ValueError('Five valid eye positions are required')
        corners=points[1:].astype(np.float32).reshape(-1,1,2)
        if (not cv2.isContourConvex(corners) or cv2.contourArea(corners) < .00004
                or cv2.pointPolygonTest(corners,tuple(points[0]),False) <= 0):
            raise ValueError('Eye positions overlap or do not surround the center')
        self.triangles=[]
        for i in range(4):
            ids=[0,i+1,(i+1)%4+1]
            source=np.vstack((points[ids].T,np.ones(3)))
            if abs(np.linalg.det(source)) < .00001:
                raise ValueError('Eye targets are too close together')
            self.triangles.append((np.linalg.inv(source),np.array(TARGETS)[ids]))

    def project(self, point):
        if point is None or np.shape(point) != (2,) or not np.isfinite(point).all():
            return None
        candidates=[]
        for inverse,destination in self.triangles:
            weights=inverse@[*point,1]
            candidates.append((float(np.min(weights)),weights@destination))
        margin,mapped=max(candidates,key=lambda candidate:candidate[0])
        if margin < -.25 or not np.all((mapped>=0)&(mapped<=1)):
            return None
        return mapped.tolist()


class HybridOnboarding:
    hybrid=True
    TOTAL_SECONDS=60
    HEAD_SECONDS=30
    GUIDED_MOTION_SECONDS=36.
    GUIDED_MOTION_MIN_SECONDS=33.

    def __init__(self,calibration,head_camera,clock=time.monotonic,diagnostic_path=None):
        self.calibration=calibration
        self.head_camera=head_camera
        self.clock=clock
        self.diagnostic_path=Path(diagnostic_path) if diagnostic_path else None
        manifest=Path(__file__).resolve().parents[1]/"version.json"
        self.build_identity=json.loads(manifest.read_text()) if manifest.exists() else {}
        self.displays=[]
        self.source_key=None
        self.arm()

    def configure(self,displays):
        clean=validate_displays(displays)
        if clean!=self.displays:
            # External topology changes do not invalidate the laptop's eye map.
            same_anchor=bool(self.displays and clean[0]['id']==self.displays[0]['id']
                             and clean[0]['viewport'][2:]==self.displays[0]['viewport'][2:])
            self.displays=clean
            if not same_anchor:self.arm()

    def arm(self,start=False):
        if getattr(self,"binocular",None) is not None:self.binocular.close()
        self.binocular=BinocularCalibration()
        if getattr(self,'head_refinement',None) is not None:self.head_refinement.close()
        self.calibration.reset_eye_model()
        # Diagnostic eye geometry learns from the same IR frames in parallel.
        # Screen mapping stays independent of this anatomical approximation.
        if start:self.calibration.eye_model.start()
        self.phase=('waiting' if start else 'idle') if self.displays else 'no_displays'
        self.message=('Put on the glasses and face the laptop webcam.' if start else
                      'Ready. Start calibration when you are prepared.')
        self.visible_since=None
        self.last_seen=None
        self.started_at=None
        self.target_since=None
        self.head_started=None
        self.orbit_samples=0
        self.head_cue=None
        self.feedback_progress=0.
        self.last_advance=None
        self.progress=0.
        self.index=0
        self.fast_path=False
        self.head_fit=HeadCompensation()
        self.mapping=None
        self.epoch=None
        self.pairs=[]
        self.hold=deque(maxlen=90)
        self.fixations=[]
        self.screen_circle=None
        self.center_capture_window=None
        self.accuracy_check=None
        self.dot_learning=None
        self.last_pair_time=None
        self.validation_error=None
        self.sample_accepted=False
        self.feedback_at=None
        self.blocker='Waiting for paired cameras'
        self.stopped_stage=None
        self.sample_counts=Counter()
        self.waiting_counts=Counter()
        self.fit_failures=Counter()
        self.last_fit_error=None
        self.last_sample_rejection=None
        self.report_written=False
        self.cursor_calibration=CursorCalibration()
        self.cursor_reference=[]
        self.cursor_backup=None
        self.head_refinement=None
        self.guided_motion_started=None
        self.guided_motion_outcome=None
        self.calibration_rays=[]
        self.reference_sequence=0
        self.reference_session=uuid.uuid4().hex
        self.reference_log=(self.diagnostic_path.parent/'calibration-sessions'/f'{self.reference_session}.jsonl'
                            if self.diagnostic_path is not None else None)

        self.audit=CalibrationLog(self.reference_log.with_suffix('.events.jsonl') if self.reference_log else None,self.reference_session)
        self.audit.append('session_started',self.clock(),build=self.build_identity,
            coordinate_conventions={'eye':'IR pixels / [640,480]',
                'head':['yaw_rad','pitch_rad','roll_rad','webcam_eye_midpoint_u','webcam_eye_midpoint_v','log_rotation_corrected_face_width'],
                'target':'screen UV; top-left [0,0], bottom-right [1,1]',
                'geometry':'screen-width units; center origin, +x right, +y up, +z toward wearer',
                'timestamps':'monotonic capture times; UTC is log write time'},
            observation_log_rate_hz=10,measurement_log_rate='all accepted measurements',
            note='Paired measurements are evidence, not proof of a validated model. Missing physical rays remain null.')

    def log_context(self):
        session=self.cursor_calibration
        preview=session.active and session.candidate is not None
        mapping=session.candidate if preview else self.mapping
        fit=getattr(self,'cursor_head_fit',self.head_fit) if preview else self.head_fit
        return self.audit.context(self.clock(),build=self.build_identity,
            eye_camera_id=self.calibration.eye_camera_id,head_camera=self.head_camera.status(self.clock()).get('camera_id'),
            displays=self.displays,detection_threshold=self.calibration.detection_threshold,
            head_model=model_snapshot(fit),gaze_model=model_snapshot(mapping),
            binocular_models={side:model_snapshot(m) for side,m in self.binocular.maps.items()},
            thresholds={'head_margin':HEAD_MARGIN.tolist(),'head_scale':HEAD_SCALE.tolist(),
                        'max_pair_gap_seconds':PAIR_MAX_SECONDS,'max_face_age_seconds':FACE_MAX_SECONDS,
                        'cursor_hold_seconds':1.,'cursor_motion_block_seconds':.5,
                        'cursor_motion_eye_residual_limit':.006,'cursor_eye_std_limit':.008,'cursor_fit_error_limit_uv':.1})

    def log_observation(self,result,target,reason,now):
        if self.audit.path is None:return
        if self.audit.last_observation is not None and now-self.audit.last_observation<.1:return
        self.audit.observation(now,context_id=self.log_context(),phase=self.phase,
            cursor_stage=self.cursor_calibration.stage if self.cursor_calibration.active else None,
            target=target,decision=reason,
            capture_time=(result or {}).get('capture_time'),
            pupil=(result or {}).get('pupil_ellipse'),confidence=(result or {}).get('confidence'),
            iris=(result or {}).get('iris_ellipse'),iris_support=(result or {}).get('iris_support'),
            pairing=self.head_camera.status(now).get('pairing'),
            head=(result or {}).get('head_pose'),
            ir_eye_center=(result or {}).get('eye_center'),ir_direction=(result or {}).get('gaze_direction'))

    def record_reference(self,eye,head,target,source,predicted=None,stamp=None,raw_eye=None,fixation_id=None):
        paired={}
        rig=self.calibration.eye_cameras
        if rig and hasattr(rig,'observations_at'):
            paired=rig.observations_at(self.clock() if stamp is None else stamp)
            self.binocular.record(paired,target,source,self.clock(),
                self.displays[0]['viewport'][2]/self.displays[0]['viewport'][3],rig.context()[0],fixation_id)
        self.reference_sequence+=1
        self.calibration_rays.append({'id':self.reference_sequence,
            'eye':np.asarray(eye).tolist(),'head':np.asarray(head).tolist(),
            'raw_eye':np.asarray(raw_eye if raw_eye is not None else eye).tolist(),
            'target':np.asarray(target).tolist(),'source':source,
            'paired_eyes':paired,'session_id':self.reference_session,'coordinate_frame':'screen_uv_and_webcam_features',
            'fixation_id':fixation_id,
            'head_camera_id':self.head_camera.status(self.clock()).get('camera_id'),
            'eye_camera_id':self.calibration.eye_camera_id,
            'viewport':self.displays[0]['viewport'],
            'captured_at':self.clock() if stamp is None else stamp,
            'predicted_before':np.asarray(predicted).tolist() if predicted is not None else None,
            'error_px':float(np.linalg.norm((np.asarray(predicted)-target)*self.displays[0]['viewport'][2:])) if predicted is not None else None})
        if self.audit.path is not None:
            mapping=self.cursor_calibration.candidate if self.cursor_calibration.active and self.cursor_calibration.candidate is not None else self.mapping
            geometry=mapping
            while geometry is not None and not isinstance(geometry,GeometricGazeMap):geometry=getattr(geometry,'base',None)
            ray=geometry.ray(np.asarray(raw_eye if raw_eye is not None else eye),np.asarray(head)) if geometry else None
            self.audit.append('measurement',self.clock(),context_id=self.log_context(),measurement=self.calibration_rays[-1],
                beam={'origin':ray[0] if ray else None,'direction':ray[1] if ray else None,
                      'predicted_screen_uv':ray[2] if ray else None,
                      'target_screen_point':screen_point(target,self.displays[0]['viewport'][2]/self.displays[0]['viewport'][3]),
                      'units':'screen widths','origin_source':'fitted assumed-optics geometry' if geometry else 'no fitted physical ray'})
        if self.reference_log is not None:
            try:
                self.reference_log.parent.mkdir(parents=True,exist_ok=True)
                with self.reference_log.open('a') as out:
                    out.write(json.dumps(self.calibration_rays[-1],allow_nan=False)+'\n')
            except OSError as error:
                print(f'Could not save calibration evidence: {error}',flush=True)
        # Continuous capture must not grow every /state response indefinitely.
        # Keep the initial/manual anchors; all motion evidence remains on disk.
        if source.startswith('geometry-') and self.reference_sequence%300==0:
            motion=[r for r in self.calibration_rays if r['source'].startswith('geometry-')]
            if len(motion)>3600:
                first_kept=motion[-3600]['id']
                self.calibration_rays=[r for r in self.calibration_rays
                    if not r['source'].startswith('geometry-') or r['id']>=first_kept]

    def start_cursor_calibration(self):
        if self.phase in ('motion','refine'):raise ValueError('Stop guided calibration before starting cursor alignment')
        if self.phase=='verify':self.stop_step()
        self.accuracy_check=None
        if not self.displays:raise ValueError('Wait for the laptop screen')
        if self.cursor_calibration.active:return
        if self.calibration.eye_model.phase=='uncalibrated':self.calibration.eye_model.start()
        if self.phase in ('waiting','fitting','head','screen'):self.stop_step()
        self.cursor_backup=(self.phase,self.mapping,self.head_fit)
        if self.head_fit.reference is None:self.head_fit=HeadCompensation()
        self.cursor_calibration=CursorCalibration(self.mapping,self.displays[0]['viewport'][2:])
        self.cursor_calibration.active=True
        self.cursor_calibration.stage="positions" if self.head_fit.reference is not None else "center"
        self.cursor_calibration.head_cue=None
        self.cursor_head_fit=self.head_fit if self.head_fit.reference is not None else HeadCompensation()
        self.cursor_head_target=None
        self.cursor_reference=[]
        self.last_cursor_decision=None
        if self.phase!='complete':self.phase='cursor'
        self.epoch=self.head_camera.epoch
        self.audit.append("cursor_started",self.clock(),context_id=self.log_context(),stage=self.cursor_calibration.stage,
                          labels_enabled=True,label_source='explicit_stationary_system_cursor')

    def start_preview_alignment(self,target):
        if self.phase!='complete' or self.mapping is None:
            raise ValueError('Finish the short screen calibration first')
        if self.cursor_calibration.active:
            raise ValueError('Finish the current alignment first')
        if (not isinstance(target,list) or len(target)!=2 or
                not all(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1 for x in target)):
            raise ValueError('Preview target must be on the calibrated display')
        self.start_cursor_calibration()
        self.cursor_calibration.fixed_target=list(target)
        self.cursor_calibration.message='Look at the fixed preview marker for one second, then gently move your head and pause.'

    def geometry_seeds(self):
        seeds=[]
        for index,target in enumerate(TARGETS):
            rows=[r for r in self.calibration_rays if r['source']=='onboarding' and np.allclose(r['target'],target)]
            if not rows:continue
            if index==0 and self.center_capture_window:
                low,high=self.center_capture_window
                rows=[r for r in rows if low<=r['captured_at']<=high]
            elif index and self.screen_circle and self.screen_circle.blocks[index-1]:
                stamps={p[0] for p in self.screen_circle.blocks[index-1]}
                rows=[r for r in rows if r['captured_at'] in stamps]
            else:
                last=rows[-1]['captured_at']
                rows=[r for r in rows if last-r['captured_at']<1.5]
            if not rows:continue
            seeds.append((np.median([r['raw_eye'] for r in rows],axis=0),
                          np.median([r['head'] for r in rows],axis=0),np.array(target)))
        # Manual cursor fixations are equally valid screen references. Use the
        # accepted map's anchors, not every historical (possibly rejected) frame.
        for eye,head,target in getattr(self.mapping,'anchors',[]):
            raw=np.asarray(eye)+(np.asarray(head)-self.head_fit.reference)/HEAD_SCALE@self.head_fit.coefficients
            seeds=[s for s in seeds if np.linalg.norm(s[2]-target)>=.06]
            seeds.append((raw,np.asarray(head).copy(),np.asarray(target).copy()))
        return seeds

    def start_head_refinement(self,guided=False):
        if self.phase!='complete' or self.mapping is None:
            raise ValueError('Finish the screen calibration first')
        if self.cursor_calibration.active:raise ValueError('Finish the current alignment first')
        now=self.clock()
        self.accuracy_check=None
        if not guided and self.guided_motion_outcome is not None:
            if self.head_refinement is not None:self.head_refinement.close()
            self.head_refinement=None;self.guided_motion_outcome=None
        if self.head_refinement is None or self.head_refinement.done:
            seeds=self.geometry_seeds()
            if len(seeds)<5 or np.min(np.ptp([s[2] for s in seeds],axis=0))<.5:
                raise ValueError('Save five or more cursor positions across the screen before head calibration')
            w,h=self.displays[0]['viewport'][2:]
            self.head_refinement=ContinuousTargetCalibration(self.mapping,self.head_fit,seeds,w/h,
                self.head_camera.status(now).get('image_aspect') or 16/9,now,
                eye_side=self.calibration.eye_cameras.context()[0] if self.calibration.eye_cameras else 'right')
            self.head_refinement_revision=0
            self.head_refinement_failures=(0,0)
        else:self.head_refinement.resume(now)
        self.cursor_calibration=CursorCalibration(self.mapping,self.displays[0]['viewport'][2:])
        session=self.cursor_calibration
        session.active=True;session.stage='geometry';session.fixed_target=[.5,.5]
        session.message=self.head_refinement.message
        session.progress=self.head_refinement.progress(now)
        self.epoch=self.head_camera.epoch
        if guided:
            self.head_refinement.enable_guided(now)
            for run in self.binocular.practices.values():
                if run.paused_elapsed is not None:run.resume(now)
                run.enable_guided(now)
            self.phase='motion';self.guided_motion_started=now
            self.guided_motion_outcome=None;self.progress=0.;self.sample_accepted=False
            self.target_since=now+.8  # Let the last corner travel to the center.
            self.message='Keep looking at the center; gently turn and shift your head.'
            session.message=self.message
        self.audit.append('head_motion_started',now,context_id=self.log_context(),seeds=self.head_refinement.seeds,
                          feature_schema='rotation_corrected_face_scale_v1',report=self.head_refinement.state(now))

    def guided_motion_deadline(self):
        deadline=self.guided_motion_started+self.GUIDED_MOTION_SECONDS
        # Either eye may finish fitting later. Let its already-started check
        # finish too; the selected eye must not determine the other eye's budget.
        base_deadline=deadline
        for practice in [self.head_refinement,*self.binocular.practices.values()]:
            if (practice is not None and practice.phase=='validate' and
                    practice.guided_started==self.guided_motion_started):
                deadline=max(deadline,min(base_deadline+practice.CHECK_SECONDS,
                                         practice.validation_started+practice.CHECK_SECONDS))
        return deadline

    def update_head_refinement(self,now):
        session=self.cursor_calibration;practice=self.head_refinement
        if not session.active or session.stage!='geometry' or practice is None:return
        practice.tick(now)
        session.progress=practice.progress(now);session.message=practice.message
        session.remaining_seconds=0.  # Explicit capture has no deadline.
        failures=(practice.fit_failures,practice.check_failures)
        if failures!=self.head_refinement_failures:
            self.head_refinement_failures=failures
            self.audit.append('head_motion_fit_rejected',now,context_id=self.log_context(),report=practice.state(now))
        if practice.revision>self.head_refinement_revision:
            self.mapping=practice.result
            self.head_refinement_revision=practice.revision
            self.calibration.desktop_cursor=True
            self.message=practice.message
            self.audit.append('head_motion_fit_result',now,context_id=self.log_context(),report=practice.state(now))

        if self.phase=='motion':
            elapsed=max(0.,now-self.guided_motion_started)
            remaining=max(0.,self.guided_motion_deadline()-now)
            self.progress=min(1.,elapsed/self.GUIDED_MOTION_SECONDS)
            session.remaining_seconds=remaining
            cue=practice.motion_cue(now)
            session.head_cue=cue['key'] if cue else None
            instructions={'shift':'Slide your head a little left and right; keep your face forward and eyes on the target',
                          'depth':'Move a little closer, then farther; keep your face level and eyes on the target',
                          'pitch':'Nod gently up and down; keep your eyes on the target',
                          'yaw':'Turn your face gently left and right; keep your eyes on the target'}
            session.message=((('Repeat: ' if cue['checking'] else '')+instructions[cue['key']]) if cue else practice.message)
            self.message=session.message
            rig=self.calibration.eye_cameras
            active=rig.context()[0] if rig else 'right'
            sides={s for s,c in getattr(rig,'config',{}).items() if isinstance(c,dict) and c.get('device_id')} or {active}
            runs={s:practice if s==active else self.binocular.practices.get(s) for s in sides}
            learned={s:bool(run and run.applied) for s,run in runs.items()}
            both_motion=all(run and all(run.checked_motion.values()) for run in runs.values())
            if remaining<=0 or (all(learned.values()) and both_motion and elapsed>=self.GUIDED_MOTION_MIN_SECONDS):
                self.guided_motion_outcome=('applied' if all(learned.values()) else
                                           'partial' if any(learned.values()) else 'previous_fit_kept')
                session.active=False;practice.pause(now);self.binocular.finish_head(now)
                self.phase='complete'
                self.audit.append('guided_head_finished',now,outcome=self.guided_motion_outcome,eyes=learned,report=practice.state(now))
                self.finish_guided_calibration()

    def finish_guided_calibration(self):
        """Finish the two learning stages; an accuracy exam is optional."""
        self.phase='complete';self.progress=1.;self.sample_accepted=False
        self.calibration.desktop_cursor=True;self.blocker=''
        self.message='Calibration finished. Refine by looking at the system cursor when needed.'
        if self.guided_motion_outcome=='previous_fit_kept':
            self.message='Five-dot map ready. No head correction learned; refine with the system cursor at different head positions.'
        elif self.guided_motion_outcome=='partial':
            self.message='Five-dot maps ready. Head correction learned for one eye; refine with the system cursor.'
        self.audit.append('guided_calibration_finished',self.clock(),outcome=self.guided_motion_outcome,
                          accuracy_checked=False)

    def refine_head(self,observation,stamp,now):
        # A rejected primary pupil must not stop the companion from learning
        # the same explicitly known center target with its own paired pose.
        rig=self.calibration.eye_cameras
        if rig and hasattr(rig,'observations_at') and (self.phase!='motion' or now>=self.target_since):
            observations=rig.observations_at(now,tolerance=.15)
            companion={s:o for s,o in observations.items() if s!=rig.context()[0]}
            if companion:
                self.binocular.record(companion,[.5,.5],'geometry-training',now,
                    self.displays[0]['viewport'][2]/self.displays[0]['viewport'][3],rig.context()[0])
                for side,run in self.binocular.practices.items():
                    if self.phase=='motion' and run.guided_started is None:
                        run.enable_guided(self.guided_motion_started)
                    if run.accepted and run.last_capture:
                        kind,sample=run.last_capture
                        self.audit.append('head_motion_eye_sample',now,eye=side,source=kind,sample=sample)
        practice=self.head_refinement
        practice.observe((observation[0],observation[1]) if observation else None,stamp,now)
        if practice.accepted:
            # These are accepted paired observations, not a claim that the
            # resulting model passed its later independent accuracy check.
            source,(captured,eye,head,target)=practice.last_capture
            self.record_reference(eye,head,target,source,stamp=captured)
        self.cursor_calibration.accepted=practice.accepted
        self.update_head_refinement(now)

    def cursor_sample(self,target,now=None):
        now=self.clock() if now is None else now
        self.tick(now)
        session=self.cursor_calibration
        if not session.active or self.phase=='motion':return
        if session.fixed_target is not None:target=session.fixed_target
        if not isinstance(target,list) or len(target)!=2 or not all(type(x) in (float,int) and math.isfinite(x) for x in target):
            raise ValueError('Cursor position must contain two finite numbers')
        if any(x<0 or x>1 for x in target):
            session.message='Move the mouse onto the calibrated screen'
            self.cursor_reference=[];session.reset_fixation()
            return
        latest=self.calibration.latest
        result=latest['result'] if latest and 0<=now-latest['time']<.15 else None
        checked,pair_reason=self.observation_check(result,now)
        observation=checked if result and result.get('confidence',0)>=self.calibration.detection_threshold else None
        shape_reason=pupil_shape_rejection(result) if observation and session.stage=='geometry' else None
        if shape_reason:
            observation=None;checked=None;pair_reason=shape_reason
        self.log_observation(result,target,pair_reason if checked is None else 'below_confidence_threshold' if observation is None else 'paired',now)
        eye=None;stamp=None
        if session.stage=='geometry':
            self.refine_head(observation,result.get('capture_time',latest['time']) if observation else now,now)
            return
        if observation:
            raw,head,packet=observation
            stamp=result.get('capture_time',latest['time'])
            if session.stage=='center':
                session.accepted=True
                session.target=np.asarray(target)
                if self.cursor_head_target is None or np.linalg.norm(np.array(target)-self.cursor_head_target)>.015:
                    self.cursor_head_target=np.array(target);self.cursor_reference=[]
                if not self.cursor_reference or stamp!=self.cursor_reference[-1][0]:
                    self.cursor_reference.append((stamp,raw,head))
                self.cursor_reference=[p for p in self.cursor_reference if now-p[0]<3]
                session.progress=min(.95,len(self.cursor_reference)/8,(stamp-self.cursor_reference[0][0])/1.2)
                if len(self.cursor_reference)>=8 and stamp-self.cursor_reference[0][0]>=1.2:
                    try:
                        self.cursor_head_fit.fit_steady([p[1] for p in self.cursor_reference],[p[2] for p in self.cursor_reference])
                        for captured_at,saved_eye,saved_pose in self.cursor_reference:
                            self.record_reference(saved_eye,saved_pose,target,'cursor-center',stamp=captured_at)
                        session.stage='positions'
                        # The first steady mouse fixation is also a screen anchor;
                        # don't make the user fill the same ring a second time.
                        session.target=np.asarray(target);session.since=self.cursor_reference[0][0]-.25
                        for captured_at,saved_eye,saved_pose in self.cursor_reference:
                            session.observe(target,saved_eye,captured_at,captured_at,pose=saved_pose,
                                evidence={'raw_eye':saved_eye.tolist(),'predicted':None})
                        self.audit.append('cursor_reference_ready',now,context_id=self.log_context(),saved_positions=session.saved_count)
                        return
                    except ValueError as error:
                        session.message=str(error);session.accepted=False;return
                session.message='Look at the stationary mouse; keep your head comfortable and still.'
                return
            eye=self.cursor_head_fit.correct(raw,head,enforce_bounds=session.base_mapping is None)
        before=session.saved_count
        predicted=self.estimate_uv(self.feature(result)) if result else None
        session.observe(target,eye,stamp,now,pose=observation[1] if observation is not None else None,
                        evidence={'raw_eye':observation[0].tolist(),'predicted':predicted,
                                  'per_eye_predictions':self.raw_eye_predictions()} if observation else None)
        if session.saved_count>before:
            fixation_id=uuid.uuid4().hex
            for _,saved_eye,saved_head,saved_target,evidence in session.last_capture:
                if saved_head is not None:
                    self.record_reference(saved_eye,saved_head,saved_target,'preview' if session.fixed_target else 'cursor',
                                          evidence['predicted'],evidence['captured_at'],evidence['raw_eye'],fixation_id)
            capture=session.last_capture
            poses=np.array([row[2] for row in capture if row[2] is not None])
            head_model=getattr(session.candidate,'head_model',None)
            self.audit.append('cursor_learning_update',now,context_id=self.log_context(),
                target_uv=target,capture_kind=getattr(session,'capture_kind','fixation'),
                head_change_degrees=np.degrees(poses[-1,:3]-poses[0,:3]) if len(poses) else None,
                head_translation_feature_change=poses[-1,3:]-poses[0,3:] if len(poses) else None,
                head_correction_status=getattr(head_model,'status',None),
                head_correction_rank=getattr(head_model,'rank',0),
                samples=[{'captured_at':row[4]['captured_at'],'raw_eye':row[4]['raw_eye'],
                          'head':row[2],'predicted_before':row[4]['predicted'],
                          'eyes_before':row[4].get('per_eye_predictions',{})} for row in capture],
                note='Explicit cursor target is the label. Before-update errors are training feedback, not an independent accuracy check.')
        if session.fixed_target is not None and session.accepted:
            session.message=('Reference saved. Keep watching the marker; gently move your head and pause.'
                             if session.progress>=1 else 'Keep watching the fixed marker; hold this head position for one second.')
        if observation is None:session.message='Waiting for a reliable paired eye sample'
        elif eye is None:session.message='Return nearer the saved head position; then capture small head changes while watching the pointer'
        decision=(session.saved_count,session.message)
        if decision!=getattr(self,'last_cursor_decision',None):
            self.last_cursor_decision=decision
            self.audit.append('cursor_fixation_result',now,context_id=self.log_context(),saved=session.saved_count>before,
                ready=session.candidate is not None,progress=session.progress,message=session.message,target=target)
        if session.candidate is not None:self.calibration.desktop_cursor=True

    def finish_cursor_calibration(self):
        if self.phase=='motion':
            self.stop_step()
            return
        session=self.cursor_calibration
        if not session.active:return
        session.active=False
        if session.stage=='geometry':
            self.head_refinement.pause(self.clock())
            self.binocular.finish_head(self.clock())
            session.accepted=False
            session.message=self.head_refinement.message
            self.audit.append('head_motion_stopped',self.clock(),context_id=self.log_context(),report=self.head_refinement.state(self.clock()))
            return
        if session.candidate is not None:
            self.mapping=session.candidate;self.head_fit=self.cursor_head_fit;self.phase='complete';self.progress=1
            if self.head_refinement is not None:self.head_refinement.close()
            self.head_refinement=None  # Practice from the newly aligned screen fit next time.
            self.calibration.desktop_cursor=True
            self.message='Eye cursor aligned with the system cursor'
        elif self.cursor_backup:
            self.phase,self.mapping,self.head_fit=self.cursor_backup
            session.message+=' · Previous calibration retained'
        self.audit.append('cursor_finished',self.clock(),context_id=self.log_context(),applied=session.candidate is not None,message=session.message,labels_enabled=False)
        self.cursor_backup=None

    def cancel(self):
        self.arm()
        self.phase='cancelled'
        self.calibration.eye_model.phase='uncalibrated'
        self.message='Calibration paused'

    def stop_step(self):
        """Stop screen/head capture without discarding completed prerequisites."""
        if self.phase=='refine':
            self.phase='paused';self.stopped_stage='refine'
            self.sample_accepted=False;self.feedback_at=None;self.blocker='Stopped by user'
            return
        if self.phase=='motion':
            self.head_refinement.pause(self.clock());self.binocular.finish_head(self.clock())
            self.cursor_calibration.active=False
            self.stopped_stage='motion';self.phase='paused'
            self.sample_accepted=False;self.feedback_at=None
            self.message='Calibration stopped. Completed screen fit kept.'
            self.blocker='Stopped by user'
            return
        if self.phase=='verify':
            self.accuracy_check.done=True
            self.accuracy_check.status='incomplete'
            self.audit.append('accuracy_check_result',self.clock(),report=self.accuracy_check.state(self.clock()))
            self.stopped_stage='verify';self.phase='paused'
            self.sample_accepted=False;self.feedback_at=None
            self.message='Accuracy check stopped. Completed calibration kept.'
            self.blocker='Stopped by user'
            return
        if self.phase not in ('waiting','fitting','head','screen'):return
        self.stopped_stage='head' if self.phase=='waiting' else self.phase
        self.phase='paused'
        self.sample_accepted=False
        self.feedback_at=None
        self.message='Calibration stopped. Retry this step when ready.'
        self.blocker='Stopped by user'
        if self.epoch is None:self.epoch=self.head_camera.epoch

    def retry_step(self,now=None):
        """Retry only unfinished work; completed head/target fits remain usable."""
        now=self.clock() if now is None else now
        self.tick(now)  # A changed camera invalidates the old coordinate system.
        stage=self.stopped_stage if self.phase=='paused' else self.phase
        if stage=='refine':
            self.phase='complete';self.start_dot_learning()
            return
        if stage=='verify':
            self.start_accuracy_check()
            return
        if stage=='motion':
            self.phase='complete';self.stopped_stage=None
            self.start_head_refinement(guided=True)
            return
        if stage not in ('fitting','head','screen'):
            self.arm(start=True)
            return
        if stage=='screen' and self.head_fit.reference is None:
            raise ValueError('Complete head calibration before continuing screen points')
        self.phase=stage
        self.stopped_stage=None
        # Every explicit retry gets a fresh time budget, including after a long pause.
        self.started_at=now
        self.target_since=now+.55
        self.progress=0.
        self.sample_accepted=False
        self.feedback_at=None
        self.feedback_progress=0.
        self.last_advance=None
        self.last_seen=None
        self.last_pair_time=None
        self.hold.clear()
        self.mapping=None
        self.accuracy_check=None
        self.validation_error=None
        self.blocker='Waiting for fresh paired eye and head samples'
        if stage in ('fitting','head'):
            self.pairs=[]
            self.fixations=[]
            self.head_fit=HeadCompensation()
            self.index=0
            self.sample_counts.clear()
            self.fit_failures.clear()
            self.last_fit_error=None
            self.last_sample_rejection=None
            self.report_written=False
        if stage=='fitting':
            self.calibration.reset_eye_model()
            self.calibration.eye_model.start()
            self.orbit_samples=0
            self.head_started=None
            self.head_cue=None
            self.message='Follow the circular dot with your eyes.'
        elif stage=='head':
            self.head_started=now
            self.head_cue=None
            self.message='Look at the center dot; keep your head comfortable and still.'
        else:
            self.fixations=self.fixations[:1]
            self.index=1;self.head_cue=None
            if self.screen_circle is not None:self.screen_circle.retry(now+.3)
            else:self.screen_circle=QuickCalibration(np.median(self.fixations[0],axis=0),now+.3)
            self.message='Follow the four dots; keep your head comfortably still.'

    def observation_check(self,result,now=None):
        now=self.clock() if now is None else now
        if not isinstance(result,dict):return None,'no_pupil'
        ellipse=result.get('pupil_ellipse')
        head=result.get('head_pose')
        if not isinstance(ellipse,dict) or not ellipse.get('center'):return None,'no_pupil'
        if not head:return None,'no_paired_head'
        if head.get('epoch')!=self.head_camera.epoch:return None,'camera_epoch_changed'
        if not self.head_camera.status(now)['face_visible']:return None,'face_not_visible'
        if not 0<=now-head.get('time',-1)<=FACE_MAX_SECONDS:return None,'head_sample_stale'
        if abs(result.get('capture_time',now)-head['time'])>PAIR_MAX_SECONDS:return None,'timestamp_gap'
        eye=np.array(ellipse['center'],dtype=float)/[640,480]
        pose=np.array(head.get('features'),dtype=float)
        if (eye.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[eye,pose]).all()
                or not np.all((eye>0)&(eye<1))):return None,'invalid_geometry'
        return (eye,pose,head),'paired'

    def observation(self,result,now=None):
        return self.observation_check(result,now)[0]

    def write_diagnostic_report(self):
        if self.report_written or self.diagnostic_path is None:return
        self.report_written=True
        report={'started_at':self.started_at,'head_ready':self.head_fit.reference is not None,'head_mode':self.head_fit.mode,
                'head_reference':self.head_fit.reference.tolist() if self.head_fit.reference is not None else None,'phase':self.phase,'message':self.message,'sample_counts':dict(self.sample_counts),
                'fit_failures':dict(self.fit_failures),'last_fit_error':self.last_fit_error,
                'fit_metrics':self.head_fit.metrics,'last_sample_rejection':self.last_sample_rejection,
                'pairing':self.head_camera.status(self.clock()).get('pairing'),
                'pairs':[{'time':t,'eye':eye.tolist(),'head':pose.tolist()} for t,eye,pose in self.pairs]}
        # Numeric diagnostic data only, no images. One bounded attempt, overwritten
        # by the next completed/failed head stage; never sent off this machine.
        path=self.diagnostic_path
        try:path.write_text(json.dumps(report,indent=2,allow_nan=False))
        except (OSError,ValueError) as error:print(f'Head diagnostics could not be saved: {error}',flush=True)

    def feature(self,result):
        observation=self.observation(result)
        return np.r_[observation[0],observation[1]].tolist() if observation else None

    def collect_shared_target(self,now):
        rig=self.calibration.eye_cameras
        if not rig or not hasattr(rig,'observations_at'):return True
        if self.phase=='head':
            index=0;settled_at=self.target_since;started=self.head_started
        elif self.phase=='screen' and self.screen_circle:
            from quick_calibration import TRAVEL,SETTLE
            index=self.screen_circle.index+1;started=self.screen_circle.corner_started_at
            settled_at=started+TRAVEL+SETTLE
        else:return True
        if settled_at is None:return True
        observations=rig.observations_at(now,tolerance=.15)
        ready=self.binocular.collect_onboarding(observations,index,settled_at,now)
        capture=self.binocular.onboarding_captures[index]
        if capture.accepted_sides:
            self.audit.append('onboarding_eye_samples',now,target=TARGETS[index],
                              observations={s:observations[s] for s in capture.accepted_sides})
        sides={s for s,c in getattr(rig,'config',{}).items() if isinstance(c,dict) and c.get('device_id')}
        # Both eyes see one shared target. Keep their capture windows separate;
        # an absent camera cannot hold the working eye indefinitely.
        return sides.issubset(ready) or (started is not None and now-started>=7.8)

    def tick(self,now=None):
        now=self.clock() if now is None else now
        if self.epoch is not None and self.head_camera.epoch != self.epoch:
            was_stopped=self.phase=='paused'
            self.arm(start=was_stopped)
            if was_stopped:self.stop_step()
            return
        self.update_head_refinement(now)
        if self.phase=='refine':
            self.dot_learning.tick(now)
            if self.dot_learning.done:self.finish_dot_learning()
            return
        if self.phase=='verify':
            self.accuracy_check.tick(now)
            if self.accuracy_check.done:self.finish_accuracy_check()
            return
        shared_ready=self.collect_shared_target(now)
        if self.phase=='screen' and self.screen_circle is not None:
            self.screen_circle.advance_allowed=shared_ready
            self.screen_circle.advance(now)
        if self.phase=='screen' and self.screen_circle is not None and (self.screen_circle.finished or self.screen_circle.timed_out):
            try:
                if self.screen_circle.timed_out:
                    corner=('top-left','top-right','bottom-right','bottom-left')[self.screen_circle.index]
                    raise ValueError(f'Too few clear samples at {corner}. Retry keeps {self.screen_circle.coverage}/4 completed corners.')
                self.mapping=self.screen_circle.fit()
                center=[r['captured_at'] for r in self.calibration_rays
                        if r['source']=='onboarding' and np.allclose(r['target'],TARGETS[0])]
                if center:
                    windows=[self.center_capture_window or (max(min(center),max(center)-1.8),max(center))]+[(b[0][0],b[-1][0]) for b in self.screen_circle.blocks]
                    self.binocular.finish_onboarding(windows)
                self.phase='complete';self.calibration.desktop_cursor=True
                try:self.start_head_refinement(guided=True)
                except ValueError as error:
                    # A usable five-dot map must survive missing head-fit seeds.
                    self.guided_motion_outcome='previous_fit_kept'
                    self.audit.append('guided_head_unavailable',now,reason=str(error))
                    self.finish_guided_calibration()
            except ValueError as error:
                self.screen_circle.fit_status=str(error)
                self.phase='paused';self.stopped_stage='screen';self.message=str(error)
                reason=max(self.screen_circle.rejections,key=self.screen_circle.rejections.get,default=None)
                self.blocker=str(error)+(f' {reason}' if reason else '')
            self.audit.append('screen_fit_result',now,context_id=self.log_context(),phase=self.phase,message=self.message)
            return
        if self.started_at is not None and self.phase in ('fitting','head'):
            if now-self.started_at>self.TOTAL_SECONDS or (self.phase=='head' and self.head_started is not None and now-self.head_started>self.HEAD_SECONDS):
                self.stopped_stage=self.phase
                self.message=(f'Head correction incomplete: {self.blocker}' if self.phase=='head'
                              else f'Screen capture incomplete: {self.blocker}')
                self.phase='paused'
                self.mapping=None
                self.write_diagnostic_report()

    def start_dot_learning(self):
        if self.phase!='complete' or self.mapping is None or self.cursor_calibration.active:
            raise ValueError('Finish or stop the current calibration first')
        rig=self.calibration.eye_cameras
        sides={s for s,c in rig.config.items() if isinstance(c,dict) and c.get('device_id')} if rig and hasattr(rig,'config') else set()
        self.dot_learning=DotLearning(self.clock(),sides or {rig.context()[0] if rig else 'right'})
        self.accuracy_check=None;self.phase='refine';self.sample_accepted=False
        self.message='Follow five dots. Each target is the known gaze position.'
        self.audit.append('dot_learning_started',self.clock())

    def update_dot_learning(self,result,now):
        rig=self.calibration.eye_cameras
        if rig and hasattr(rig,'observations_at'):observations=rig.observations_at(now)
        else:
            observation,_=self.observation_check(result,now)
            observations={}
            if observation is not None and result.get('confidence',0)>=self.calibration.detection_threshold:
                eye,head,_=observation
                observations['right']={'eye':eye,'head':head,'time':result.get('capture_time',now)}
        self.dot_learning.observe(observations,now)
        if self.dot_learning.accepted:
            self.audit.append('dot_learning_sample',now,target=self.dot_learning.target,observations=observations)
        self.sample_accepted=self.dot_learning.accepted;self.blocker=self.dot_learning.reason
        self.dot_learning.tick(now)
        if self.dot_learning.done:self.finish_dot_learning()

    def finish_dot_learning(self):
        rig=self.calibration.eye_cameras;active=rig.context()[0] if rig else 'right'
        applied=[];failures={}
        for side in self.dot_learning.sides:
            rows=self.dot_learning.rows
            if any(side not in row['eyes'] for row in rows):
                failures[side]='Missing clear target samples';continue
            identities={json.dumps(s.get('identity')) for row in rows for s in row['eyes'][side]}
            if len(identities)!=1:
                failures[side]='Camera changed during capture';continue
            identity=rows[0]['eyes'][side][0].get('identity')
            if side!=active and identity is not None:self.binocular.identity(side,identity)
            anchors=[]
            for row in rows:
                samples=row['eyes'][side]
                eyes=[self.head_fit.correct(np.asarray(s['eye']),np.asarray(s['head']),enforce_bounds=False)
                      if side==active else s['eye'] for s in samples]
                anchors.append((np.median(eyes,axis=0),np.median([s['head'] for s in samples],axis=0),np.asarray(row['target'])))
            base=self.mapping if side==active else self.binocular.maps.get(side)
            try:
                old=[a for a in getattr(base,'anchors',[]) if all(np.linalg.norm(a[2]-b[2])>.15 or
                     np.linalg.norm((a[1]-b[1])/PoseAnchorMap.pose_scale)>1 for b in anchors)]
                # Old-model support or conflicts cannot veto a fresh complete
                # labelled pass. Rebuild from these five targets if necessary.
                try:
                    if base is None:raise ValueError('No prior map')
                    fitted=PoseAnchorMap(base,old+anchors)
                except ValueError:
                    fitted=PoseAnchorMap(AnchorMap([a[0] for a in anchors]),anchors)
                if side==active:
                    self.mapping=fitted
                    if self.head_refinement is not None:self.head_refinement.close()
                    self.head_refinement=None
                else:
                    self.binocular.maps[side]=fitted
                    self.binocular.seeds[side]=anchors
                    self.binocular.manual_points[side]={}
                    self.binocular.manual_hold[side]=None
                    run=self.binocular.practices.pop(side,None)
                    if run:run.close()
                applied.append(side)
            except ValueError as error:failures[side]=str(error)
        self.audit.append('dot_learning_result',self.clock(),measurements=self.dot_learning.rows,applied=applied,failures=failures)
        self.phase='complete';self.sample_accepted=False;self.progress=1.
        self.message=('Learned target measurements: '+', '.join(applied)+'.' if applied else 'No new fit. Previous calibration kept.')
        if failures:self.message+=' Unchanged: '+', '.join(failures)+'.'
        self.blocker='';self.calibration.desktop_cursor=True

    def start_accuracy_check(self):
        retry=self.phase=='paused' and self.stopped_stage=='verify'
        if (self.phase!='complete' and not retry) or self.mapping is None:
            raise ValueError('Finish screen calibration before checking accuracy')
        if self.cursor_calibration.active:
            raise ValueError('Finish alignment before checking accuracy')
        self.accuracy_check=AccuracyCheck(self.displays[0]['viewport'],self.clock())
        self.validation_error=None
        self.phase='verify';self.progress=0.;self.sample_accepted=False
        self.stopped_stage=None
        self.message='Check accuracy at five new dots. Keep your head still.'
        self.blocker='Look at the first dot'

    def finish_accuracy_check(self):
        report=self.accuracy_check.state(self.clock())
        report['gaze_eye_mode']=getattr(self.calibration,'gaze_eye_mode','both')
        self.phase='complete';self.progress=1.;self.sample_accepted=False
        self.message=('Accuracy check complete. See the checked points on the laptop in diagnostics.' if report['status']=='complete'
                      else 'Accuracy check incomplete. The initial mapping is kept; check again when ready.')
        if self.guided_motion_outcome=='partial':
            self.message+=' Head correction was learned for only one eye.'
        if self.guided_motion_outcome=='previous_fit_kept':
            self.message+=' Head movement did not establish a checked correction; the five-dot fit was kept.'
        self.blocker=''
        self.audit.append('accuracy_check_result',self.clock(),report=report)

    def update_accuracy_check(self,result,now):
        observation,reason=self.observation_check(result,now)
        check=self.accuracy_check
        if observation is None or result.get('confidence',0)<self.calibration.detection_threshold:
            check.reject(reason if observation is None else 'Pupil confidence too low')
        else:
            eye,pose,_=observation
            raw,fixation=self.binocular_estimate()
            # Use exactly the cursor's chosen eye(s), with the same pose limits.
            # The primary eye's old pose box must not block a supported companion.
            mode=getattr(self.calibration,'gaze_eye_mode','both')
            predicted=fixation['uv'] if raw or mode!='both' else self.estimate_uv([*eye,*pose])
            # Prediction availability is a report result, never a fixation gate.
            self.sample_accepted=check.observe(eye,predicted,result.get('capture_time',now),now)
        self.blocker=check.reason
        check.tick(now)
        if check.done:self.finish_accuracy_check()

    def update(self,result,now=None):
        now=self.clock() if now is None else now
        self.tick(now)
        self.sample_accepted=False
        self.feedback_at=now
        if self.phase=='refine':
            self.update_dot_learning(result,now)
            return
        model=self.calibration.eye_model
        if model.phase=='collecting' and model.status(now)['can_freeze']:
            model.freeze(now)
        if self.phase=='motion':
            observation,reason=self.observation_check(result,now)
            good=observation is not None and result.get('confidence',0)>=self.calibration.detection_threshold
            if good and pupil_shape_rejection(result):good=False;reason='Pupil shape unstable'
            if now<self.target_since:good=False;reason='Target is moving to center'
            self.log_observation(result,[.5,.5],reason if not good else 'paired',now)
            self.refine_head(observation if good else None,(result or {}).get('capture_time',now),now)
            if self.phase=='motion':
                self.sample_accepted=self.head_refinement.accepted
                self.blocker='Measuring head movement' if self.sample_accepted else reason
            return
        if self.phase=='verify':
            self.update_accuracy_check(result,now)
            return
        if self.phase in ('no_displays','idle','paused','cancelled','complete','cursor'):return
        observation,reason=self.observation_check(result,now)
        good=bool(observation is not None and result.get('confidence',0)>=self.calibration.detection_threshold)
        target=self.screen_circle.target(now) if self.phase=='screen' and self.screen_circle else list(TARGETS[0])
        self.log_observation(result,target,reason if observation is None else 'below_confidence_threshold' if not good else 'paired',now)
        if self.phase=='head':
            rejection=reason if observation is None else 'low_pupil_confidence' if not good else 'accepted'
            self.sample_counts[rejection]+=1
            if not good:self.last_sample_rejection=rejection
        previous=self.last_seen
        if good:self.last_seen=now
        if self.phase=='waiting':
            self.waiting_counts[reason if observation is None else 'low_pupil_confidence' if not good else 'accepted']+=1
            if not good:
                self.visible_since=None
                self.message=('Waiting for IR pupil confidence to meet the detection threshold.' if observation is not None else
                              'Waiting for a detected IR pupil.' if reason=='no_pupil' else
                              'Waiting for a visible face in the webcam.' if reason=='face_not_visible' else
                              'Waiting for a fresh, paired webcam sample.')
                self.blocker=self.message
                return
            if self.visible_since is None or previous is None or now-previous>.2:self.visible_since=now
            if now-self.visible_since>=.6:
                self.phase='head';self.started_at=now;self.head_started=now;self.target_since=now+.55
                self.epoch=observation[2]['epoch']
                self.head_cue=None
                self.message='Look at the center dot; keep your head comfortable and still.'
            return
        if self.phase=='fitting':
            self.sample_accepted=good
            if good:self.orbit_samples+=1
            self.progress=min(.95,self.orbit_samples/150)
            if now-self.started_at>=ORBIT_SECONDS:
                self.phase='head';self.head_started=now;self.target_since=now+.55
                self.progress=0.;self.sample_accepted=False;self.head_cue=None
                self.message='Look at the center dot; keep your head comfortable and still.'
            return
        if not good:
            self.blocker=('Face not visible' if not self.head_camera.status(now)['face_visible'] else
                          'IR pupil below detection threshold' if result and result.get('confidence',0)<self.calibration.detection_threshold else
                          'Waiting for synchronized eye and head samples')
            if self.phase=='head' and self.last_fit_error:self.blocker=self.last_fit_error
            if self.phase=='screen' and self.screen_circle:self.screen_circle.reject(self.blocker)
            return
        eye,pose,head=observation
        if now<self.target_since:
            self.blocker='Target is moving';return
        if self.phase=='head':
            if head['time']==self.last_pair_time:
                self.sample_counts['duplicate_head_sample']+=1;return
            self.last_pair_time=head['time']
            self.pairs.append((result.get('capture_time',now),eye,pose))
            # A short stable center reference enables a bounded, steady-head
            # cursor first. Larger head movement is trained separately later.
            recent=[p for p in self.pairs if now-p[0]<=1.8]
            if len(recent)>1 and recent[-1][0]-recent[-2][0]>.75:
                self.pairs=self.pairs[-1:];recent=self.pairs
            duration=recent[-1][0]-recent[0][0]
            self.progress=min(.9,len(recent)/8,duration/1.0)
            self.head_cue=None
            self.message='Look at the center dot; keep your head comfortable and still.'
            self.blocker=self.message;self.sample_accepted=True
            if len(recent)<8 or duration<1.0:return
            if not self.collect_shared_target(now):return
            try:
                corrected=self.head_fit.fit_steady([p[1] for p in recent],[p[2] for p in recent])
            except ValueError as error:
                self.last_fit_error=str(error);self.fit_failures[str(error)]+=1
                self.blocker=str(error)
                return
            self.last_fit_error=None
            self.write_diagnostic_report()
            self.fixations=[corrected.tolist()]
            self.center_capture_window=(recent[0][0],recent[-1][0])
            for stamp,eye,pose in recent:
                self.record_reference(eye,pose,TARGETS[0],'onboarding',stamp=stamp)
            self.phase='screen';self.index=1;self.target_since=now+.3;self.head_cue=None;self.sample_accepted=False
            self.screen_circle=QuickCalibration(np.median(corrected,axis=0),now+.3)
            self.progress=0.;self.message='Follow the dot with your eyes. Keep your head comfortable.'
            return
        point=self.head_fit.correct(eye,pose)
        if point is None:
            self.blocker='Head outside the calibrated range'
            if self.screen_circle:self.screen_circle.reject(self.blocker)
            self.message='Keep your head near the center-capture position and follow the moving dot.'
            return
        if self.screen_circle is None:return
        accepted=self.screen_circle.observe(point,result.get('capture_time',now),now)
        if accepted:
            block=self.screen_circle.index
            self.record_reference(point,pose,TARGETS[block+1],'onboarding',stamp=result.get('capture_time',now),raw_eye=eye)
        self.progress=self.screen_circle.progress_at(now)
        self.sample_accepted=accepted
        self.blocker='Collecting path samples' if accepted else 'Waiting for a fresh eye frame'
        self.message='Follow the four dots; keep your head comfortably still.'

    @property
    def has_screen_mapping(self):
        return (self.cursor_calibration.active and self.cursor_calibration.candidate is not None) or (self.phase=='complete' and self.mapping is not None)

    @property
    def has_prediction_mapping(self):
        # Validation uses the saved fit while the interactive cursor is hidden.
        return self.has_screen_mapping or (self.phase in ('motion','verify') and self.mapping is not None)

    def estimate_uv(self,feature):
        if not self.has_prediction_mapping or feature is None or len(feature)!=8:return None
        if not self.head_camera.status(self.clock())['face_visible']:return None
        preview=self.cursor_calibration.active and self.cursor_calibration.candidate is not None
        mapping=self.cursor_calibration.candidate if preview else self.mapping
        head_fit=self.cursor_head_fit if preview else self.head_fit
        corrected=head_fit.correct(feature[:2],feature[2:])
        if hasattr(mapping,'project_pose_unbounded'):
            unbounded=head_fit.correct(feature[:2],feature[2:],enforce_bounds=False)
            mapped=mapping.project_pose_unbounded(unbounded,feature[2:],baseline_allowed=corrected is not None)
        else:mapped=project_unbounded(mapping,corrected)
        if mapped is None or np.shape(mapped)!=(2,) or not np.isfinite(mapped).all():return None
        return np.asarray(mapped).tolist()

    def raw_eye_predictions(self):
        rig=self.calibration.eye_cameras
        if not rig or not hasattr(rig,'observations_at') or not self.has_prediction_mapping:return {}
        observations=getattr(rig,'prediction_observations_at',rig.observations_at)(self.clock(),tolerance=.15)
        predictions={};active=rig.context()[0]
        for side,observation in observations.items():
            uv=(self.estimate_uv([*observation['eye'],*observation['head']]) if side==active else
                self.binocular.predict(side,observation))
            if uv is None or np.shape(uv)!=(2,) or not np.isfinite(uv).all():continue
            x,y,w,h=self.displays[0]['viewport']
            predictions[side]={'uv':np.asarray(uv).tolist(),'confidence':observation['confidence'],
                'head_features':observation['head'],'captured_at':observation['time'],
                'identity':str(observation['identity']),
                'held':bool(observation.get('held',False)),
                'desktop':fence(uv,self.displays[0]['viewport'])}
        return predictions

    def binocular_estimate(self):
        raw=self.raw_eye_predictions()
        mode=getattr(getattr(self,'calibration',None),'gaze_eye_mode','both')
        selected=raw if mode=='both' else {side:row for side,row in raw.items() if side==mode}
        aspect=self.displays[0]['viewport'][2]/self.displays[0]['viewport'][3] if self.displays else 1.
        return raw,shared_fixation(selected,aspect)

    def eye_predictions(self):
        # Optional debug dots show independent calibrated predictions, never two
        # copies of the consensus or raw optical rays with guessed mounting.
        return self.raw_eye_predictions()

    def desktop_point(self,feature):
        raw,fixation=self.binocular_estimate()
        if fixation['status']=='unsynchronized':return None
        uv=fixation['uv']
        if uv is None and getattr(getattr(self,'calibration',None),'gaze_eye_mode','both')!='both':return None
        if uv is None:uv=self.estimate_uv(feature)
        if not self.displays or uv is None:return None
        viewport=self.displays[0]['viewport']
        if len(fixation['sides'])==2:
            # Average the displayed eye positions, including their screen fence,
            # so the white cursor stays between the two colored markers.
            return np.mean([fence(raw[side]['uv'],viewport) for side in fixation['sides']],axis=0).tolist()
        return fence(uv,viewport)

    def state(self,now=None):
        now=self.clock() if now is None else now
        self.tick(now)
        head=self.head_camera.status(now)
        message=head['error'] or (self.cursor_calibration.message if self.cursor_calibration.active else self.message)
        running=self.phase in ('fitting','head','screen') and self.started_at is not None
        remaining=max(0.,self.TOTAL_SECONDS-(now-self.started_at)) if running else None
        step_remaining=(min(remaining,max(0.,self.HEAD_SECONDS-(now-self.head_started)))
                        if running and self.phase=='head' and self.head_started is not None else None)
        if self.phase=='motion':
            remaining=max(0.,self.guided_motion_deadline()-now)
            step_remaining=remaining
        if self.phase=='screen' and self.screen_circle is not None:
            remaining=max(0.,self.screen_circle.corner_started_at+MAX_CORNER_SECONDS-now)
            step_remaining=remaining
        progress=self.screen_circle.progress_at(now) if self.phase=='screen' and self.screen_circle else self.progress
        if self.phase in ('head','screen'):
            index=self.screen_circle.index+1 if self.phase=='screen' and self.screen_circle else 0
            capture=self.binocular.onboarding_captures.get(index)
            rig=self.calibration.eye_cameras
            sides={s for s,c in getattr(rig,'config',{}).items() if isinstance(c,dict) and c.get('device_id')}
            if capture and sides:progress=min(progress,capture.progress(sides))
        mapping=self.cursor_calibration.candidate if self.cursor_calibration.active and self.cursor_calibration.candidate is not None else self.mapping
        head_model=getattr(mapping,'head_model',None)
        empirical=mapping
        while empirical is not None and not isinstance(empirical,HeadMotionMap):empirical=getattr(empirical,'base',None)
        geometry=mapping
        while geometry is not None and not isinstance(geometry,GeometricGazeMap):geometry=getattr(geometry,'base',None)
        return {'phase':self.phase,'display_id':self.displays[0]['id'] if self.displays else None,
                'eye_map_status':{side:('Screen map ready' if (self.mapping is not None if side==(self.calibration.eye_cameras.context()[0] if self.calibration.eye_cameras else 'right') else side in self.binocular.maps)
                                else 'Needs target samples') for side in ('left','right')},
                'display_index':1 if self.displays else 0,'display_count':len(self.displays),
                'guided_head_outcome':self.guided_motion_outcome,
                'dot_learning':self.dot_learning.state(now) if self.phase=='refine' else None,
                'target':(self.dot_learning.target if self.phase=='refine' else [.5,.5] if self.phase=='motion' else self.accuracy_check.target if self.phase=='verify' else self.screen_circle.target(now) if self.phase=='screen' and self.screen_circle is not None
                          else list(TARGETS[self.index]) if self.phase in ('fitting','head','screen') else None),
                'screen_path_started_at':self.screen_circle.corner_started_at if self.phase=='screen' and self.screen_circle is not None else None,
                'screen_path':'quick' if self.phase=='screen' and self.screen_circle is not None else None,
                'accuracy_check':self.accuracy_check.state(now) if self.accuracy_check else None,
                'progress':self.dot_learning.state(now)['progress'] if self.phase=='refine' else self.accuracy_check.state(now)['progress'] if self.phase=='verify' else progress,'message':message,'elapsed':now-self.started_at if self.started_at is not None else 0,
                'remaining_seconds':remaining,'step_remaining_seconds':step_remaining,
                'sample_accepted':bool(self.sample_accepted and self.feedback_at is not None
                                       and 0<=now-self.feedback_at<=.15 and head['face_visible']),
                'fast_path':False,'profile_saved':False,'mode':'hybrid',
                'validation_error':self.validation_error,'head_camera':head,
                'head_cue':self.head_cue if self.phase=='head' else None,
                'head_ready':self.head_fit.reference is not None,'head_mode':self.head_fit.mode,
                'head_reference':self.head_fit.reference.tolist() if self.head_fit.reference is not None else None,
                'cursor_calibration':self.cursor_calibration.state(),
                'calibration_rays':[r for r in self.calibration_rays
                    if not r['source'].startswith('geometry-') or r['id']>self.reference_sequence-120],
                'calibration_measurement_count':self.reference_sequence,
                'calibration_session_id':self.reference_session,
                'calibration_log':str(self.audit.path) if self.audit.path else None,
                'calibration_log_error':self.audit.error,
                'head_correction_rank':getattr(head_model,'rank',0),
                'head_correction_error':getattr(head_model,'error',None),
                'head_correction_status':'empirical' if empirical is not None else 'geometric' if geometry is not None else getattr(head_model,'status','no_cursor_anchors'),
                'geometry_model':geometry.geometry() if geometry is not None else None,
                'geometry_calibration':self.head_refinement.state(now) if self.head_refinement is not None else None,
                'head_correction_pairs':getattr(head_model,'pair_count',0),
                'head_correction_fit_error':getattr(head_model,'fit_error',None),
                'screen_points':len(self.fixations), 'screen_point':self.index+1,
                'screen_sectors':self.screen_circle.coverage if self.screen_circle is not None else 0,
                'screen_fit_status':self.screen_circle.fit_status if self.screen_circle is not None else None,
                'screen_sample_counts':[len(block) for block in self.screen_circle.blocks] if self.screen_circle else [],
                'screen_rejections':self.screen_circle.rejections if self.screen_circle else {},
                'screen_fit_error':self.screen_circle.error if self.screen_circle is not None else None,
                'screen_target_index':self.screen_circle.index+2 if self.screen_circle and self.phase=='screen' else None,
                'blocker':self.blocker, 'stopped_stage':self.stopped_stage,
                'head_diagnostics':{'samples':len(self.pairs),'sample_counts':dict(self.sample_counts),
                    'waiting_counts':dict(self.waiting_counts),
                    'last_sample_rejection':self.last_sample_rejection,'last_fit_error':self.last_fit_error,
                    'fit_failures':dict(self.fit_failures),'fit_metrics':self.head_fit.metrics}}
