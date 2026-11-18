"""Numeric audits reproduce independent eyes without opening a camera."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from quick_calibration import TARGETS
from replay_head_motion import replay_recorded
from test_geometric_gaze import BASE,ASPECT,physical_eye,moving_head


class RecordedReplayTests(unittest.TestCase):
    def test_both_eyes_use_original_primary_pose_and_a_disjoint_later_check(self):
        rows=[dict(event='session_started',session_id='fixture'),
              dict(event='context',displays=[dict(viewport=[0,0,1600,1000])]),
              dict(event='webcam_alignment_started'),
              dict(event='head_capture_clock_started',capture_started_at=100.)]
        for index,target in enumerate(TARGETS):
            for i in range(10):
                observations={}
                for side in ('left','right'):
                    observations[side]=dict(identity=[side,0,1,1,1],time=index+i*.05,
                        eye=physical_eye(target,BASE,side).tolist(),head=(BASE+10).tolist(),
                        head_sample={'primary_features':BASE.tolist()})
                rows.append(dict(event='onboarding_eye_samples',target=target.tolist(),observations=observations))
        for t in np.arange(.1,64,.2):
            h=moving_head(t)
            for side in ('left','right'):
                rows.append(dict(event='paired_motion_sample',eye=side,target=[.5,.5],
                    observation=dict(time=100+t,eye=physical_eye([.5,.5],h,side).tolist(),
                        head_sample={'time':100+t,'features':(h+10).tolist(),'primary_features':h.tolist()})))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.jsonl';path.write_text('\n'.join(json.dumps(r) for r in rows))
            result=replay_recorded(path)
        self.assertTrue(result['clock_exact'])
        self.assertEqual(set(result['eyes']),{'left','right'})
        for eye in result['eyes'].values():
            self.assertGreater(eye['report']['fitted_training_samples'],100)
            self.assertGreater(eye['report']['evaluated_checking_samples'],100)
            self.assertTrue(all(32<=row['seconds']<64 for row in eye['checking_trace']))
            self.assertLess(eye['report']['validation_error_uv'],.06)
            np.testing.assert_allclose(eye['anchors'][0]['head'],BASE)
        samples={side:[] for side in ('left','right')}
        seeds={side:[[physical_eye(target,BASE,side).tolist(),BASE.tolist(),target.tolist()]
                     for target in TARGETS] for side in samples}
        for row in rows:
            if row['event']=='paired_motion_sample' and row['observation']['time']<132:
                obs=row['observation']
                samples[row['eye']].append([obs['time'],obs['eye'],obs['head_sample']['primary_features'],row['target']])
        rows.append(dict(event='single_pass_head_captured',capture_started_at=100,samples=samples,seeds=seeds))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.jsonl';path.write_text('\n'.join(json.dumps(r) for r in rows))
            shortened=replay_recorded(path)
        for eye in shortened['eyes'].values():
            self.assertEqual(eye['report']['fit_metrics']['validation_protocol'],'within_motion_held_out_blocks')
            self.assertTrue(eye['checking_trace'])
            self.assertTrue(all(4.25<=r['seconds']%8<7.75 for r in eye['checking_trace']))
