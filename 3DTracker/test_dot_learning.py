import unittest
import numpy as np
from dot_learning import DotLearning

class DotLearningTests(unittest.TestCase):
    def test_each_eye_gets_independent_samples_and_no_predictions_are_required(self):
        run=DotLearning(10,{'left','right'});now=10
        while not run.done and now<60:
            now+=1/30;target=np.asarray(run.target)
            run.observe({side:{'eye':(.4+target*scale).tolist(),'head':[0,0,0,.5,.4,-1.2],
                               'time':now} for side,scale in [('left',.1),('right',-.2)]},now)
            run.tick(now)
        self.assertTrue(run.done)
        self.assertTrue(all(set(row['eyes'])=={'left','right'} for row in run.rows))
        self.assertNotEqual(run.rows[0]['eyes']['left'][0]['eye'],run.rows[0]['eyes']['right'][0]['eye'])

    def test_missing_eye_does_not_fabricate_samples_or_block_the_other(self):
        run=DotLearning(10,{'left','right'});now=10
        while not run.done and now<60:
            now+=1/30
            run.observe({'left':{'eye':np.asarray(run.target)*.1,'head':[0,0,0,.5,.4,-1.2],'time':now}},now)
            run.tick(now)
        self.assertTrue(run.done)
        self.assertTrue(all(set(row['eyes'])=={'left'} for row in run.rows))

    def test_staggered_eye_fixations_finish_five_shared_targets_without_overwriting(self):
        run=DotLearning(10,{'left','right'});now=10
        while not run.done and now<40:
            now+=1/30;elapsed=now-run.started;target=np.asarray(run.target)
            # Left completes first. Right settles later; their stable blocks
            # never overlap. A blink afterwards must not erase the left block.
            side='left' if elapsed<1.5 else 'right'
            observations={side:{'eye':(.4+target*(.1 if side=='left' else -.2)).tolist(),
                                'head':[0,0,0,.5,.4,-1.2],'time':now}}
            if elapsed<2.5 and side=='right':observations={}
            run.observe(observations,now);run.tick(now)
        self.assertTrue(run.done)
        self.assertEqual(len(run.rows),5)
        for row in run.rows:
            self.assertEqual(set(row['eyes']),{'left','right'})
            self.assertLess(row['eyes']['left'][-1]['time'],row['eyes']['right'][0]['time'])

    def test_duplicate_and_stale_frames_cannot_fill_a_target(self):
        run=DotLearning(10,{'left'})
        obs={'left':{'eye':[.4,.4],'head':[0,0,0,.5,.4,-1.2],'time':11}}
        for _ in range(30):run.observe(obs,11);run.tick(11)
        self.assertEqual(run.index,0)
        self.assertEqual(len(run.blocks['left']),1)
        run.observe(obs,12);run.tick(12)
        self.assertEqual(run.index,0)
