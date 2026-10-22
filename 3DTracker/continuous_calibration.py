"""Explicit, continuous fixed-target learning with frozen future-data checks.

No learning from ordinary computer use. Camera observations are never targets.
All accepted samples remain in the audit; fitting uses a bounded recent window.
"""
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from geometric_gaze import GeometricGazeMap, motion_coverage
from gaze_mapping import project_unbounded
from head_motion_map import HeadMotionMap

def fit_head_candidate(*args,**kwargs):
    try:return GeometricGazeMap.fit(*args,**kwargs)
    except ValueError as error:
        model=HeadMotionMap.fit(*args,**kwargs)
        model.fit_metrics["geometric_rejection"]=str(error)
        return model



def pupil_shape_rejection(result):
    """Reject gross iris/pupil disagreement only when the iris has strong support.

    Round ellipses have no reliable orientation. We don't force the pupil to the
    iris shape or manufacture an observation through a blink or reflection.
    """
    pupil=result.get('pupil_ellipse');iris=result.get('iris_ellipse')
    if not pupil or not iris or result.get('iris_support',0)<.65:return None
    p=np.asarray(pupil.get('axes',[]),dtype=float);i=np.asarray(iris.get('axes',[]),dtype=float)
    if p.shape!=(2,) or i.shape!=(2,) or not np.isfinite(np.r_[p,i]).all() or min(*p,*i)<=0:return None
    pr=min(p)/max(p);ir=min(i)/max(i)
    if pr<ir*.55 and ir-pr>.3:return 'Pupil shape disagrees with the iris; possible reflection'
    if pr<.75 and ir<.75:
        pa=float(pupil.get('angle_degrees',0))+(90 if p[1]>p[0] else 0)
        ia=float(iris.get('angle_degrees',0))+(90 if i[1]>i[0] else 0)
        if abs((pa-ia+90)%180-90)>50:return 'Pupil and iris axes disagree; possible reflection'
    return None


