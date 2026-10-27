"""Screen-attached gaze geometry fitted from known targets and paired camera samples.

Lengths are fractions of screen width, not measured centimetres. Webcam vertical
FOV, principal point and eye separation remain explicit assumptions. Calibration
fits pupil-to-head-local ray tangents and a bounded depth scale; it does not claim
an anatomical eyeball reconstruction. Validation is a later, untouched capture.
"""
from itertools import product
import numpy as np
from gaze_mapping import project_unbounded

POSE_SCALE=np.array([.14,.14,.18,.04,.04,.12])
HEAD_SCALE=np.array([.12,.12,.12,.05,.05,.15])


def head_rotation(head):
    y,x,z=np.asarray(head)[:3]
    rx=np.array([[1,0,0],[0,np.cos(x),-np.sin(x)],[0,np.sin(x),np.cos(x)]])
    ry=np.array([[np.cos(y),0,np.sin(y)],[0,1,0],[-np.sin(y),0,np.cos(y)]])
    rz=np.array([[np.cos(z),-np.sin(z),0],[np.sin(z),np.cos(z),0],[0,0,1]])
    c=np.diag([-1.,1.,-1.])
    return c@rz@ry@rx@c.T


def eye_origin(head,depth,reference_width,aspect,camera_aspect=16/9,eye_side="right",vertical_fov_degrees=45.):
    # Same unmirrored camera/screen convention as AngleGeometry in the native UI.
    d=depth*np.exp(np.clip(reference_width-head[5],-.7,.7))
    fy=.5/np.tan(np.deg2rad(vertical_fov_degrees)/2);fx=fy/camera_aspect
    middle=np.array([-(head[3]-.5)*d/fx,
                     .5/aspect+.7/30.2+(.5-head[4])*d/fy,d])
    return middle+head_rotation(head)@np.array([(-1 if eye_side == "left" else 1)*3.2/30.2,0,0])


def screen_point(target,aspect):
    return np.array([target[0]-.5,(.5-target[1])/aspect,0.])


def motion_coverage(samples):
    """Report rotation and translation evidence separately, without inventing axes.

    Regress translation features against rotation first: apparent movement tied
    only to a turn is not independent evidence for a lateral/depth shift.
    """
    if len(samples)<8:return {'rotation':False,'translation':False}
    heads=np.array([s[2] for s in samples])
    normalized=(heads-np.median(heads,axis=0))/POSE_SCALE
    rotation=np.max(np.ptp(np.percentile(normalized[:,:3],[5,95],axis=0),axis=0))>=.4
    design=np.column_stack((np.ones(len(heads)),normalized[:,:3]))
    translation=normalized[:,3:]-design@np.linalg.lstsq(design,normalized[:,3:],rcond=None)[0]
    shifted=np.max(np.ptp(np.percentile(translation,[5,95],axis=0),axis=0))>=.35
    return {'rotation':bool(rotation),'translation':bool(shifted)}


