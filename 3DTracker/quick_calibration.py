"""Finite screen anchors for an initial approximate map, not an accuracy exam."""
import numpy as np

TARGETS=np.array([[.5,.5],[.08,.08],[.92,.08],[.92,.92],[.08,.92]])
TRAVEL=.55
SETTLE=.2
CAPTURE=1.2
STEP=TRAVEL+SETTLE+CAPTURE
DURATION=4*STEP
MAX_CORNER_SECONDS=8.


def append_fixation(block, eye, stamp):
    """Keep only a contiguous, settled fixation in normalized IR coordinates.

    Stability is sample quality, never proof that the user watched the target.
    Thresholds correspond to roughly four pixels in the 640x480 IR frame.
    """
    if block:
        dt=stamp-block[-1][0]
        jump=np.linalg.norm(eye-block[-1][1])
        if dt>.15 or jump>max(.004,.25*dt):block.clear()
    block.append((stamp,eye.copy()))
    if np.linalg.norm(np.ptp([p[1] for p in block],axis=0))>.006:
        block[:]=[(stamp,eye.copy())]


def target_at(elapsed):
    elapsed=max(0.,elapsed)
    index=min(3,int(elapsed/STEP))
    t=min(1.,(elapsed-index*STEP)/TRAVEL)
    t=t*t*(3-2*t)
    return (TARGETS[index]*(1-t)+TARGETS[index+1]*t).tolist()


class AnchorMap:
    """Piecewise interpolation through center and four measured corner anchors."""
    def __init__(self,eyes):
        self.eyes=np.asarray(eyes,dtype=float)
        if self.eyes.shape!=(5,2) or not np.isfinite(self.eyes).all():
            raise ValueError('Need clear eye samples at the center and four corners')
        self.span=np.ptp(self.eyes,axis=0)
        if np.min(self.span)<.012:raise ValueError('Eye positions are too similar to map the screen')
        self.triangles=[]
        signs=[]
        for i in range(4):
            indices=[0,i+1,(i+1)%4+1]
            source=self.eyes[indices]
            matrix=np.column_stack((source[1]-source[0],source[2]-source[0]))
            determinant=np.linalg.det(matrix)
            if abs(determinant)<.00001:raise ValueError('Corner eye positions overlap. Retry step 2 while following each dot.')
            signs.append(np.sign(determinant))
            self.triangles.append((source,np.linalg.inv(matrix),TARGETS[indices]))
        if len(set(signs))!=1:raise ValueError('Corner eye positions cross. Retry step 2 while following each dot.')
        self.error=None

    def project_unbounded(self,point):
        p=np.asarray(point,dtype=float)
        if p.shape!=(2,) or not np.isfinite(p).all():return None
        candidates=[]
        for source,inverse,targets in self.triangles:
            xy=inverse@(p-source[0])
            weights=np.r_[1-xy.sum(),xy]
            penalty=np.maximum(-weights,0).sum()
            candidates.append((penalty,weights@targets))
        return min(candidates,key=lambda item:item[0])[1]

    def project(self,point):
        uv=self.project_unbounded(point)
        return uv.tolist() if uv is not None and np.all((uv>=0)&(uv<=1)) else None


class QuickCalibration:
    def __init__(self,center,started_at):
        self.center=np.asarray(center,dtype=float)
        self.started_at=started_at
        self.blocks=[[],[],[],[]]
        self.last_stamp=None
        self.fit_status='Look at each dot briefly; the pass ends automatically'
        self.fit_attempted=False
        self.error=None
        self.index=0
        self.corner_started_at=started_at
        self.finished=False
        self.timed_out=False
        self.rejections={}
        self.advance_allowed=True

    @staticmethod
    def ready(block):
        return len(block)>=6 and block[-1][0]-block[0][0]>=.3

    def advance(self,now):
        if self.finished or self.timed_out:return
        block=self.blocks[self.index]
        if now-self.corner_started_at>=STEP and self.ready(block) and now-block[-1][0]<=.15 and self.advance_allowed:
            if self.index==3:self.finished=True
            else:
                self.index+=1
                self.corner_started_at=now
        elif now-self.corner_started_at>=MAX_CORNER_SECONDS:
            self.timed_out=True

    def retry(self,now):
        # A failed final fit needs new anchors; a missing corner retains all
        # earlier completed corners and resumes at the same target.
        if self.finished:
            self.blocks=[[],[],[],[]];self.index=0
        self.blocks[self.index]=[]
        self.started_at=now
        self.corner_started_at=now
        self.finished=False;self.timed_out=False;self.last_stamp=None
        self.rejections={}
        self.advance_allowed=True

    def target(self,now):
        return target_at(self.index*STEP+min(TRAVEL,max(0.,now-self.corner_started_at)))

    def reject(self,reason):
        self.rejections[reason]=self.rejections.get(reason,0)+1
        if not self.finished:self.blocks[self.index].clear()

    @property
    def samples(self):return [sample for block in self.blocks for sample in block]

    @property
    def coverage(self):return sum(self.ready(block) for block in self.blocks)

    def observe(self,eye,stamp,now):
        if self.last_stamp is not None and stamp<=self.last_stamp:return False
        if not 0<=now-stamp<=.15:
            self.reject('Eye frame delayed');return False
        self.advance(now)
        if self.finished or self.timed_out:return False
        elapsed=stamp-self.corner_started_at
        if elapsed<TRAVEL+SETTLE:return False
        index=self.index
        eye=np.asarray(eye,dtype=float)
        if eye.shape!=(2,) or not np.isfinite(eye).all():return False
        self.last_stamp=stamp
        append_fixation(self.blocks[index],eye,stamp)
        return True

    def progress_at(self,now):
        if self.finished:return 1.
        block=self.blocks[self.index]
        if not block:return 0.
        return min(1.,len(block)/6,(block[-1][0]-block[0][0])/.3,max(0.,now-self.corner_started_at)/STEP)

    def fit(self):
        self.fit_attempted=True
        if any(len(block)<6 or block[-1][0]-block[0][0]<.3 for block in self.blocks):
            missing=[str(i+1) for i,block in enumerate(self.blocks) if len(block)<6 or block[-1][0]-block[0][0]<.3]
            raise ValueError('Too few clear samples at corner '+', '.join(missing)+'. Retry step 2.')
        medians=[self.center]+[np.median([p[1] for p in block],axis=0) for block in self.blocks]
        mapping=AnchorMap(medians)
        # Check within-fixation repeatability, not whether a global affine model
        # can explain every eye position. Accuracy is refined with cursor anchors.
        errors=[]
        for target,block in zip(TARGETS[1:],self.blocks):
            for _,eye in block:
                errors.append(np.linalg.norm(mapping.project_unbounded(eye)-target))
        error=float(np.percentile(errors,80))
        if error>.20:raise ValueError('Eye samples jumped during the pass. Retry step 2 with your head still.')
        self.error=error;mapping.error=error
        self.fit_status='Initial map ready; refine with cursor alignment'
        return mapping
