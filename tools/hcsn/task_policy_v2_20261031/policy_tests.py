"""Independent bounded-plan and residual-gradient contracts."""
from functools import lru_cache
import unittest

import numpy as np

from ..task_value_factorial_20261030.task import Bellman, feasible, likelihood, metadata, outcomes
from .planner import OneRead
from .training import loss_gradient


class PolicyTests(unittest.TestCase):
    def test_one_read_matches_independent_restricted_recursion(self):
        rng = np.random.default_rng(720310901)
        protocol = dict(deadlines=[6, 8, 10], read_budgets=[2, 3, 4],
                        packet_reliabilities=[.55, .7, .9], packet_prices=[.015, .06, .12],
                        step_durations=[.2, .8, 2.])
        confusion = np.array([[.96, .04], [.07, .93]])
        for env in range(20):
            meta = metadata(rng, str(env), protocol)
            planner = OneRead(meta, confusion, 1.5, .015)
            teacher = Bellman(meta, confusion, 1.5, .015)

            @lru_cache(None)
            def q(job, tick, budget, belief, reads_left):
                legal = feasible(meta, job, tick, budget)
                result = [0., -np.inf, -np.inf, -np.inf]
                if not legal[3]:
                    return tuple(result)
                dt = meta["duration"]
                if legal[1]:
                    result[1] = max(q(job, tick+1, budget, belief, reads_left))-.015*dt[tick]
                if legal[2] and reads_left:
                    prob, posterior = outcomes(belief, likelihood(confusion, meta["reliability"][job][tick]))
                    result[2] = sum(prob[o]*max(q(job, tick+1, budget-1, float(posterior[o]), 0)) for o in range(2))
                    result[2] -= 1.5*meta["price"][job][tick]+.015*dt[tick]
                result[3] = abs(2*belief-1)+max(q(job+1, tick+2, budget, .5, 1))-.015*sum(dt[tick:tick+2])
                return tuple(result)

            for _ in range(12):
                state = (int(rng.integers(2)), int(rng.integers(meta["deadline"])),
                         int(rng.integers(5)), float(rng.uniform(.05, .95)))
                actual = planner.q(*state)
                expected = np.array(q(*state, 1))
                np.testing.assert_allclose(actual, expected, atol=2e-12, rtol=0.)
                full = np.array(teacher.q(*state))
                valid = np.isfinite(actual)
                self.assertGreaterEqual(float(np.min(full[valid]-actual[valid])), -2e-12)

    def test_label_relabeling_preserves_plan_and_features(self):
        meta = dict(deadline=4, budget=2, reliability=[[.6,.9,.7,.8],[.9,.6,.8,.7]],
                    price=[[.02,.04,.08,.02],[.03,.08,.02,.04]], duration=[.2,.8,1.6,.4])
        confusion = np.array([[.96,.04],[.07,.93]])
        original = OneRead(meta, confusion, 1.5, .015)
        relabeled = OneRead(meta, confusion[::-1, ::-1], 1.5, .015)
        np.testing.assert_allclose(original.q(0,0,2,.3), relabeled.q(0,0,2,.7), atol=1e-14)
        np.testing.assert_allclose(original.features(0,0,2,.3), relabeled.features(0,0,2,.7), atol=1e-14)

    def test_both_residual_objective_gradients(self):
        rng = np.random.default_rng(720310902)
        weights = dict(w=rng.normal(0,.1,(7,5)), b=rng.normal(0,.1,5),
                       v=rng.normal(0,.1,(5,4)), c=rng.normal(0,.1,4))
        x, target = rng.normal(size=(11,7)), rng.normal(size=(11,4))
        mask = rng.random((11,4)) > .25
        mask[:,0] = True
        sample = rng.uniform(.2,3.,11)
        for mode in ("q_mse", "advantage"):
            for _ in range(2):
                direction = {k:rng.normal(size=v.shape) for k,v in weights.items()}
                loss, grad = loss_gradient(weights,x,target,mask,sample,mode,.0007)
                eps = 1e-6
                plus = {k:v+eps*direction[k] for k,v in weights.items()}
                minus = {k:v-eps*direction[k] for k,v in weights.items()}
                finite = (loss_gradient(plus,x,target,mask,sample,mode,.0007)[0]-
                          loss_gradient(minus,x,target,mask,sample,mode,.0007)[0])/(2*eps)
                analytic = sum(float(np.sum(grad[k]*direction[k])) for k in weights)
                self.assertAlmostEqual(finite, analytic, delta=2e-8)
                altered = target.copy()
                altered[~mask] = 1e6
                self.assertEqual(loss, loss_gradient(weights,x,altered,mask,sample,mode,.0007)[0])


if __name__ == "__main__":
    unittest.main()
