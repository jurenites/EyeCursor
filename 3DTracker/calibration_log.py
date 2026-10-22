"""Local numeric calibration audit. No images; no automatic replay into a live fit."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np

# Explicit model parameters only. Never serialize an object's camera or UI handles.
MODEL_FIELDS=('reference','coefficients','bounds','error','mode','eyes','offset','shift',
              'anchors','eye_scale','residuals','pose_scale','rank','support','status',
              'pair_count','fit_error','depth','reference_width','aspect','camera_aspect',
              'head_coefficients','eye_center','validation_error','degree','ridge','fit_metrics')


def numeric(value):
    if isinstance(value,np.ndarray):return numeric(value.tolist())
    if isinstance(value,np.generic):return numeric(value.item())
    if isinstance(value,float) and not np.isfinite(value):return None
    if isinstance(value,dict):return {str(k):numeric(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [numeric(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise TypeError(f'Unsupported log value: {type(value).__name__}')


def model_snapshot(model):
    if model is None:return None
    result={'type':type(model).__name__}
    if callable(getattr(model,'geometry',None)):result['optics']=numeric(model.geometry())
    for key in MODEL_FIELDS:
        if hasattr(model,key):result[key]=numeric(getattr(model,key))
    for key in ('base','head_model'):
        if getattr(model,key,None) is not None:result[key]=model_snapshot(getattr(model,key))
    return result


class CalibrationLog:
    def __init__(self,path,session_id):
        self.path=Path(path) if path else None
        self.session_id=session_id
        self.contexts=set();self.sequence=0;self.last_observation=None;self.error=None

    def append(self,event,now,**payload):
        if self.path is None:return
        self.sequence+=1
        row=numeric(dict(schema_version=1,sequence=self.sequence,event=event,
                         session_id=self.session_id,monotonic_seconds=now,
                         utc=datetime.now(timezone.utc).isoformat(),**payload))
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a') as out:out.write(json.dumps(row,allow_nan=False)+'\n')
            self.error=None
            return True
        except OSError as error:
            self.error=str(error)
            return False

    def context(self,now,**payload):
        encoded=json.dumps(numeric(payload),sort_keys=True,allow_nan=False)
        key=hashlib.sha256(encoded.encode()).hexdigest()[:20]
        if key not in self.contexts:
            if self.append('context',now,context_id=key,**payload):self.contexts.add(key)
        return key

    def observation(self,now,**payload):
        # Sample decision diagnostics at 10 Hz. Successful measurements remain
        # uncapped and are linked to their original full-rate measurement IDs.
        if self.last_observation is not None and now-self.last_observation<.1:return
        self.last_observation=now
        self.append('observation',now,**payload)


def summarize(path):
    from collections import Counter
    rows=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    events=Counter(row['event'] for row in rows)
    decisions=Counter(row.get('decision','unknown') for row in rows if row['event']=='observation')
    outcomes=[{k:r.get(k) for k in ('event','utc','message','applied','ready','saved','phase')}
              for r in rows if r['event'] in ('cursor_finished','cursor_fixation_result','screen_fit_result')]
    return {'session_id':rows[0]['session_id'] if rows else None,'events':dict(events),
            'sampled_observation_decisions':dict(decisions),'recent_outcomes':outcomes[-12:],
            'note':'Counts describe logged evidence; they are not a physical accuracy score.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Summarize a local EyeCursor calibration audit; no live state is modified.')
    parser.add_argument('path')
    print(json.dumps(summarize(parser.parse_args().path),indent=2))
