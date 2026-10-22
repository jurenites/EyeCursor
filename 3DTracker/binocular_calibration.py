"""Independent screen maps from simultaneous, explicitly labelled eye samples."""
import numpy as np
from quick_calibration import AnchorMap,TARGETS
from cursor_calibration import CursorMap,PoseAnchorMap
from continuous_calibration import ContinuousTargetCalibration
from gaze_mapping import project_unbounded
from dot_learning import TargetCapture


class SteadyReference:
    def __init__(self,reference):
        self.reference=np.asarray(reference);self.coefficients=np.zeros((6,2))
    def correct(self,eye,pose,enforce_bounds=True):return np.asarray(eye)


class BinocularCalibration:
    def __init__(self):
        self.identities={};self.rows={};self.maps={};self.seeds={};self.practices={};self.errors={}
        self.manual_points={};self.manual_hold={}
        self.onboarding_captures={}

    def close(self):
        for run in self.practices.values():run.close()

    def identity(self,side,identity):
        if self.identities.get(side)!=identity:
            old=self.practices.pop(side,None)
            if old:old.close()
            self.manual_points[side]={};self.manual_hold[side]=None
            self.rows[side]=[];self.maps.pop(side,None);self.seeds.pop(side,None)
            self.identities[side]=identity

    def record(self,observations,target,source,now,aspect,active_eye,fixation_id=None):
        for side,obs in observations.items():
            self.identity(side,obs['identity'])
            eye=np.asarray(obs['eye']);head=np.asarray(obs['head']);target=np.asarray(target)
            if source.startswith('geometry-'):
                # Selected eye is fitted by the owning onboarding workflow.
                if side==active_eye or side not in self.maps:continue
                run=self.practices.get(side)
                if run is None:
                    seeds=self.seeds[side]
                    run=ContinuousTargetCalibration(self.maps[side],SteadyReference(seeds[0][1]),seeds,
                        aspect,obs.get('camera_aspect',16/9),now,eye_side=side)
                    self.practices[side]=run
                if run.paused_elapsed is not None:run.resume(now)
                run.observe((eye,head),obs['time'],now)
                if run.result is not None:self.maps[side]=run.result
                continue
            if source in ('cursor','preview') and fixation_id and side in self.maps:
                hold=self.manual_hold.get(side)
                if hold is None or hold[0]!=fixation_id:hold=(fixation_id,[]);self.manual_hold[side]=hold
                hold[1].append((eye,head,target))
                if len(hold[1])>=3:
                    anchor=tuple(np.median([r[k] for r in hold[1]],axis=0) for k in range(3))
                    # Primary-eye acceptance does not prove companion stability.
                    if np.max(np.std([r[0] for r in hold[1]],axis=0))>.008:continue
                    points=dict(self.manual_points[side]);points[fixation_id]=anchor
                    points=dict(list(points.items())[-80:])
                    try:
                        mapping=PoseAnchorMap(self.maps[side],list(points.values()))
                        self.maps[side]=mapping;self.manual_points[side]=points
                        old=self.practices.pop(side,None)
                        if old:old.close()
                    except ValueError as error:self.errors[side]=str(error)
                continue
            if source not in ('onboarding','cursor','cursor-center','preview'):continue
            rows=self.rows.setdefault(side,[])
            if rows and obs['time']<=rows[-1][0]:continue
            rows.append((obs['time'],eye,head,target));self.rows[side]=rows[-2000:]
            # Onboarding is committed only after the primary capture chooses
            # its final stable windows. Earlier accepted frames can subsequently
            # be discarded by QuickCalibration and must not train the other eye.
            if source=='onboarding':continue
            # A fixation gets one vote; correlated frames do not dominate the fit.
            groups={}
            for _,e,h,t in self.rows[side]:groups.setdefault(tuple(np.round(t,3)),[]).append((e,h,t))
            seeds=[tuple(np.median([r[k] for r in g],axis=0) for k in range(3)) for g in groups.values() if len(g)>=3]
            if len(seeds)<5:continue
            try:
                ordered=[next((s for s in seeds if np.linalg.norm(s[2]-t)<.02),None) for t in TARGETS]
                if all(s is not None for s in ordered):
                    mapping=AnchorMap([s[0] for s in ordered]);seeds=ordered
                else:
                    mapping=CursorMap([s[0] for s in seeds],[s[2] for s in seeds])
                    # A center is necessary for a fixed-center movement fit.
                    seeds.sort(key=lambda s:np.linalg.norm(s[2]-[.5,.5]))
                # Do not overwrite a learned head map while collecting one new
                # fixation. Primary cursor corrections still use all saved anchors.
                if side not in self.practices:self.maps[side]=mapping;self.seeds[side]=seeds
                self.errors.pop(side,None)
            except ValueError as error:self.errors[side]=str(error)

    def collect_onboarding(self,observations,index,settled_at,now):
        capture=self.onboarding_captures.get(index)
        if capture is None or capture.settled_at!=settled_at:
            capture=TargetCapture(settled_at);self.onboarding_captures[index]=capture
        for side,obs in observations.items():self.identity(side,obs['identity'])
        capture.observe(observations,now)
        return set(capture.completed)

    def finish_onboarding(self,windows):
        """Fit separate eye maps from the same five known targets.

        Live capture uses each eye's independent completed block. Legacy log
        replay without those blocks retains its original interval selection.
        """
        for side,rows in self.rows.items():
            seeds=[]
            for index,(target,(start,end)) in enumerate(zip(TARGETS,windows)):
                if self.onboarding_captures:
                    capture=self.onboarding_captures.get(index)
                    samples=capture.completed.get(side,[]) if capture else []
                    candidates=[(r['time'],np.asarray(r['eye']),np.asarray(r['head']),target)
                                for r in samples if r.get('identity')==self.identities.get(side)]
                else:
                    candidates=[r for r in rows if start-.12<=r[0]<=end+.12
                                and np.linalg.norm(r[3]-target)<.02]
                if len(candidates)<6 or candidates[-1][0]-candidates[0][0]<.2:break
                center=np.median([r[1] for r in candidates],axis=0)
                residual=np.linalg.norm(np.asarray([r[1] for r in candidates])-center,axis=1)
                # Require a strong majority near the fixation median; a few
                # reflection-corrupted frames must not move its anchor. Use the
                # existing center-capture residual limit in normalized pixels.
                if np.mean(residual<=.012)<.75:break
                stable=[r for r,error in zip(candidates,residual) if error<=.012]
                if len(stable)<6:break
                seeds.append((np.median([r[1] for r in stable],axis=0),
                              np.median([r[2] for r in stable],axis=0),target.copy()))
            if len(seeds)!=5:
                self.errors[side]=f'Missing stable {side} samples at target {len(seeds)+1}'
                self.maps.pop(side,None);self.seeds.pop(side,None)
                continue
            try:
                self.maps[side]=AnchorMap([s[0] for s in seeds]);self.seeds[side]=seeds
                self.errors.pop(side,None)
            except ValueError as error:
                self.errors[side]=str(error);self.maps.pop(side,None);self.seeds.pop(side,None)

    def finish_head(self,now):
        for side,run in self.practices.items():
            if run.result is not None:self.maps[side]=run.result
            run.pause(now)

    def predict(self,side,observation):
        self.identity(side,observation['identity'])
        model=self.maps.get(side)
        if model is None:return None
        run=self.practices.get(side)
        if run is not None and run.result is not None:model=run.result;self.maps[side]=model
        eye,head=np.asarray(observation['eye']),np.asarray(observation['head'])
        if hasattr(model,'project_raw'):return model.project_raw(eye,head)
        if hasattr(model,'project_pose_unbounded'):return model.project_pose_unbounded(eye,head,True)
        # Initial companion fit is only supported near its measured head poses.
        poses=np.array([s[1] for s in self.seeds[side]])
        from geometric_gaze import POSE_SCALE
        if np.any(head<poses.min(axis=0)-POSE_SCALE) or np.any(head>poses.max(axis=0)+POSE_SCALE):return None
        return project_unbounded(model,eye)


