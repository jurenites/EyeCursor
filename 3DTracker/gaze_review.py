"""Offline gaze review. Never changes capture data, calibration, or the live cursor.

Fixations are screen-space dispersion/duration estimates, not proof of reading.
No interpolation through rejected observations, blinks or missing camera frames.
"""
import math


def analyze(samples, width, height, start_ms=0., end_ms=None,
            dispersion_px=45., min_fixation_ms=120., max_gap_ms=100.):
    width, height = float(width), float(height)
    if not all(math.isfinite(v) and v > 0 for v in (width, height, dispersion_px, min_fixation_ms, max_gap_ms)):
        raise ValueError('Review dimensions and thresholds must be positive')
    end_ms = float('inf') if end_ms is None else float(end_ms)
    points = []
    seen = set()
    for index, row in enumerate(samples):
        t = row.get('t_ms')
        if not isinstance(t, (int, float)) or not math.isfinite(t) or not start_ms <= t <= end_ms:
            continue
        x, y = row.get('x'), row.get('y')
        finite = all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y))
        status = 'measured' if row.get('valid') and finite else 'missing'
        if finite and not (0 <= x <= 1 and 0 <= y <= 1): status = 'off_screen'
        if row.get('held'): status = 'held'
        if row.get('learning'): status = 'calibration'
        capture = row.get('capture_id')
        if capture is not None:
            if capture in seen: continue  # Polling is not a new eye measurement.
            seen.add(capture)
        points.append(dict(index=index, t_ms=t, x=x if finite else None, y=y if finite else None,
                           confidence=row.get('confidence'), status=status))
    points.sort(key=lambda p:p['t_ms'])

    def distance(a,b):
        return math.hypot((a['x']-b['x'])*width, (a['y']-b['y'])*height)

    # Conservative, explicitly labelled hypothesis: low-score A->B->A spike.
    # A sustained new location (A->B->B) is preserved from its FIRST sample.
    statuses = [p['status'] for p in points]
    for i in range(1,len(points)-1):
        a,b,c = points[i-1:i+2]
        scores = [p['confidence'] for p in (a,b,c)]
        if not all(s == 'measured' for s in statuses[i-1:i+2]): continue
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in scores): continue
        if not (0 < b['t_ms']-a['t_ms'] <= max_gap_ms and 0 < c['t_ms']-b['t_ms'] <= max_gap_ms): continue
        if (distance(a,c) <= dispersion_px and distance(a,b) > max(60.,3*dispersion_px)
                and scores[1]+.15 < min(scores[0],scores[2])):
            b['status'] = 'possible_glitch'

    # I-DT-style bounding-box dispersion, expressed in screen pixels because
    # the current hardware does not establish trustworthy visual-angle units.
    fixations = []
    def extract(run):
        i = 0
        while i < len(run):
            j = i
            while j < len(run) and run[j]['t_ms']-run[i]['t_ms'] < min_fixation_ms: j += 1
            if j == len(run): break
            block = run[i:j+1]
            xs = [p['x']*width for p in block]; ys = [p['y']*height for p in block]
            bounds = [min(xs),max(xs),min(ys),max(ys)]
            def spread(b): return math.hypot(b[1]-b[0], b[3]-b[2])
            if spread(bounds) > dispersion_px: i += 1; continue
            while j+1 < len(run):
                p = run[j+1]; x,y = p['x']*width,p['y']*height
                updated = [min(bounds[0],x),max(bounds[1],x),min(bounds[2],y),max(bounds[3],y)]
                if spread(updated) > dispersion_px: break
                j += 1; bounds = updated
            block = run[i:j+1]
            durations = [b['t_ms']-a['t_ms'] for a,b in zip(block,block[1:])]
            duration = sum(durations)
            # Time-weighted midpoint of measured adjacent samples, no terminal hold.
            center = [sum((a[key]+b[key])*.5*dt for a,b,dt in zip(block,block[1:],durations))/duration
                      for key in ('x','y')]
            fixations.append(dict(start_ms=block[0]['t_ms'],end_ms=block[-1]['t_ms'],duration_ms=duration,
                                  x=center[0],y=center[1],dispersion_px=spread(bounds),samples=len(block)))
            i = j+1
    run = []
    for p in points:
        if p['status'] != 'measured' or (run and not 0 < p['t_ms']-run[-1]['t_ms'] <= max_gap_ms):
            extract(run); run=[]
        if p['status'] == 'measured': run.append(p)
    extract(run)
    return dict(schema='eyecursor.review.v1', points=points, fixations=fixations,
                parameters=dict(start_ms=start_ms,end_ms=None if math.isinf(end_ms) else end_ms,
                                width=width,height=height,dispersion_px=dispersion_px,
                                min_fixation_ms=min_fixation_ms,max_gap_ms=max_gap_ms),
                summary=dict(fixation_ms=sum(f['duration_ms'] for f in fixations),
                             measured_samples=sum(p['status']=='measured' for p in points),
                             possible_glitches=sum(p['status']=='possible_glitch' for p in points),
                             excluded_samples=sum(p['status'] not in ('measured','possible_glitch') for p in points)),
                interpretation='Estimated screen-space fixations. Connections join sampled positions; unobserved trajectories are unknown. Dwell does not establish reading or comprehension.')