class GeometricGazeMap:
    def __init__(self,base,head_fit,aspect,camera_aspect,eye_side="right"):
        self.eye_side=eye_side
        self.base=base;self.head_fit=head_fit;self.aspect=aspect;self.camera_aspect=camera_aspect
        self.reference=np.array(head_fit.reference,copy=True)
        self.head_coefficients=np.array(head_fit.coefficients,copy=True)
        self.error=None;self.validation_error=None

    def raw_eye(self,point,pose):
        return np.asarray(point)+(pose-self.reference)/HEAD_SCALE@self.head_coefficients

    def correct_eye(self,raw,pose):
        return np.asarray(raw)-(pose-self.reference)/HEAD_SCALE@self.head_coefficients

    @classmethod
    def fit(cls,base,head_fit,seeds,samples,aspect,camera_aspect=16/9,eye_side="right",robust=False):
        # Every seed is one entire center/corner fixation; motion is reduced to
        # time blocks so correlated frames cannot dominate the five screen anchors.
        if len(seeds)<5 or len(samples)<30:
            raise ValueError('Need five screen anchors and more paired head-motion samples')
        targets=np.array([s[2] for s in seeds])
        if np.min(np.ptp(targets,axis=0))<.5 or np.linalg.cond(np.cov(targets.T))>20:
            raise ValueError('Save cursor positions across both sides and the top and bottom first')
        heads=np.array([s[2] for s in samples])
        span=np.ptp(np.percentile(heads,[5,95],axis=0),axis=0)
        if np.max(span/POSE_SCALE)<.5:
            raise ValueError('No clear head movement captured; try a gentle turn while watching the dot')
        groups={}
        for stamp,eye,head,target in samples:
            groups.setdefault(int((stamp-samples[0][0])/.4),[]).append((eye,head,target))
        blocks=[tuple(np.median([p[k] for p in block],axis=0) for k in range(3)) for block in groups.values()]
        if len(blocks)<10:raise ValueError('Too few fresh paired samples during the head movement')
        data=list(seeds)+blocks
        eyes=np.array([p[0] for p in data]);poses=np.array([p[1] for p in data]);targets=np.array([p[2] for p in data])
        if not np.isfinite(np.r_[eyes.ravel(),poses.ravel(),targets.ravel()]).all():raise ValueError('Invalid paired geometry')
        model=cls(base,head_fit,aspect,camera_aspect,eye_side)
        model.eye_center=np.median(eyes[:len(seeds)],axis=0)
        model.eye_scale=np.maximum(np.ptp(eyes[:len(seeds)],axis=0),.02)
        design=np.column_stack((np.ones(len(eyes)),(eyes-model.eye_center)/model.eye_scale))
        if np.linalg.matrix_rank(design)<3 or np.linalg.cond(design)>100:
            raise ValueError('Screen anchors do not establish two eye directions')
        weights=np.r_[np.full(len(seeds),len(blocks)/len(seeds)),np.ones(len(blocks))]
        rotations=np.array([head_rotation(h) for h in poses])
        model.reference_width=float(np.median(poses[:len(seeds),5]))
        best=None;max_retained=0.;best_motion_error=float("inf")
        # The installed webcam's lens is not calibrated. Fit a bounded effective
        # FOV jointly with depth instead of forcing every camera to 45 degrees.
        # This remains estimated geometry and must pass untouched later samples.
        for fov,depth in product((45.,30.,60.,75.),np.linspace(.65,3.3,38)):
            origins=np.array([eye_origin(h,depth,model.reference_width,aspect,camera_aspect,eye_side,fov) for h in poses])
            world=np.array([screen_point(t,aspect) for t in targets])-origins
            local=np.einsum('nji,nj->ni',rotations,world)
            if np.any(local[:,2]>=-.1):continue
            tangents=local[:,:2]/-local[:,2,None]
            effective=weights.copy()
            for _ in range(5 if robust else 1):
                coefficient=np.linalg.solve(design.T@(effective[:,None]*design)+np.diag([1e-8,.0001,.0001]),
                                            design.T@(effective[:,None]*tangents))
                local_fit=np.column_stack((design@coefficient,-np.ones(len(design))))
                world_fit=np.einsum('nij,nj->ni',rotations,local_fit)
                valid=world_fit[:,2]/np.linalg.norm(world_fit,axis=1)<-.05
                intersections=origins-world_fit*(origins[:,2]/np.minimum(world_fit[:,2],-.001))[:,None]
                prediction=np.column_stack((intersections[:,0]+.5,.5-intersections[:,1]*aspect))
                errors=np.linalg.norm(prediction-targets,axis=1)
                errors[~valid]=10.
                if robust:
                    motion_errors=errors[len(seeds):]
                    median=np.median(motion_errors)
                    mad=1.4826*np.median(np.abs(motion_errors-median))
                    cutoff=min(.08,max(.025,median+3*mad))
                    effective=weights*np.minimum(1.,cutoff/np.maximum(errors,1e-6))**2
                    effective[:len(seeds)]=weights[:len(seeds)]
            if not robust and not np.all(valid):continue
            kept=errors[len(seeds):]<=cutoff if robust else np.ones(len(blocks),dtype=bool)
            max_retained=max(max_retained,float(np.mean(kept)))
            best_motion_error=min(best_motion_error,float(np.percentile(errors[len(seeds):],80)))
            if robust and (np.sum(kept)<10 or np.mean(kept)<.7):continue
            score=float(np.mean(errors[:len(seeds)]**2)+np.mean(errors[len(seeds):][kept]**2))
            if best is None or score<best[0]:best=(score,float(depth),coefficient.copy(),errors,kept,float(fov))
        if best is None:raise ValueError(f'Geometric model retained at most {max_retained:.0%} of motion blocks; needs 70%. Best movement error {best_motion_error:.3f} UV')
        _,model.depth,model.coefficients,errors,kept,model.vertical_fov_degrees=best
        selected=np.r_[np.ones(len(seeds),dtype=bool),kept]
        model.fit_metrics={"motion_blocks":len(blocks),"retained_blocks":int(np.sum(kept)),"rejected_blocks":int(np.sum(~kept)),"effective_vertical_fov_degrees":model.vertical_fov_degrees,"estimated_optics":True}
        if np.max(errors[:len(seeds)])>.08 or np.percentile(errors[len(seeds):][kept],80)>.08:
            raise ValueError('Eye rays and known targets disagree; the previous map is kept')
        model.error=float(np.percentile(errors[selected],80))
        model.bounds=np.percentile(poses[selected],[2,98],axis=0)
        model.eyes=np.array([model.correct_eye(e,h) for e,h,_ in seeds])
        return model

    def ray(self,raw,pose):
        raw,pose=np.asarray(raw),np.asarray(pose)
        if raw.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[raw,pose]).all():return None
        q=np.r_[1.,(raw-self.eye_center)/self.eye_scale]@self.coefficients
        direction=head_rotation(pose)@np.r_[q,-1.]
        direction/=np.linalg.norm(direction)
        origin=eye_origin(pose,self.depth,self.reference_width,self.aspect,self.camera_aspect,self.eye_side,getattr(self,"vertical_fov_degrees",45.))
        if direction[2]>=-.05:return None
        point=origin-direction*origin[2]/direction[2]
        uv=np.array([point[0]+.5,.5-point[1]*self.aspect])
        return origin,direction,uv

    def project_raw(self,raw,pose):
        pose=np.asarray(pose)
        if pose.shape!=(6,) or not np.isfinite(pose).all():return None
        if np.any(pose<self.bounds[0]-.5*POSE_SCALE) or np.any(pose>self.bounds[1]+.5*POSE_SCALE):return None
        return self.evaluate_raw(raw,pose)

    def evaluate_raw(self,raw,pose):
        """Held-out evaluation does not inherit the training coverage gate."""
        ray=self.ray(raw,pose)
        return ray[2] if ray is not None else None

    def project_pose_unbounded(self,point,pose,baseline_allowed=True):
        point,pose=np.asarray(point),np.asarray(pose)
        if point.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[point,pose]).all():return None
        if np.all((pose>=self.bounds[0]-.5*POSE_SCALE)&(pose<=self.bounds[1]+.5*POSE_SCALE)):
            return self.project_raw(self.raw_eye(point,pose),pose)
        # Only the old model's supported region remains valid beyond measured poses.
        if hasattr(self.base,'project_pose_unbounded'):
            return self.base.project_pose_unbounded(point,pose,baseline_allowed)
        return project_unbounded(self.base,point) if baseline_allowed else None

    def project_unbounded(self,point):return self.project_pose_unbounded(point,self.reference)
    def project(self,point):
        uv=self.project_unbounded(point)
        return uv.tolist() if uv is not None and np.all((uv>=0)&(uv<=1)) else None

    def geometry(self):
        return {'eye_side':self.eye_side,'depth_screen_widths':self.depth,'reference_log_face_width':self.reference_width,
                'camera_aspect':self.camera_aspect,'screen_aspect':self.aspect,
                'vertical_fov_degrees':getattr(self,'vertical_fov_degrees',45.),'eye_separation_screen_widths':6.4/30.2,
                'assumed_optics':True,'validation_error_uv':self.validation_error,
                'checked_motion':getattr(self,'checked_motion',{'rotation':False,'translation':False})}


