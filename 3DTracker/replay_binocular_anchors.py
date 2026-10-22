"""Read-only replay of paired anchors in a saved five-point session.

Reports calibration-window contamination and later explicit cursor labels.
Retrospective errors are diagnostics, not a new live accuracy measurement.
"""
import json
from pathlib import Path
import numpy as np
from binocular_calibration import BinocularCalibration
from quick_calibration import AnchorMap, TARGETS, append_fixation


def replay(path):
    events=[json.loads(line) for line in Path(path).read_text().splitlines()]
    measurements=[r['measurement'] for r in events if r['event']=='measurement']
    windows=[]
    for target in TARGETS:
        block=[]
        for row in measurements:
            if row['source']=='onboarding' and np.allclose(row['target'],target):
                if np.allclose(target,TARGETS[0]):block.append((row['captured_at'],np.asarray(row['eye'])))
                else:append_fixation(block,np.asarray(row['eye']),row['captured_at'])
        if not block:raise ValueError('This recording has no complete five-point pass')
        windows.append((block[0][0],block[-1][0]))
    pair=BinocularCalibration()
    for row in measurements:
        if row['source']=='onboarding':
            pair.record(row.get('paired_eyes',{}),row['target'],'onboarding',row['captured_at'],1.,'left')
    old={};shifts={}
    for side,rows in pair.rows.items():
        seeds=[np.median([r[1] for r in rows if np.allclose(r[3],target)],axis=0) for target in TARGETS]
        try:old[side]=AnchorMap(seeds)
        except ValueError:pass
    pair.finish_onboarding(windows)
    for side,model in pair.maps.items():
        if side in old:
            shifts[side]=(np.linalg.norm((model.eyes-old[side].eyes)*[640,480],axis=1)).tolist()
    # One vote per subsequent known-target fixation, without applying those
    # fixations as corrections to either model being compared.
    groups={}
    for row in measurements:
        if row['source']=='cursor' and row.get('fixation_id'):
            groups.setdefault(row['fixation_id'],[]).append(row)
    errors={}
    for side in pair.maps:
        before=[];after=[]
        for rows in groups.values():
            samples=[r['paired_eyes'][side]['eye'] for r in rows if side in r.get('paired_eyes',{})]
            if not samples:continue
            eye=np.median(samples,axis=0);target=np.median([r['target'] for r in rows],axis=0)
            size=np.asarray(rows[0]['viewport'][2:])
            after.append(float(np.linalg.norm((pair.maps[side].project_unbounded(eye)-target)*size)))
            if side in old:before.append(float(np.linalg.norm((old[side].project_unbounded(eye)-target)*size)))
        errors[side]={'later_fixations':len(after),
                      'old_mean_points':float(np.mean(before)) if before else None,
                      'settled_mean_points':float(np.mean(after)) if after else None}
    result={'session':events[0]['session_id'],'stable_windows':windows,
            'corner_shift_ir_pixels':shifts,'later_cursor_labels':errors,
            'companion_errors':pair.errors,
            'recorded_accuracy_checks':[r['report'] for r in events if r['event']=='accuracy_check_result'],
            'note':'Retrospective, uncorrected baseline comparison; not a live accuracy guarantee. No app state modified.'}
    pair.close()
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events_log')
    print(json.dumps(replay(parser.parse_args().events_log),indent=2,allow_nan=False))
