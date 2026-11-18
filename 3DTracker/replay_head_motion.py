"""Reproduce a saved steady-head session without touching the running application.

Output is numeric only. Retrospective replay is not a new real-world accuracy
measurement: code design may already have used this recording.
"""
import json
from pathlib import Path
from concurrent.futures import Future
import numpy as np
from quick_calibration import AnchorMap,TARGETS
from hybrid_onboarding import HeadCompensation
from continuous_calibration import ContinuousTargetCalibration


def replay_recorded(path,eye_side=None):
    """Reconstruct simultaneous five-dot + head-motion captures, offline only.

    Use the laptop's ORIGINAL feature packets, not secondary-view corrections.
    Legacy recordings did not store the instruction clock explicitly; report
    its inferred origin rather than presenting that estimate as exact.
    """
    from types import SimpleNamespace
    from binocular_calibration import BinocularCalibration,SteadyReference
    from continuous_calibration import check_recorded_head_movement
    from gaze_mapping import project_unbounded
    events=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if sum(r['event']=='webcam_alignment_started' for r in events)>1:
        raise ValueError('Replay one head capture at a time; this audit contains multiple attempts')
    captures=BinocularCalibration();motion={};seen={};viewport=None;clock=None
    single_captures=[r for r in events if r['event']=='single_pass_head_captured']
    if len(single_captures)>1:raise ValueError('Replay one head capture at a time')
    single=single_captures[0] if single_captures else None
    for row in events:
        if row['event']=='context' and row.get('displays'):viewport=row['displays'][0]['viewport']
        if row['event']=='head_capture_clock_started':clock=row['capture_started_at']
        if row['event']=='onboarding_eye_samples':
            matches=[i for i,t in enumerate(TARGETS) if np.allclose(t,row['target'])]
            if not matches:continue
            capture=captures.onboarding_captures.setdefault(matches[0],SimpleNamespace(completed={}))
            for side,obs in row['observations'].items():
                packet=obs.get('head_sample') or {}
                obs=dict(obs,head=packet.get('primary_features',obs['head']))
                captures.rows.setdefault(side,[])
                captures.identities[side]=obs['identity']
                block=capture.completed.setdefault(side,[])
                if not block or obs['time']>block[-1]['time']:block.append(obs)
        if row['event']=='paired_motion_sample':
            side=row['eye'];obs=row['observation'];packet=obs.get('head_sample')
            if not packet:raise ValueError('Motion sample has no saved webcam exposure')
            if obs['time'] in seen.setdefault(side,set()):continue
            seen[side].add(obs['time'])
            motion.setdefault(side,[]).append((obs['time'],np.array(obs['eye']),
                np.array(packet.get('primary_features',packet['features'])),np.array(row['target'])))
    if single:
        clock=single['capture_started_at']
        motion={side:[(r[0],np.asarray(r[1]),np.asarray(r[2]),np.asarray(r[3])) for r in rows]
                for side,rows in single['samples'].items()}
    captures.finish_onboarding([(0,1)]*5)
    if not viewport or not motion:raise ValueError('Need saved display geometry and paired motion samples')
    exact=clock is not None
    if clock is None:
        first=next(row['observation'] for row in events if row['event']=='paired_motion_sample')
        clock=(first['head_sample'].get('secondary_sample') or {}).get('time',first['time'])
    result={'session_id':events[0]['session_id'],'reference':'original laptop webcam features',
        'clock_seconds':clock,'clock_exact':exact,'viewport':viewport,'eyes':{},
        'note':'Retrospective replay of reconstructed anchors, not a fresh accuracy result. Only the first 32 seconds train; the next 32 check. Legacy clock inferred from the first paired exposure.'}
    if single:result['note']='Retrospective replay of a single 32-second pass. Later blocks of each motion are held out from fitting; no fresh accuracy claim.'
    for side,rows in motion.items():
        if eye_side and side!=eye_side:continue
        if side not in captures.maps:
            result['eyes'][side]={'error':captures.errors.get(side,'Missing five-dot samples')};continue
        rows.sort(key=lambda r:r[0]);seeds=captures.seeds[side];base=captures.maps[side]
        if single:seeds=[tuple(np.asarray(v) for v in r) for r in single['seeds'][side]]
        run=check_recorded_head_movement(base,SteadyReference(seeds[0][1]),seeds,rows,
            viewport[2]/viewport[3],16/9,side,clock,single_pass=single is not None)
        report=run.state(clock+(32 if single else 64));trace=[]
        for stamp,pupil,head,target in rows:
            if single:
                if not (0<=stamp-clock<32 and 4.25<=(stamp-clock)%8<7.75):continue
            elif not clock+32<=stamp<clock+64:continue
            before=project_unbounded(base,pupil)
            after=run.checked_candidate.evaluate_raw(pupil,head) if run.checked_candidate else None
            trace.append({'seconds':stamp-clock,'motion':run.motion_cue(stamp)['key'],
                'pupil_px':(pupil*[640,480]).tolist(),'head':head.tolist(),
                'target_uv':target.tolist(),'before_uv':before.tolist() if before is not None else None,
                'candidate_uv':after.tolist() if after is not None else None,
                'before_error_points':float(np.linalg.norm((before-target)*viewport[2:])) if before is not None else None,
                'candidate_error_points':float(np.linalg.norm((after-target)*viewport[2:])) if after is not None else None})
        result['eyes'][side]={'report':report,'checking_trace':trace,
            'anchors':[{'pupil':e.tolist(),'head':h.tolist(),'target':t.tolist()} for e,h,t in seeds]}
        run.close()
    return result

