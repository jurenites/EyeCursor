"""Known-target collection. No gaze prediction is consulted during capture."""
import numpy as np
from quick_calibration import TARGETS, append_fixation, QuickCalibration


class TargetCapture:
    """Each eye completes its own stable block while one known dot is visible."""
    def __init__(self,settled_at):
        self.settled_at=settled_at;self.blocks={};self.evidence={};self.completed={}
        self.identities={};self.accepted_sides=set()

    def observe(self,observations,now):
        accepted=False;self.accepted_sides=set()
        for side,obs in observations.items():
            stamp=obs['time'];eye=np.asarray(obs['eye']);head=np.asarray(obs['head'])
            if not 0<=now-stamp<=.15 or stamp<self.settled_at:continue
            if eye.shape!=(2,) or head.shape!=(6,) or not np.isfinite(np.r_[eye,head]).all():continue
            identity=obs.get('identity')
            if side in self.identities and self.identities[side]!=identity:
                self.blocks.pop(side,None);self.evidence.pop(side,None);self.completed.pop(side,None)
            self.identities[side]=identity
            if side in self.completed:continue
            block=self.blocks.setdefault(side,[])
            if block and stamp<=block[-1][0]:continue
            append_fixation(block,eye,stamp)
            evidence=self.evidence.setdefault(side,{})
            evidence[stamp]=dict(obs)
            self.evidence[side]={t:evidence[t] for t,_ in block}
            accepted=True;self.accepted_sides.add(side)
            if QuickCalibration.ready(block):
                self.completed[side]=[self.evidence[side][t] for t,_ in block]
        return accepted

    def progress(self,sides):
        return min((1. if side in self.completed else
                    min(1.,(self.blocks[side][-1][0]-self.blocks[side][0][0])/.3) if self.blocks.get(side) else 0.
                    for side in sides),default=0.)


class DotLearning:
    def __init__(self,now,sides):
        self.index=0;self.started=now;self.sides=set(sides)
        self.capture=TargetCapture(now+.8);self.rows=[];self.done=False
        self.accepted=False;self.reason='Look at the dot; keep your head comfortably still'

    @property
    def blocks(self):return self.capture.blocks

    @property
    def target(self):return TARGETS[self.index].tolist()

    def observe(self,observations,now):
        self.accepted=False
        if self.done:return
        self.accepted=self.capture.observe({s:o for s,o in observations.items() if s in self.sides},now)
        self.reason='Recording eye and face measurements' if self.accepted else 'Waiting for fresh eye and face measurements'

    def tick(self,now):
        if self.done:return
        ready=set(self.capture.completed)
        # Preserve each completed eye while the other settles at this same dot.
        # A disconnected camera gets a bounded wait, never fabricated samples.
        if ready!=self.sides and now-self.started<8.:return
        self.rows.append({'target':self.target,'eyes':dict(self.capture.completed)})
        if self.index==len(TARGETS)-1:self.done=True
        else:
            self.index+=1;self.started=now;self.capture=TargetCapture(now+.8);self.accepted=False
            self.reason='Follow the next dot'

    def state(self,now):
        progress=self.capture.progress(self.sides)
        return {'target_index':self.index+1,'target_count':len(TARGETS),'progress':progress,
                'remaining_seconds':max(0.,self.started+8.-now),'message':self.reason}