def shared_fixation(predictions,aspect=1.):
    """A single screen fixation, with disagreement treated as model uncertainty.

    Agreement is necessary, not proof of accuracy. Agreeing calibrated positions
    have equal weight; detector confidence cannot choose the more accurate map.
    Raw per-eye estimates stay unchanged for calibration and audit.
    """
    valid={}
    for side,row in predictions.items():
        point=np.asarray(row.get('uv'),dtype=float)
        confidence=row.get('confidence',0.)
        if point.shape==(2,) and np.isfinite(point).all() and np.isfinite(confidence) and confidence>0:
            valid[side]=row
    if not valid:return {'status':'unavailable','uv':None,'sides':[],'disagreement':None}
    if len(valid)==1:
        side,row=next(iter(valid.items()))
        return {'status':'monocular','uv':list(row['uv']),'sides':[side],'disagreement':None}
    rows=list(valid.values());times=[r.get('captured_at') for r in rows]
    if all(t is not None for t in times) and max(times)-min(times)>.12:
        return {'status':'unsynchronized','uv':None,'sides':[],'disagreement':None}
    distance=float(np.linalg.norm((np.asarray(rows[0]['uv'])-rows[1]['uv'])*[1.,1./aspect]))
    # Eight percent of screen width. Apply before desktop fencing: two absurd
    # off-screen estimates must not become agreement just by hitting the same edge.
    if distance>.08:
        return {'status':'disagreement','uv':None,'sides':[],'disagreement':distance}
    # Pupil-detection confidence is not screen-mapping accuracy. Neither eye
    # earns more influence merely because its pupil outline is easier to detect.
    point=np.mean([r['uv'] for r in rows],axis=0)
    return {'status':'binocular','uv':point.tolist(),'sides':list(valid),'disagreement':distance}


def fuse_predictions(predictions,preferred=None,aspect=1.):
    # The legacy preferred argument no longer lets selection choose a winner
    # when the two calibrated maps contradict each other.
    value=shared_fixation(predictions,aspect)['uv']
    return np.asarray(value) if value is not None else None
