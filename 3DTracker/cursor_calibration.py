"""Explicit mouse-follow calibration. No samples are collected outside this mode."""
import numpy as np
from gaze_mapping import project_unbounded, HeadResidualModel


def motion_block_is_coherent(times, eyes, poses, pose_scale):
    """Permit smooth counter-rotation, but reject a jump hidden by a median.

    This is a short-window observation-quality check, never a target-error gate.
    Eye and head trajectories are independently checked against capture time.
    """
    times=np.asarray(times);eyes=np.asarray(eyes);poses=np.asarray(poses)
    if len(times)<6 or times[-1]-times[0]<.15:return False
    if np.any(np.diff(times)<=0):return False
    t=(times-times[0])/max(times[-1]-times[0],.001)
    design=np.column_stack((np.ones(len(t)),t))
    eye_error=eyes-design@np.linalg.lstsq(design,eyes,rcond=None)[0]
    head=poses/pose_scale
    head_error=head-design@np.linalg.lstsq(design,head,rcond=None)[0]
    return bool(np.max(np.linalg.norm(eye_error,axis=1))<.006 and
                np.max(np.linalg.norm(head_error,axis=1))<.15)


class CursorMap:
    def __init__(self, eyes, targets):
        eyes,targets=np.asarray(eyes,dtype=float),np.asarray(targets,dtype=float)
        if len(eyes)<6 or eyes.shape!=targets.shape or eyes.shape[1:]!=(2,):
            raise ValueError('Pause at six different screen positions')
        if not np.isfinite(eyes).all() or not np.isfinite(targets).all():
            raise ValueError('Invalid cursor samples')
        if np.min(np.ptp(targets,axis=0))<.5:
            raise ValueError('Visit both sides and the top and bottom of the screen')
        if np.linalg.cond(np.cov(targets.T))>20:
            raise ValueError('Spread positions across the screen, not along one line')
        design=np.column_stack((eyes,np.ones(len(eyes))))
        if np.linalg.matrix_rank(design)<3 or np.linalg.cond(design)>1000:
            raise ValueError('Eye positions are too similar; follow the mouse with your eyes')
        errors=[]
        for i in range(len(eyes)):
            keep=np.arange(len(eyes))!=i
            fit=np.linalg.lstsq(design[keep],targets[keep],rcond=None)[0]
            errors.append(np.linalg.norm(design[i]@fit-targets[i]))
        self.error=float(np.percentile(errors,90))
        if self.error>.10:
            raise ValueError('Eye and cursor samples disagree; pause and look at each position')
        self.coefficients=np.linalg.lstsq(design,targets,rcond=None)[0]
        self.bounds=np.array([eyes.min(axis=0)-.015,eyes.max(axis=0)+.015])

    def project_unbounded(self,point):
        p=np.asarray(point)
        if p.shape!=(2,) or not np.isfinite(p).all():return None
        return np.r_[p,1]@self.coefficients

    def project(self,point):
        uv=self.project_unbounded(point)
        return uv.tolist() if uv is not None and np.all((uv>=0)&(uv<=1)) else None


class ShiftedInputMap:
    """Keep an existing screen fit when the head model's reference changes."""
    def __init__(self,base,shift):self.base,self.shift=base,np.asarray(shift)
    def project(self,point):
        return None if point is None else self.base.project(np.asarray(point)+self.shift)
    def project_unbounded(self,point):
        return None if point is None else project_unbounded(self.base,np.asarray(point)+self.shift)
    def project_pose_unbounded(self,point,pose,baseline_allowed=True):
        if point is None:return None
        shifted=np.asarray(point)+self.shift
        if hasattr(self.base,'project_pose_unbounded'):
            return self.base.project_pose_unbounded(shifted,pose,baseline_allowed)
        return project_unbounded(self.base,shifted) if baseline_allowed else None
    @property
    def anchors(self):return [(eye-self.shift,head,target) for eye,head,target in getattr(self.base,'anchors',[])]


