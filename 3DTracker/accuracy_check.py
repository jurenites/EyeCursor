"""Independent screen checks. These samples never fit or correct the gaze map."""
import numpy as np
from quick_calibration import append_fixation, QuickCalibration

CHECK_TARGETS=np.array([[.25,.25],[.75,.25],[.75,.75],[.25,.75],[.5,.32]])


class AccuracyCheck:
    TIMEOUT=8.
    def __init__(self,viewport,now):
        self.size=np.asarray(viewport[2:],dtype=float)
        self.index=0
        self.started=now
        self.block=[]
        self.predictions={}
        self.rows=[]
        self.last_stamp=None
        self.done=False
        self.status='checking'
        self.reason='Look at the dot and keep your head still'

    @property
    def target(self):return CHECK_TARGETS[self.index].tolist()

    def reject(self,reason):
        self.block.clear();self.predictions.clear();self.reason=reason

    def observe(self,eye,predicted,stamp,now):
        if self.done or (self.last_stamp is not None and stamp<=self.last_stamp):return False
        if not 0<=now-stamp<=.15:
            self.reject('Waiting for fresh eye measurements');return False
        if stamp-self.started<.8:return False
        eye=np.asarray(eye,dtype=float)
        if eye.shape!=(2,) or not np.isfinite(eye).all():
            self.reject('Eye measurement unavailable');return False
        predicted=np.asarray(predicted,dtype=float) if predicted is not None else None
        if predicted is not None and (predicted.shape!=(2,) or not np.isfinite(predicted).all()):predicted=None
        self.last_stamp=stamp
        append_fixation(self.block,eye,stamp)
        self.predictions={t:self.predictions[t] for t,_ in self.block if t in self.predictions}
        self.predictions[stamp]=predicted.copy() if predicted is not None else None
        self.reason='Hold at the dot; collecting a stable fixation'
        return True

    def tick(self,now):
        if self.done:return
        ready=QuickCalibration.ready(self.block) and now-self.block[-1][0]<=.15
        if not ready and now-self.started<self.TIMEOUT:return
        row={'target':self.target,'measured':None,'error_points':None,'precision_points':None,'samples':0,'captured_samples':len(self.block) if ready else 0}
        if ready:
            points=np.array([self.predictions[t] for t,_ in self.block if self.predictions[t] is not None])
        if ready and len(points)>=6:
            measured=np.median(points,axis=0)
            row.update(measured=measured.tolist(),samples=len(points),
                error_points=float(np.mean(np.linalg.norm((points-CHECK_TARGETS[self.index])*self.size,axis=1))),
                precision_points=float(np.sqrt(np.mean(np.sum(((points-measured)*self.size)**2,axis=1)))))
        self.rows.append(row)
        if self.index==len(CHECK_TARGETS)-1:
            self.done=True
            self.status='complete' if all(r['samples'] for r in self.rows) else 'incomplete'
        else:
            self.index+=1;self.started=now;self.reject('Look at the next dot')

    def state(self,now):
        errors=[r['error_points'] for r in self.rows if r['error_points'] is not None]
        return {'status':self.status,'target_index':self.index+1,'target_count':len(CHECK_TARGETS),'targets':CHECK_TARGETS.tolist(),
            'rows':self.rows,'mean_error_points':float(np.mean(errors)) if errors else None,
            'worst_error_points':float(max(errors)) if errors else None,
            'viewport_size':self.size.tolist(),'units':'screen points',
            'remaining_seconds':max(0.,self.started+self.TIMEOUT-now) if not self.done else 0.,
            'message':self.reason,'progress':min(1.,(self.block[-1][0]-self.block[0][0])/.3) if self.block else 0.}
