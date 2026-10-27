"""Empirical head correction when assumed camera optics cannot explain a capture.

Learn pupil displacement from head pose, NOT gaze from a constant target. The
screen map's response to eye movement is retained. A later capture must validate
any update; this model does not infer anatomical eye centers or metric depth.
"""
import numpy as np
from geometric_gaze import HEAD_SCALE, POSE_SCALE
from gaze_mapping import project_unbounded


class HeadMotionMap:
    def __init__(self,base,head_fit,seeds):
        self.base=base;self.head_fit=head_fit
        self.reference=np.array(head_fit.reference,copy=True)
        self.head_coefficients=np.array(head_fit.coefficients,copy=True)
        self.eye_center=np.asarray(seeds[0][0]);self.validation_error=None
        self.quadratic_interactions=True
        self.eyes=np.array([s[0] for s in seeds]);self.error=None

    def design(self,poses):
        x=(np.asarray(poses)-self.reference)/POSE_SCALE
        columns=[np.ones((*x.shape[:-1],1)),x]
        if self.degree==2:
            columns.append(x*x)
            if getattr(self,'quadratic_interactions',False):
                # Rotation and translation combine: independent axis squares
                # cannot represent yaw×shift or yaw×pitch counter-rotation.
                columns.append(np.stack([x[...,i]*x[...,j] for i in range(6) for j in range(i)],axis=-1))
        return np.concatenate(columns,axis=-1)

    def reference_project(self,point):
        if hasattr(self.base,'project_pose_unbounded'):
            return self.base.project_pose_unbounded(point,self.reference,True)
        return project_unbounded(self.base,point)

    @classmethod
    def fit(cls,base,head_fit,seeds,samples,*args,**kwargs):
        if len(samples)<60:raise ValueError('More paired head measurements are needed')
        model=cls(base,head_fit,seeds)
        # Known target -> reference pupil, interpolated from the existing screen
        # anchors. Never use the live predicted cursor as the training target.
        centers=[e for e,h,t in seeds if np.linalg.norm(np.asarray(t)-[.5,.5])<.04]
        if not centers:raise ValueError('Save a center fixation before head calibration')
        model.eye_center=np.median(centers,axis=0)
        # Preserve previously learned manual offsets: invert the reference map's
        # center instead of assuming an old pupil sample still maps to the center.
        for _ in range(10):
            prediction=model.reference_project(model.eye_center)
            if prediction is None:raise ValueError('Reference screen map has no center prediction')
            residual=np.asarray(prediction)-[.5,.5]
            if np.linalg.norm(residual)<.001:break
            jacobian=np.column_stack([(model.reference_project(model.eye_center+delta)-prediction)/.0001
                                      for delta in np.eye(2)*.0001])
            model.eye_center-=np.linalg.solve(jacobian,residual)
        if np.linalg.norm(model.reference_project(model.eye_center)-[.5,.5])>.02:
            raise ValueError('Reference screen center could not be recovered')
        groups={}
        for stamp,eye,pose,target in samples:
            if np.linalg.norm(np.asarray(target)-[.5,.5])>.04:continue
            groups.setdefault(int((stamp-samples[0][0])/.4),[]).append((eye,pose))
        blocks=[tuple(np.median([r[k] for r in g],axis=0) for k in range(2)) for g in groups.values()]
        if len(blocks)<16:raise ValueError('More independent head movement blocks are needed')
        eyes,poses=map(np.asarray,zip(*blocks))
        # Displacement includes any already established head compensation.
        y=eyes-model.eye_center-(poses-model.reference)/HEAD_SCALE@model.head_coefficients
        split=max(10,int(len(blocks)*.7));best=None
        def solve(x,y,ridge):
            weights=np.ones(len(y))
            for _ in range(6):
                c=np.linalg.solve(x.T@(weights[:,None]*x)+np.eye(x.shape[1])*ridge,x.T@(weights[:,None]*y))
                residual=np.linalg.norm(x@c-y,axis=1)
                weights=np.minimum(1.,.008/np.maximum(residual,1e-6))
            return c,residual
        for degree in (1,2):
            model.degree=degree;x=model.design(poses)
            for ridge in (.1,1.,10.,100.):
                c,_=solve(x[:split],y[:split],ridge)
                score=float(np.percentile(np.linalg.norm(x[split:]@c-y[split:],axis=1),80))
                if best is None or score<best[0]:best=(score,degree,ridge)
        model.degree=best[1];model.ridge=best[2]
        model.coefficients,residual=solve(model.design(poses),y,model.ridge)
        model.bounds=np.percentile(poses,[0,100],axis=0)
        model.fit_metrics={'model':'empirical_head_displacement','motion_blocks':len(blocks),
            'inner_check_pupil_error':best[0],'degree':model.degree,'ridge':model.ridge,
            'downweighted_blocks':int(np.sum(residual>.008)),
            'feature_schema':'head_quadratic_cross_v2'}
        return model

    def project_raw(self,raw,pose):
        raw,pose=np.asarray(raw),np.asarray(pose)
        if raw.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[raw,pose]).all():return None
        # Do not extrapolate a polynomial far beyond observed head positions.
        if np.any(pose<self.bounds[0]-.5*POSE_SCALE) or np.any(pose>self.bounds[1]+.5*POSE_SCALE):
            # A still-head map is not a valid substitute at an unseen head pose.
            # The caller may explicitly use it only inside its supported region.
            return None
        return self.evaluate_raw(raw,pose)

    def evaluate_raw(self,raw,pose):
        """Evaluate a held-out pose before deciding whether to extend support."""
        raw,pose=np.asarray(raw),np.asarray(pose)
        if raw.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[raw,pose]).all():return None
        corrected=raw-(pose-self.reference)/HEAD_SCALE@self.head_coefficients-self.design(pose)@self.coefficients
        return self.reference_project(corrected)

    def project_pose_unbounded(self,point,pose,baseline_allowed=True):
        pose=np.asarray(pose);raw=np.asarray(point)+(pose-self.reference)/HEAD_SCALE@self.head_coefficients
        prediction=self.project_raw(raw,pose)
        if prediction is not None:return prediction
        return project_unbounded(self.base,point) if baseline_allowed else None

    def project_unbounded(self,point):return self.project_pose_unbounded(point,self.reference)
    def project(self,point):
        value=self.project_unbounded(point)
        return value.tolist() if value is not None and np.all((value>=0)&(value<=1)) else None