class ReplayExecutor:
    def submit(self,function,*args,**kwargs):
        future=Future()
        try:future.set_result(function(*args,**kwargs))
        except Exception as error:future.set_exception(error)
        return future
    def shutdown(self,**kwargs):pass

def replay(path,eye_side):
    rows=[json.loads(line) for line in Path(path).read_text().splitlines()]
    start=next(row for row in rows if row['event']=='head_motion_started')
    context=next(row for row in rows if row['event']=='context' and row['context_id']==start['context_id'])
    seeds=[tuple(np.asarray(v) for v in row) for row in start['seeds']]
    head=context['head_model']
    if head['mode']!='steady' or len(seeds)!=5 or not np.allclose([s[2] for s in seeds],TARGETS):
        raise ValueError('This replay supports the five-anchor steady-head session format only')
    fit=HeadCompensation();fit.fit_steady([seeds[0][0]]*10,[np.asarray(head['reference'])]*10)
    base=AnchorMap([s[0] for s in seeds])
    samples=[r['measurement'] for r in rows if r['event']=='measurement'
             and r['measurement']['source'] in ('geometry-training','geometry-check')
             and r['measurement']['captured_at']>=start['monotonic_seconds']]
    if not samples:raise ValueError('No head movement measurements in this session')
    viewport=context['displays'][0]['viewport'];aspect=viewport[2]/viewport[3]
    run=ContinuousTargetCalibration(base,fit,seeds,aspect,16/9,samples[0]['captured_at']-.1,
        eye_side=eye_side,executor=ReplayExecutor())
    transitions=[];previous=None
    for row in samples:
        stamp=row['captured_at'];run.observe((np.array(row['raw_eye']),np.array(row['head'])),stamp,stamp)
        signature=(run.phase,run.revision,run.check_failures,run.fit_failures)
        if signature!=previous:
            transitions.append({'seconds':stamp-samples[0]['captured_at'],'phase':run.phase,
                'updates':run.revision,'candidate_p80_uv':run.validation_error,
                'previous_p80_uv':run.baseline_error,'fit':run.fit_metrics})
        previous=signature
    result={'measurement_count':len(samples),'applied_updates':run.revision,
        'side_assumption':run.eye_side,'transitions':transitions,
        'note':'Retrospective replay; no images, live state changes, or automatic restoration.'}
    run.close();return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('events_log')
    parser.add_argument('--eye-side',choices=('left','right'))
    parser.add_argument('--recorded',action='store_true',help='Replay both eyes from the guided paired-motion audit format')
    args=parser.parse_args()
    if not args.recorded and args.eye_side is None:parser.error('--eye-side is required for the legacy single-eye format')
    print(json.dumps(replay_recorded(args.events_log,args.eye_side) if args.recorded else replay(args.events_log,args.eye_side),indent=2,allow_nan=False))
