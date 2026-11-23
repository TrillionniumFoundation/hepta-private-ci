import unittest

import numpy as np

from .ndu import FiniteBellman, actions_and_targets, controls, policy_result


class TaskTest(unittest.TestCase):
    def test_expensive_second_observation_and_future_oracle(self):
        free=np.array([[[0,1],[0,1]],[[0,1],[1,0]]])
        paid=np.array([[[1,0],[0,1]],[[0,1],[1,0]]])
        dt=np.ones((2,2))*0.48
        target=np.zeros(2,dtype=int)
        teacher,correct=actions_and_targets(free,paid,target,dt)
        s=dict(scores=free,correct=correct,teacher=teacher,dt=dt,group=['a','b'])
        base=controls(s)
        self.assertEqual(base['immediate_stop']['r1'],0)
        self.assertEqual(base['immediate_read']['r1'],0.5)
        self.assertEqual(base['hindsight_upper']['r1'],1.)
        self.assertEqual(base['hindsight_upper']['terminal_action'],[1,0])
        self.assertEqual(base['hindsight_upper']['exit_prefix'],[0,1])
        self.assertTrue(np.allclose(base['hindsight_upper']['episode_utility'],teacher[:,0].max(-1)))
        # Same free evidence implies same fitted decision despite different paid outcomes.
        p=FiniteBellman(s).predict(s)
        np.testing.assert_array_equal(p[0],p[1])
        result=policy_result(p,s)
        self.assertLessEqual(result['utility'],base['hindsight_upper']['utility'])