class CursorOffsetMap:
    """A measured correction to an existing fit, usable after one held target."""
    def __init__(self,base,points):
        offsets=[]
        for eye,target in points:
            predicted=base.project(eye)
            if predicted is None:raise ValueError('Visit more positions to rebuild the screen fit')
            offsets.append(np.asarray(target)-predicted)
        self.offset=np.median(offsets,axis=0)
        self.error=float(np.percentile(np.linalg.norm(offsets-self.offset,axis=1),90))
        if self.error>.06:raise ValueError('Collect more positions; one offset cannot explain this error')
        self.base=base
    def project(self,point):
        uv=self.project_unbounded(point)
        return uv.tolist() if uv is not None and np.all((uv>=0)&(uv<=1)) else None
    def project_unbounded(self,point):
        predicted=project_unbounded(self.base,point)
        return None if predicted is None else predicted+self.offset


class PoseAnchorMap:
    """Local corrections from explicit fixations; no learning from ordinary mouse use."""
    pose_scale=np.array([.14,.14,.18,.04,.04,.12])
    def __init__(self,base,anchors):
        self.base=base.base if isinstance(base,PoseAnchorMap) else base
        self.anchors=[(np.asarray(e),np.asarray(h),np.asarray(t)) for e,h,t in anchors][-100:]
        self.eye_scale=np.maximum(np.ptp(getattr(self.base,'eyes',[[0,0],[.16,.12]]),axis=0)*.45,.025)
        self.error=getattr(self.base,'error',None)
        for eye,head,target in self.anchors:
            if eye.shape!=(2,) or head.shape!=(6,) or target.shape!=(2,) or not np.isfinite(np.r_[eye,head,target]).all():
                raise ValueError('Invalid paired cursor anchor')
            if self.raw_project(eye,head) is None:raise ValueError('Move the pointer nearer an already mapped area')
        for i,(eye,head,target) in enumerate(self.anchors):
            for other,pose,goal in self.anchors[:i]:
                distance=np.linalg.norm(np.r_[(eye-other)/self.eye_scale,(head-pose)/self.pose_scale])
                if distance<.12 and np.linalg.norm(target-goal)>.18:
                    raise ValueError('This fixation conflicts with a saved anchor; keep looking at the pointer and retry')

        self.residuals=np.array([target-self.raw_project(eye,head) for eye,head,target in self.anchors])
        self.head_model=HeadResidualModel(self.anchors,self.residuals,self.pose_scale)

    def raw_project(self,point,pose=None):
        if pose is not None and hasattr(self.base,'project_pose_unbounded'):
            return self.base.project_pose_unbounded(point,pose,True)
        return project_unbounded(self.base,point)

    def project_unbounded(self,point):return self.raw_project(point)
    def project(self,point):return self.base.project(point)

    def project_pose_unbounded(self,eye,pose,baseline_allowed=True):
        eye,pose=np.asarray(eye),np.asarray(pose)
        if eye.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[eye,pose]).all():return None
        base=self.raw_project(eye,pose)
        if base is None:return None
        if not self.anchors:return base if baseline_allowed else None
        heads=np.array([p[1] for p in self.anchors])
        delta=(pose-heads)/self.pose_scale
        unsupported=delta@(np.eye(6)-self.head_model.support)
        nearest=float(np.min(np.linalg.norm(unsupported,axis=1)))
        # Extend only around measured poses or along learned head directions.
        within_observed=np.all((pose>=heads.min(axis=0)-self.pose_scale*.6)&
                               (pose<=heads.max(axis=0)+self.pose_scale*.6))
        if not baseline_allowed and (nearest>1 or not within_observed):return None
        eye_distance=np.array([np.linalg.norm((eye-p[0])/self.eye_scale) for p in self.anchors])
        distances=np.sqrt(eye_distance**2+np.sum(unsupported**2,axis=1))
        weights=1/np.maximum(distances,.0001)**2
        corrections=self.residuals+delta@self.head_model.coefficients
        correction=np.average(corrections,axis=0,weights=weights)
        # Preserve the learned screen bias throughout nearby eye positions. Only
        # an unobserved head direction fades it, not moving away from the mouse.
        strength=max(0.,min(1.,(1.4-nearest)/.6))
        return base+strength*correction

    def project_pose(self,eye,pose,baseline_allowed=True):
        uv=self.project_pose_unbounded(eye,pose,baseline_allowed)
        return uv.tolist() if uv is not None and np.all((uv>=0)&(uv<=1)) else None


