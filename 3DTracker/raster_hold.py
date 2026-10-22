"""Brief display continuity supported by unchanged pixels, never training data."""
from copy import deepcopy
import cv2
import numpy as np


class RasterHold:
    def __init__(self, duration=.12):
        self.duration=duration;self.reset()

    def reset(self):
        self.reference=None;self.result=None;self.stamp=None;self.bounds=None

    def update(self,frame,result,stamp,threshold):
        if result and 'display_hold' in result:
            result={k:v for k,v in result.items() if k!='display_hold'}
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY) if frame.ndim==3 else frame
        if self.stamp is not None and (stamp<=self.stamp or gray.shape!=self.reference.shape):self.reset()
        reliable=bool(result and result.get('pupil_ellipse') and result.get('confidence',0)>=max(.6,threshold)
                      and result.get('temporal_tracking',{}).get('accepted',True))
        if reliable:
            pupil=result['pupil_ellipse'];center=np.asarray(pupil['center']);axes=np.asarray(pupil['axes'])
            radius=max(12.,float(max(axes))*.8)
            x,y=center;h,w=gray.shape
            bounds=(max(0,int(x-radius)),max(0,int(y-radius)),min(w,int(x+radius)),min(h,int(y+radius)))
            if min(bounds[2]-bounds[0],bounds[3]-bounds[1])<16:self.reset();return result
            self.reference=gray.copy();self.result=deepcopy(result);self.stamp=stamp;self.bounds=bounds
            return result
        if self.stamp is None or not 0<stamp-self.stamp<=self.duration:return result
        x0,y0,x1,y1=self.bounds
        old=self.reference[y0:y1,x0:x1].astype(float);new=gray[y0:y1,x0:x1].astype(float)
        # Only the pupil neighbourhood counts. A static background must never
        # hide a blink or a saccade. Exclude tiny saturated IR glints, not edges.
        mask=(old<240)&(new<240)
        if np.mean(mask)<.8:return result
        delta=(new-old)[mask];offset=np.median(delta)
        difference=np.abs(delta-offset)
        if abs(offset)>8 or np.mean(difference)>3 or np.percentile(difference,90)>10:return result
        held=deepcopy(self.result)
        held.pop('display_hold',None)
        held['measured_at']=self.stamp;held['held_until']=self.stamp+self.duration
        held['eye_model_updated']=False
        output=dict(result or {})
        output['display_hold']=held
        return output
