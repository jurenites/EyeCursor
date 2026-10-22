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
    parser.add_argument('--eye-side',choices=('left','right'),required=True)
    args=parser.parse_args()
    print(json.dumps(replay(args.events_log,args.eye_side),indent=2,allow_nan=False))
