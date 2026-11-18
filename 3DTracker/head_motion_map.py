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
        self.kernel_centers=None
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

    @staticmethod
    def kernel(x,centers,width):
        return np.exp(-np.sum((np.asarray(x)[...,None,:]-centers)**2,axis=-1)/(2*width**2))

    def displacement(self,pose):
        value=self.design(pose)@self.coefficients
        centers=getattr(self,'kernel_centers',None)
        if centers is not None:
            x=(np.asarray(pose)-self.reference)/POSE_SCALE
            value=value+self.kernel(x,centers,self.kernel_width)@self.kernel_coefficients
        return value

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
        # A single final 30% split held out mostly the last instructed motion
        # (turning), selecting a polynomial that could overfit depth/nodding.
        # Hold out 2s blocks throughout each 8s interval instead. These are all
        # TRAINING-cycle rows; the later full movement cycle stays untouched.
        times=np.array(list(groups))*.4
        folds=(times%8//2).astype(int)
        best=None;selection=[]
        def solve(x,y,ridge):
            weights=np.ones(len(y))
            for _ in range(6):
                c=np.linalg.solve(x.T@(weights[:,None]*x)+np.eye(x.shape[1])*ridge,x.T@(weights[:,None]*y))
                residual=np.linalg.norm(x@c-y,axis=1)
                weights=np.minimum(1.,.008/np.maximum(residual,1e-6))
            return c,residual
        normalized=(poses-model.reference)/POSE_SCALE
        def fit_candidate(indices,degree,ridge,width):
            model.degree=degree;x=model.design(poses[indices])
            if width is None:
                c,_=solve(x,y[indices],ridge)
                return c,None
            # A linear counter-rotation term plus a smooth local residual avoids
            # forcing every mounting/landmark error into global cross-products.
            c=np.linalg.solve(x.T@x+np.eye(x.shape[1])*.1,x.T@y[indices])
            k=model.kernel(normalized[indices],normalized[indices],width)
            beta=np.linalg.solve(k+np.eye(len(k))*ridge,y[indices]-x@c)
            return c,beta
        candidates=[(d,r,None) for d in (1,2) for r in (.1,1.,10.,100.)]
        candidates += [(1,r,w) for w in (.5,1.,2.,4.) for r in (.01,.1,1.)]
        for degree,ridge,width in candidates:
            errors=[]
            for fold in range(4):
                held=folds==fold;keep=~held
                if not held.any() or np.sum(keep)<8:continue
                c,beta=fit_candidate(keep,degree,ridge,width)
                prediction=model.design(poses[held])@c
                if beta is not None:
                    prediction+=model.kernel(normalized[held],normalized[keep],width)@beta
                # Select for screen error, not IR pixel error: the five-dot map
                # establishes a different gain for the two pupil coordinates.
                for measured,delta in zip(y[held],prediction):
                    uv=model.reference_project(model.eye_center+measured-delta)
                    errors.append(np.linalg.norm(uv-[.5,.5]) if uv is not None else 10.)
            if not errors:continue
            score=float(np.percentile(errors,80))
            selection.append(dict(degree=degree,ridge=ridge,kernel_width=width,error_p80_uv=score))
            if best is None or score<best[0]:best=(score,degree,ridge,width)
        if best is None:raise ValueError('More independent head movement blocks are needed for model selection')
        model.degree=best[1];model.ridge=best[2];model.kernel_width=best[3]
        model.coefficients,beta=fit_candidate(np.ones(len(poses),dtype=bool),model.degree,model.ridge,model.kernel_width)
        if beta is not None:
            model.kernel_centers=normalized.copy();model.kernel_coefficients=beta
        residual=np.linalg.norm(model.displacement(poses)-y,axis=1)
        model.bounds=np.percentile(poses,[0,100],axis=0)
        model.fit_metrics={'model':'empirical_head_displacement','motion_blocks':len(blocks),
            'inner_check_screen_error_p80_uv':best[0],'degree':model.degree,'ridge':model.ridge,
            'kernel_width':model.kernel_width,'selection_method':'four_blocked_folds_training_only',
            'selection_candidates':selection,
            'downweighted_blocks':int(np.sum(residual>.008)),
            'feature_schema':'head_displacement_blocked_v3'}
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
        corrected=raw-(pose-self.reference)/HEAD_SCALE@self.head_coefficients-self.displacement(pose)
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
