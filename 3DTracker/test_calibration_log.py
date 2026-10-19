import json
import tempfile
from pathlib import Path
import unittest
import numpy as np
from calibration_log import CalibrationLog, model_snapshot, summarize
from cursor_calibration import CursorMap


class CalibrationLogTests(unittest.TestCase):
    def test_contexts_are_immutable_replayable_and_rejections_are_summarized(self):
        targets=np.array([[.1,.1],[.9,.1],[.9,.9],[.1,.9],[.5,.5],[.5,.15]])
        model=CursorMap(targets*[.18,.14]+[.38,.35],targets)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.jsonl';log=CalibrationLog(path,'session')
            context=log.context(1.,model=model_snapshot(model))
            self.assertEqual(log.context(2.,model=model_snapshot(model)),context)
            log.observation(2.,context_id=context,decision='below_confidence_threshold',confidence=float('nan'))
            log.observation(2.01,context_id=context,decision='paired')
            model.coefficients=model.coefficients+0.01
            self.assertNotEqual(log.context(3.,model=model_snapshot(model)),context)
            rows=[json.loads(l) for l in path.read_text().splitlines()]
            self.assertEqual(len(rows),3)
            self.assertIsNone(rows[1]['confidence'])
            old=np.array(rows[0]['model']['coefficients'])
            point=np.array([.73,.28])
            self.assertTrue(np.allclose(np.r_[point*[.18,.14]+[.38,.35],1]@old,point))
            summary=summarize(path)
            self.assertEqual(summary['sampled_observation_decisions'],{'below_confidence_threshold':1})

    def test_write_failure_does_not_disrupt_tracking_or_claim_saved_context(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'file';path.write_text('not a directory')
            log=CalibrationLog(path/'events.jsonl','session')
            log.context(1.,model=None)
            self.assertIsNotNone(log.error)
            self.assertEqual(log.contexts,set())
