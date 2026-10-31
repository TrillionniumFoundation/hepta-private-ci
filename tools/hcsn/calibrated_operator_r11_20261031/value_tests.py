"""Behavioral contract checks independent of neural training."""
import unittest

import numpy as np

from ..task_value_factorial_20261030.task import Bellman, feasible, metadata
from .value import GridValue, select_action


class ValueTests(unittest.TestCase):
    def test_cross_language_numerical_ties_keep_declared_priority(self):
        a = [0., .7431969696969697, .7431969696969696, .6587575757575758]
        b = [0., .7431969696969696, .7431969696969697, .6587575757575757]
        self.assertEqual(select_action(a, [True]*4), 1)
        self.assertEqual(select_action(b, [True]*4), 1)
        b[2] += 1e-10
        self.assertEqual(select_action(b, [True]*4), 2)

    def setUp(self):
        self.meta = dict(deadline=6, budget=3, reliability=[[.9]*6]*2,
                         price=[[.01]*6]*2, duration=[.2,.4,.8,1.,1.6,2.])
        self.confusion = np.array([[.99,.01],[.01,.99]])

    def test_stop_last_slot_skip_and_second_job(self):
        grid = GridValue(self.meta, self.confusion, 1.5, .015, 129)
        q = grid.q(1,5,2,.8)
        self.assertEqual(q[0], 0.)
        self.assertTrue(np.all(np.isneginf(q[1:3])))
        self.assertAlmostEqual(q[3], .6-.015*2)
        self.assertGreater(grid.q(0,0,3,.5)[3], .4)
        grid = GridValue(self.meta, self.confusion, 1.5, 10., 129)
        self.assertEqual(np.argmax(grid.q(0,0,3,.5)), 0)
        self.meta["reliability"] = [[.5]+[.99]*5, [.99]*6]
        grid = GridValue(self.meta, self.confusion, 1.5, .015, 129)
        q = grid.q(0,0,3,.5)
        self.assertGreater(q[1],q[2])

    def test_dense_public_states_against_independent_tree_dp(self):
        rng = np.random.default_rng(1400981)
        protocol = dict(deadlines=[4,6,8],read_budgets=[0,1,3],packet_reliabilities=[.55,.7,.95],
                        packet_prices=[.01,.1,.3],step_durations=[.2,1.,2.])
        errors = []
        for case in range(8):
            meta = metadata(rng, str(case), protocol)
            grid = GridValue(meta,self.confusion,1.5,.015,513)
            exact = Bellman(meta,self.confusion,1.5,.015)
            for job in (0,1):
                for tick in range(meta["deadline"]):
                    for budget in range(meta["budget"]+1):
                        for p in (0.,.001,.13,.5,.77,.999,1.):
                            legal = feasible(meta,job,tick,budget)
                            a, b = grid.q(job,tick,budget,p), np.array(exact.q(job,tick,budget,p))
                            errors.extend(abs(a[legal]-b[legal]))
        self.assertLess(max(errors),.002)


if __name__ == "__main__":
    unittest.main()
