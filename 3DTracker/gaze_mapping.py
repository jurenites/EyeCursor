"""Screen-space projection contracts, independent of camera capture and UI.

An unbounded estimate is evidence. Fencing is a presentation choice and must
never turn a lost/non-finite observation into a valid gaze sample.
"""
import numpy as np


def project_unbounded(mapping, point):
    if point is None:return None
    value=getattr(mapping,'project_unbounded',mapping.project)(point)
    if value is None:return None
    value=np.asarray(value,dtype=float)
    return value if value.shape==(2,) and np.isfinite(value).all() else None


def fence(uv,viewport,inset=8.):
    if uv is None:return None
    uv=np.asarray(uv,dtype=float)
    if uv.shape!=(2,) or not np.isfinite(uv).all():return None
    x,y,w,h=viewport
    margin=np.minimum(inset,np.array([w,h])/2)
    return (np.array([x,y])+np.clip(uv*np.array([w,h]),margin,np.array([w,h])-margin)).tolist()


def desktop_fence(point, viewports, inset=8.):
    """Stick to the outline of the display union, leaving shared seams open.

    Coordinates are macOS logical points. Empty desktop gaps are not screens.
    The inset keeps the whole dot visible at exposed edges.
    """
    if point is None or not viewports:return None
    point=np.asarray(point,dtype=float)
    if point.shape!=(2,) or not np.isfinite(point).all():return None
    candidates=[]
    for x,y,w,h in viewports:
        q=np.clip(point,[x,y],[x+w,y+h])
        mx,my=min(inset,w/2),min(inset,h/2)
        def covered(px,py):
            return any(a<=px<=a+c and b<=py<=b+d for a,b,c,d in viewports)
        lo_x=x if covered(x-.01,q[1]) else x+mx
        hi_x=x+w if covered(x+w+.01,q[1]) else x+w-mx
        lo_y=y if covered(q[0],y-.01) else y+my
        hi_y=y+h if covered(q[0],y+h+.01) else y+h-my
        candidates.append(np.clip(point,[lo_x,lo_y],[hi_x,hi_y]))
    return min(candidates,key=lambda q:float(np.sum((q-point)**2))).tolist()


class HeadResidualModel:
    """Learn head effects from repeat fixations at the same screen location.

Eye motion across different targets cannot teach a head coefficient. SVD keeps
unobserved head directions at zero, rather than guessing a full 6D transform.
These are screen residuals, not metric eye centers or camera extrinsics.
"""
    def __init__(self,anchors,residuals,scale):
        self.coefficients=np.zeros((6,2));self.support=np.zeros((6,6))
        self.rank=0;self.error=None
        self.status='insufficient_repeats';self.pair_count=0;self.fit_error=None
        rows=[];values=[]
        for i,(_,head,target) in enumerate(anchors):
            for j,(_,other,goal) in enumerate(anchors[:i]):
                delta=(head-other)/scale
                if np.linalg.norm(target-goal)<.04 and np.linalg.norm(delta)>.35:
                    rows.append(delta);values.append(residuals[i]-residuals[j])
        self.pair_count=len(rows)
        if len(rows)<3:return
        x,y=np.asarray(rows),np.asarray(values)
        _,s,vt=np.linalg.svd(x,full_matrices=False)
        basis=vt[s>max(.15,s[0]*.12)].T
        if not basis.size:
            self.status='insufficient_motion';return
        design=x@basis
        weights=np.ones(len(x))
        for _ in range(3):
            coefficients=np.linalg.solve(design.T@(weights[:,None]*design)+np.eye(basis.shape[1])*.015,
                                         design.T@(weights[:,None]*y))
            errors=np.linalg.norm(design@coefficients-y,axis=1)
            weights=np.minimum(1.,.04/np.maximum(errors,.0001))
        error=float(np.percentile(errors,90))
        self.fit_error=error
        if error>.08:
            self.status='inconsistent';return
        self.coefficients=basis@coefficients;self.support=basis@basis.T
        self.rank=basis.shape[1];self.error=error;self.status='learned'