class FixedTargetCalibration:
    TRAIN_SECONDS=10.
    CHECK_SECONDS=5.
    def __init__(self,base,head_fit,seeds,aspect,camera_aspect,now,eye_side="right"):
        self.eye_side=eye_side
        self.base_mapping=base;self.head_fit=head_fit;self.seeds=seeds
        self.aspect=aspect;self.camera_aspect=camera_aspect
        self.started=now;self.paused_elapsed=None;self.phase='collect'
        self.samples=[];self.validation=[];self.candidate=None;self.result=None
        self.last_stamp=None;self.applied=False;self.accepted=False
        self.message='Watch the fixed dot; gently turn your head left/right.'
        self.validation_error=None;self.baseline_error=None
        self.checked_motion={'rotation':False,'translation':False}

    @property
    def done(self):return self.phase in ('complete','failed')
    def elapsed(self,now):return self.paused_elapsed if self.paused_elapsed is not None else max(0.,now-self.started)
    def pause(self,now):self.paused_elapsed=self.elapsed(now)
    def resume(self,now):
        if self.paused_elapsed is not None:self.started=now-self.paused_elapsed
        self.paused_elapsed=None;self.last_stamp=None
        self.message=('Keep watching the dot and moving gently; checking fresh measurements.' if self.phase=='validate'
                      else 'Watch the fixed dot; gently turn or shift your head. No required direction.')
    def progress(self,now):return min(1.,self.elapsed(now)/(self.TRAIN_SECONDS+self.CHECK_SECONDS))

    def observe(self,observation,stamp,now):
        self.accepted=False
        if self.done or self.paused_elapsed is not None:return
        self.tick(now)
        if self.done or observation is None:return
        raw,pose=observation
        if self.last_stamp is not None and stamp<=self.last_stamp:return
        if not 0<=now-stamp<=.15:return
        # Late frames from the training interval cannot leak into validation.
        if self.phase=='validate' and stamp<self.started+self.TRAIN_SECONDS:return
        self.last_stamp=stamp
        if not np.isfinite(np.r_[raw,pose]).all():return
        self.accepted=True
        sample=(stamp,np.array(raw,copy=True),np.array(pose,copy=True),np.array([.5,.5]))
        if self.phase=='collect':self.samples.append(sample)
        else:self.validation.append(sample)

    def motion_hint(self,now):
        elapsed=self.elapsed(now)
        turning=elapsed<self.TRAIN_SECONDS/2 if self.phase=='collect' else elapsed<self.TRAIN_SECONDS+self.CHECK_SECONDS/2
        return 'turn' if turning else 'shift'

    def tick(self,now):
        if self.done or self.paused_elapsed is not None:return
        elapsed=self.elapsed(now)
        self.message=('Watch the fixed dot; gently turn your head left/right.' if self.motion_hint(now)=='turn' else
                      'Keep facing forward; slide your head side to side while watching the dot.')
        if self.phase=='collect' and elapsed>=self.TRAIN_SECONDS:
            try:
                self.candidate=GeometricGazeMap.fit(self.base_mapping,self.head_fit,self.seeds,self.samples,self.aspect,self.camera_aspect,self.eye_side)
                self.phase='validate';self.message='Keep watching the dot and moving gently; checking fresh measurements.'
            except ValueError as error:
                self.phase='failed';self.message=str(error);return
        if self.phase=='validate' and elapsed>=self.TRAIN_SECONDS+self.CHECK_SECONDS:
            if len(self.validation)<15 or self.validation[-1][0]-self.validation[0][0]<2:
                self.phase='failed';self.message='Too few fresh checking samples. Previous calibration kept.';return
            poses=np.array([p[2] for p in self.validation])
            if np.max(np.ptp(np.percentile(poses,[5,95],axis=0),axis=0)/POSE_SCALE)<.2:
                self.phase='failed';self.message='No head movement during the check. Previous calibration kept.';return
            errors=[];baseline=[]
            for _,eye,pose,target in self.validation:
                uv=self.candidate.project_raw(eye,pose)
                errors.append(np.linalg.norm(uv-target) if uv is not None else 10.)
                corrected=self.head_fit.correct(eye,pose,enforce_bounds=False)
                if hasattr(self.base_mapping,'project_pose_unbounded'):
                    old=self.base_mapping.project_pose_unbounded(corrected,pose,True)
                else:old=project_unbounded(self.base_mapping,corrected)
                baseline.append(np.linalg.norm(old-target) if old is not None else 10.)
            self.validation_error=float(np.percentile(errors,80));self.baseline_error=float(np.percentile(baseline,80))
            if self.validation_error>.06 or self.validation_error>max(.015,self.baseline_error*.85):
                self.phase='failed';self.message='The fresh check did not improve enough. Previous calibration kept.';return
            # Validation samples never train this candidate. Keep its coefficients frozen.
            self.result=self.candidate;self.result.validation_error=self.validation_error
            checked=np.vstack((self.candidate.bounds,poses[np.asarray(errors)<=.06]))
            self.result.bounds=np.array([checked.min(axis=0),checked.max(axis=0)])
            trained=motion_coverage(self.samples);checked=motion_coverage(self.validation)
            self.checked_motion={k:trained[k] and checked[k] for k in trained}
            self.result.checked_motion=self.checked_motion.copy()
            self.applied=True;self.phase='complete'
            self.message=('Head rotation and translation checked and applied.' if all(self.checked_motion.values()) else
                          'Rotation checked; translation still needs a separate check.' if self.checked_motion['rotation'] else
                          'Translation checked; rotation still needs a separate check.' if self.checked_motion['translation'] else
                          'Observed head motion checked; separate turns and shifts need more coverage.')

    def state(self,now):
        return {'phase':'paused' if self.paused_elapsed is not None else self.phase,
                'message':'Head calibration stopped; captured samples are kept.' if self.paused_elapsed is not None else self.message,
                'training_samples':len(self.samples),
                'checking_samples':len(self.validation),'progress':self.progress(now),
                'remaining_seconds':max(0.,self.TRAIN_SECONDS+self.CHECK_SECONDS-self.elapsed(now)),
                'validation_error_uv':self.validation_error,'baseline_error_uv':self.baseline_error,
                'applied':self.applied,'motion_hint':self.motion_hint(now),
                'training_motion':motion_coverage(self.samples),'checking_motion':motion_coverage(self.validation),
                'checked_motion':self.checked_motion}