class CursorCalibration:
    def __init__(self,base_mapping=None,viewport_size=(1000,1000)):
        self.active=False
        self.points=[]
        self.hold=[]
        self.target=None
        self.since=None
        self.target_since=None
        self.pose_revisit=False
        self.last_sample=None
        self.candidate=None
        self.base_mapping=base_mapping
        self.progress=0.
        self.stage='positions'
        self.head_cue=None
        self.message='Look at the stationary mouse for one second; then move it'
        self.pose_points=list(getattr(base_mapping,'anchors',[]))
        self.accepted=False
        self.saved_count=0
        self.fixed_target=None
        self.last_capture=[]
        self.viewport_size=np.asarray(viewport_size,dtype=float)

    @property
    def target_complete(self):
        return self.since is not None and getattr(self,'captured_since',None)==self.since and self.progress>=1

    def reset_fixation(self):
        self.target=None;self.since=None;self.target_since=None;self.captured_since=None
        self.pose_revisit=False
        self.hold=[];self.progress=0.;self.accepted=False

    def observe(self,target,eye,stamp,now,pose=None,evidence=None):
        self.accepted=False
        if not self.active:return
        target=np.asarray(target,dtype=float)
        if target.shape!=(2,) or not np.isfinite(target).all() or np.any((target<0)|(target>1)):
            self.reset_fixation();return
        # Ten screen-pixel diameter, measured in the same logical coordinates
        # as the native pointer. Compare with the saved point, not the last frame.
        if self.target is None or np.linalg.norm((target-self.target)*self.viewport_size)>5.:
            self.reset_fixation()
            self.target=target;self.since=now;self.target_since=now;self.hold=[];self.progress=0.
        if self.target_complete:
            reference=getattr(self,'captured_pose',None)
            valid_pose=pose is not None and np.shape(pose)==(6,) and np.isfinite(pose).all()
            if (valid_pose and reference is not None
                    and np.linalg.norm((pose-reference)/PoseAnchorMap.pose_scale)>.25):
                self.captured_since=None;self.since=now;self.hold=[];self.progress=0.
                self.pose_revisit=True
            else:
                # A saved reference stays successful through blinks, confidence
                # drops and duplicate frames. This is not a new camera sample.
                return
        if eye is None:
            if self.hold and now-self.hold[-1][0]>.25:self.hold=[];self.progress=0.
            return
        if self.target_since is None:self.target_since=self.since
        if stamp is None or not np.isfinite(stamp) or not 0<=now-stamp<=.15:return
        if (self.last_sample is not None and stamp<=self.last_sample) or now-self.target_since<.25:return
        eye=np.asarray(eye,dtype=float)
        if eye.shape!=(2,) or not np.isfinite(eye).all():self.hold=[];self.progress=0.;return
        if pose is not None:
            pose=np.asarray(pose,dtype=float)
            if pose.shape!=(6,) or not np.isfinite(pose).all():return
        self.accepted=True
        self.last_sample=stamp
        if self.hold and now-self.hold[-1][0]>.3:self.hold=[]
        self.hold.append((now,np.asarray(eye),pose,target.copy(),
                          dict(evidence or {},captured_at=stamp)))
        self.hold=[p for p in self.hold if now-p[0]<1.5]
        # A stationary known target is compatible with moving eyes and head.
        # Once the user has had time to acquire it, use short paired blocks rather
        # than demanding a full second of frozen pupils during counter-rotation.
        tail=[p for p in self.hold if now-p[0]<=.70]
        moving=(self.base_mapping is not None and pose is not None and len(tail)>=6 and
                all(p[2] is not None for p in tail) and
                (self.pose_revisit or np.linalg.norm((tail[-1][2]-tail[0][2])/PoseAnchorMap.pose_scale)>.12))
        dynamic=moving and now-self.target_since>=1.25
        capture=tail if dynamic else self.hold
        duration=.50 if dynamic else 1.
        self.progress=min(1,len(capture)/6,(now-capture[0][0])/duration)
        if len(capture)<6 or now-capture[0][0]<duration:return
        eyes=np.array([p[1] for p in capture])
        measured_pose=None
        if pose is not None:
            poses=np.array([p[2] for p in capture if p[2] is not None])
            if len(poses)!=len(capture):return
            measured_pose=np.median(poses,axis=0)
        if dynamic:
            if not motion_block_is_coherent([p[4]['captured_at'] for p in capture],eyes,poses,PoseAnchorMap.pose_scale):
                self.progress=0.;self.accepted=False
                self.message='Waiting for clear paired eye and head movement';return
        elif np.max(np.std(eyes,axis=0))>.008 or (measured_pose is not None and
                np.max(np.std(poses,axis=0)/PoseAnchorMap.pose_scale)>.25):
            self.progress=0.;self.accepted=False
            self.message='Keep watching the pointer; move your head gently';return
        self.capture_kind='head_motion' if dynamic else 'fixation'
        self.captured_pose=measured_pose
        nearby=next((i for i,p in enumerate(self.points) if np.linalg.norm(target-p[1])<.12),None)
        if nearby is not None:
            # Permit a deliberate revisit after moving away, but not repeated
            # samples at a stationary cursor silently reinforcing the same error.
            if getattr(self,'captured_since',None)==self.since:
                self.message='Move the mouse to another part of the screen';return
            self.points.pop(nearby)
        self.points.append((np.median(eyes,axis=0),target.copy()))
        self.target=target.copy()
        self.captured_since=self.since
        self.points=self.points[-40:]
        capture=list(capture)
        self.hold=[]
        self.last_capture=[]
        # A rejected new anchor cannot replace the previously accepted map.
        previous_candidate=self.candidate
        self.candidate=None
        try:
            if measured_pose is not None and self.base_mapping is not None:
                center=np.median(eyes,axis=0)
                anchors=[p for p in self.pose_points if not (np.linalg.norm(p[2]-target)<.08 and
                    np.linalg.norm((p[1]-measured_pose)/PoseAnchorMap.pose_scale)<.15)]
                anchors.append((center,measured_pose,target.copy()))
                self.candidate=PoseAnchorMap(self.base_mapping,anchors)
                self.pose_points=anchors[-100:]
            elif len(self.points)>=6:
                self.candidate=CursorMap([p[0] for p in self.points],[p[1] for p in self.points])
                if measured_pose is not None:
                    self.pose_points.append((np.median(eyes,axis=0),measured_pose,target.copy()))
                    self.candidate=PoseAnchorMap(self.candidate,self.pose_points)
            elif self.base_mapping is not None:
                self.candidate=CursorOffsetMap(self.base_mapping,self.points)
            else:raise ValueError('Pause at six different screen positions')
            self.saved_count+=1
            self.last_capture=capture
            self.progress=1.
            self.message='Saved. Keep watching the pointer and gently move your head, or stop learning.'
        except ValueError as error:
            self.candidate=previous_candidate
            if self.base_mapping is None and len(self.points)<6:
                if measured_pose is not None:
                    self.pose_points=[p for p in self.pose_points if not (np.linalg.norm(p[2]-target)<.12 and
                        np.linalg.norm((p[1]-measured_pose)/PoseAnchorMap.pose_scale)<.15)]
                    self.pose_points.append((np.median(eyes,axis=0),measured_pose,target.copy()))
                self.saved_count+=1;self.progress=1.
                self.last_capture=capture
                self.message=f'Position saved · {len(self.points)}/6; move to another part of the screen'
            else:
                self.captured_since=None;self.progress=0.;self.accepted=False
                self.message=str(error)

    def state(self):
        return {'active':self.active,'positions':len(self.points),'ready':self.candidate is not None,
                'message':self.message,'error':self.candidate.error if self.candidate else None,
                'remaining_seconds':getattr(self,'remaining_seconds',None),
                'stage':self.stage,'head_cue':self.head_cue,'progress':self.progress,
                'live_preview':bool(self.active and self.candidate is not None),
                'sample_accepted':self.accepted,'saved_anchors':len(self.pose_points) if self.pose_points else self.saved_count,
                'capture_kind':getattr(self,'capture_kind',None),
                'fixed_target':self.fixed_target,'target_complete':self.target_complete,
                'target_position':self.target.tolist() if self.target is not None else None}
