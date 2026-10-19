"""Continuous time-aligned moving-target capture, with independent fit validation."""
import math
from collections import defaultdict, deque
import numpy as np
from cursor_calibration import CursorMap

ENTRY = 2.
LAP = 32.
FIRST_PAIR_SECONDS = ENTRY + 2 * LAP


def circular_target(elapsed):
    """Large rectangular path; ease to zero speed at every corner and reversal."""
    elapsed=max(0.,elapsed)
    if elapsed<ENTRY:
        t=elapsed/ENTRY
        eased=t*t*(3-2*t)
        return [.5-.42*eased,.5-.42*eased]
    t=(elapsed-ENTRY)/LAP
    lap=math.floor(t)
    position=(t-lap)*4
    edge=min(3,int(position))
    fraction=position-edge
    eased=fraction*fraction*(3-2*fraction)
    corners=((.08,.08),(.92,.08),(.92,.92),(.08,.92))
    direction=1 if lap%2==0 else -1
    start=corners[(direction*edge)%4]
    end=corners[(direction*(edge+1))%4]
    return [a+(b-a)*eased for a,b in zip(start,end)]


class CircularCalibration:
    def __init__(self,center,started_at):
        self.center=np.asarray(center,dtype=float)
        self.started_at=started_at
        self.sample_bins=defaultdict(lambda:deque(maxlen=96))
        self.revision=0
        self.checked_revision=0
        self.last_check=-math.inf
        self.last_stamp=None
        self.error=None
        self.lag=None
        self.fit_status="Collecting path coverage"
        self.fit_attempted=False

    @property
    def samples(self):
        return [sample for bucket in self.sample_bins.values() for sample in bucket]

    @staticmethod
    def sector(elapsed):
        target=circular_target(elapsed)
        angle=math.atan2((target[1]-.5)/.42,(target[0]-.5)/.42)%(2*math.pi)
        return (int((elapsed-ENTRY)/LAP)%2,min(7,int(angle/(math.pi/4))))

    @property
    def coverage(self):return sum(len(bucket)>=3 for bucket in self.sample_bins.values())

    def ready_to_fit(self,now):
        if self.coverage<12 or self.revision==self.checked_revision or now-self.last_check<2:return False
        self.last_check=now;self.checked_revision=self.revision
        return True

    def observe(self,eye,stamp,now):
        if (self.last_stamp is not None and stamp<=self.last_stamp) or not 0<=now-stamp<=.15:return False
        elapsed=stamp-self.started_at
        eye=np.asarray(eye,dtype=float)
        if eye.shape!=(2,) or not np.isfinite(eye).all() or not math.isfinite(elapsed) or elapsed<ENTRY:return False
        self.last_stamp=stamp
        self.sample_bins[self.sector(elapsed)].append((elapsed,eye.copy()))
        self.revision+=1
        return True

    def groups(self,lag=0.):
        groups={}
        for elapsed,eye in self.samples:
            t=elapsed-lag
            if t<ENTRY:continue
            target=np.array(circular_target(t))
            key=self.sector(t)
            groups.setdefault(key,[]).append((eye,target))
        return {key:(np.median([p[0] for p in points],axis=0),np.median([p[1] for p in points],axis=0))
                for key,points in groups.items() if len(points)>=3}

    @property
    def progress(self):return self.coverage/16

    def fit(self):
        # Opposite directions and eased speed distinguish pursuit delay from
        # a rotated screen map. Select delay on training data only.
        self.fit_attempted=True
        self.error=None
        candidates=[]
        failures=[]
        for lag in np.arange(0,.301,.05):
            groups=self.groups(float(lag))
            if any(sum(key[0]==lap for key in groups)<6 for lap in (0,1)):continue
            training=[p for key,p in groups.items() if key[0]==0 or key[1]%2==1]
            validation=[p for key,p in groups.items() if key[0]==1 and key[1]%2==0]
            if len(validation)<3:continue
            training.append((self.center,np.array([.5,.5])))
            try:model=CursorMap([p[0] for p in training],[p[1] for p in training])
            except ValueError as error:
                failures.append(str(error));continue
            candidates.append((model.error,float(lag),model,validation))
        if not candidates:
            self.fit_status=('Eye movement too small to fit the screen' if any('too similar' in reason for reason in failures)
                             else 'Eye and target positions disagree; refining fit' if failures
                             else 'Collecting more sections in both directions')
            raise ValueError(self.fit_status)
        _,lag,model,validation=min(candidates,key=lambda p:p[0])
        errors=[]
        for eye,target in validation:
            prediction=model.project(eye)
            errors.append(np.linalg.norm(np.asarray(prediction)-target) if prediction is not None else 1.)
        error=float(np.percentile(errors,90))
        self.error=error;self.lag=lag
        if error>.10:
            self.fit_status=f'Consistency error {error:.0%}; needs 10% or less'
            raise ValueError(self.fit_status)
        self.fit_status='Screen fit passed'
        # Keep the independently validated model rather than refitting its holdout.
        return model
