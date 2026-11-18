"""Sequential known-target references over the two live IR previews.

The screen point is frozen by the native window, not predicted from gaze.
This records a fixation reference, not proof of camera/eyeball collinearity.
"""
import math


class PreviewReference:
    def __init__(self, sides):
        self.sides = [s for s in ('left', 'right') if s in sides]
        self.index = 0
        self.target = None
        self.started = None
        self.samples = []
        self.references = {}

    @property
    def eye(self):
        return self.sides[self.index] if self.index < len(self.sides) else None

    def set_target(self, eye, target, now):
        if eye != self.eye or self.target is not None:
            return
        if (not isinstance(target,list) or len(target)!=2 or
                not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in target)):
            raise ValueError('Preview marker must be on the calibration display')
        self.target=list(target);self.started=now

    def observe(self, observations, now):
        if self.started is None:return False
        row=observations.get(self.eye)
        if (row and row['time']>=self.started+2 and 0<=now-row['time']<=.15
                and (not self.samples or row['time']>self.samples[-1]['time'])):
            self.samples.append(dict(row))
            return True
        return False

    def ready(self, now):
        return (self.started is not None and now-self.started>=6 and len(self.samples)>=12
                and self.samples[-1]['time']-self.samples[0]['time']>=1)

    def advance(self):
        self.references[self.eye]={'target':self.target,'samples':self.samples}
        self.index+=1;self.target=None;self.started=None;self.samples=[]

    def state(self, now):
        elapsed=now-self.started if self.started is not None else 0
        return {'eye':self.eye,'target':self.target,'progress':min(1,elapsed/6,len(self.samples)/12),
                'remaining_seconds':max(0,6-elapsed),'completed':list(self.references)}