class ContinuousTargetCalibration:
    continuous=True
    CHECK_SECONDS=4.
    MIN_SAMPLES=60
    MIN_SECONDS=8.
    RETRY_SECONDS=6.

    def __init__(self,base,head_fit,seeds,aspect,camera_aspect,now,eye_side='right',executor=None):
        self.base_mapping=base;self.fallback=base;self.head_fit=head_fit;self.seeds=seeds
        self.aspect=aspect;self.camera_aspect=camera_aspect;self.eye_side=eye_side
        self.started=now;self.paused_elapsed=None;self.phase='collect'
        self.samples=[];self.validation=[];self.candidate=None;self.result=None
        self.accepted=False;self.last_capture=None;self.last_stamp=None;self.applied=False
        self.revision=0;self.rejected=0;self.check_failures=0;self.total_samples=0
        self.fit_failures=0;self.last_fit_error=None
        self.validation_error=None;self.baseline_error=None;self.fit_metrics={}
        self.checked_motion={'rotation':False,'translation':False}
        self.message='Watch the center dot; move your head naturally. Stop when you want.'
        self.next_fit=now+self.MIN_SECONDS;self.validation_started=None
        self.executor=executor;self.future=None;self.training_snapshot=[]

    @property
    def done(self):return False  # Only the user's Stop ends capture.

    def elapsed(self,now):return self.paused_elapsed if self.paused_elapsed is not None else now-self.started

    def close(self):
        if self.future:self.future.cancel()
        if self.executor:self.executor.shutdown(wait=False,cancel_futures=True)
        self.future=None;self.executor=None

    def pause(self,now):
        self.paused_elapsed=self.elapsed(now);self.accepted=False
        self.close();self.candidate=None;self.validation=[];self.phase='collect'
        self.message=('Finished. The checked head correction is kept.' if self.applied else
                      'Finished without a new head correction. Previous screen calibration kept.')

    def resume(self,now):
        self.started=now-(self.paused_elapsed or 0);self.paused_elapsed=None
        self.last_stamp=None;self.next_fit=now+2
        self.message='Watch the center dot; continue moving your head naturally.'

    def progress(self,now):
        # This is an open-ended capture, not a finite percentage of completion.
        return 1. if self.applied else 0.

    def observe(self,observation,stamp,now):
        self.accepted=False;self.last_capture=None
        self.tick(now)
        if self.paused_elapsed is not None:return
        if observation is None:self.rejected+=1;return
        if (self.last_stamp is not None and stamp<=self.last_stamp) or not 0<=now-stamp<=.15:return
        raw,pose=map(np.asarray,observation)
        if raw.shape!=(2,) or pose.shape!=(6,) or not np.isfinite(np.r_[raw,pose]).all():return
        if self.phase=='validate' and stamp<self.validation_started:return
        self.last_stamp=stamp;self.accepted=True
        sample=(stamp,raw.copy(),pose.copy(),np.array([.5,.5]))
        kind='geometry-check' if self.phase=='validate' else 'geometry-training'
        (self.validation if self.phase=='validate' else self.samples).append(sample)
        self.total_samples+=1;self.last_capture=(kind,sample)
        # Full evidence is journaled by the owner; solver work/memory remain bounded.
        self.samples=[s for s in self.samples if now-s[0]<=120][-3600:]

    def _retry(self,now,message):
        self.phase='collect';self.candidate=None;self.validation=[]
        self.next_fit=now+self.RETRY_SECONDS;self.message=message

    def tick(self,now):
        if self.paused_elapsed is not None:return
        if self.phase=='fitting' and self.future is not None and self.future.done():
            try:
                self.candidate=self.future.result();self.fit_metrics=self.candidate.fit_metrics
            except (ValueError,np.linalg.LinAlgError) as error:
                self.fit_failures+=1;self.last_fit_error=str(error)
                self._retry(now,'Head movement captured, but the eye/head model did not fit. You can finish; previous calibration stays.')
            finally:self.future=None
            if self.candidate is not None:
                self.phase='validate';self.validation=[];self.validation_started=now
                self.message='Keep watching and moving naturally; checking fresh measurements.'
        if self.phase=='validate' and now-self.validation_started>=self.CHECK_SECONDS:
            self._check(now)
        if self.phase!='collect' or now<self.next_fit:return
        # Check readiness promptly; the retry backoff belongs to failed fits,
        # not an initial capture that is a fraction of a second short.
        self.next_fit=now+.25
        if (len(self.samples)<self.MIN_SAMPLES or now-self.samples[-1][0]>.25
                or self.samples[-1][0]-self.samples[0][0]<self.MIN_SECONDS):
            self.message='Keep watching the dot; collecting clear paired eye/head measurements.';return
        if not any(motion_coverage(self.samples).values()):
            self.message='Keep watching the dot while gently turning or shifting your head.';return
        if self.executor is None:self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='gaze-fit')
        self.training_snapshot=list(self.samples)
        self.future=self.executor.submit(fit_head_candidate,self.fallback,self.head_fit,self.seeds,
            self.training_snapshot,self.aspect,self.camera_aspect,self.eye_side,robust=True)
        self.phase='fitting';self.message='Keep watching the dot; fitting the collected movement.'

    def _check(self,now):
        rows=self.validation
        if len(rows)<15 or rows[-1][0]-rows[0][0]<2 or not any(motion_coverage(rows).values()):
            self.check_failures+=1;self._retry(now,'Check needs clearer head movement; keep watching and moving.');return
        errors=[];old_errors=[]
        for _,eye,pose,target in rows:
            prediction=self.candidate.project_raw(eye,pose)
            errors.append(np.linalg.norm(prediction-target) if prediction is not None else 10.)
            corrected=self.head_fit.correct(eye,pose,enforce_bounds=False)
            old=(self.base_mapping.project_pose_unbounded(corrected,pose,True)
                 if hasattr(self.base_mapping,'project_pose_unbounded') else project_unbounded(self.base_mapping,corrected))
            old_errors.append(np.linalg.norm(old-target) if old is not None else 10.)
        self.validation_error=float(np.percentile(errors,80));self.baseline_error=float(np.percentile(old_errors,80))
        # Validation outliers are NOT removed using the candidate's own residuals.
        # Otherwise looking away could be filtered into a false successful check.
        empirical=isinstance(self.candidate,HeadMotionMap)
        # An empirical correction may be useful before it is accurate enough for
        # pointing. Require substantial improvement throughout the fresh capture,
        # including its tail, and report remaining error rather than calling it accurate.
        improved=(self.validation_error<=.30 and self.validation_error<=self.baseline_error*.75
                  and np.median(errors)<=np.median(old_errors)
                  and np.percentile(errors,95)<=np.percentile(old_errors,95)) if empirical else (
                  self.validation_error<=.06 and self.validation_error<=max(.015,self.baseline_error*.85))
        if not improved:
            self.check_failures+=1;self._retry(now,'This check did not improve the fit. Keep watching; the previous fit stays.');return
        trained=motion_coverage(self.training_snapshot);checked=motion_coverage(rows)
        self.checked_motion={k:trained[k] and checked[k] for k in trained}
        self.result=self.candidate;self.result.validation_error=self.validation_error
        self.result.checked_motion=self.checked_motion.copy()
        checked_poses=np.asarray([row[2] for row,error in zip(rows,errors) if error<=.06])
        if len(checked_poses) and not empirical:
            self.result.bounds=np.array([np.minimum(self.result.bounds[0],np.min(checked_poses,axis=0)),
                                         np.maximum(self.result.bounds[1],np.max(checked_poses,axis=0))])
        self.base_mapping=self.result;self.applied=True;self.revision+=1
        # Future fitting may use this checked capture, but never the check that is
        # currently deciding whether to apply a frozen candidate.
        self.samples.extend(rows)
        self._retry(now,('Head drift reduced; more refinement needed. Continue or finish.' if self.validation_error>.06 else
                         'Checked fit applied. Continue exploring head positions, or stop.'))

    def state(self,now):
        return {'continuous':True,'phase':'paused' if self.paused_elapsed is not None else self.phase,
                'message':self.message,'remaining_seconds':0.,'elapsed_seconds':max(0.,self.elapsed(now)),
                'training_samples':len(self.samples),'checking_samples':len(self.validation),
                'total_samples':self.total_samples,'rejected_samples':self.rejected,
                'check_failures':self.check_failures,'fit_failures':self.fit_failures,
                'last_fit_error':self.last_fit_error,'applied_updates':self.revision,
                'fit_metrics':self.fit_metrics,'progress':self.progress(now),
                'validation_error_uv':self.validation_error,'baseline_error_uv':self.baseline_error,
                'applied':self.applied,'motion_hint':'free','checked_motion':self.checked_motion,
                'training_motion':motion_coverage(self.samples),'checking_motion':motion_coverage(self.validation)}
