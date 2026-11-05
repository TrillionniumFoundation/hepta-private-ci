"""Public-state, hard resource, empirical critic and strong-reference checks."""

import math
import random
import unittest

from .core import evaluate, optimal_policy
from .finite_study import State, build_problem, fit_actor, fixed_reference, sample_model


class FiniteStudyTests(unittest.TestCase):
    def test_joint_state_and_failed_attempt_resource_accounting(self):
        nodes, root, states = build_problem()
        self.assertLessEqual(len(nodes), 512)
        self.assertEqual(states[root], State())
        for s, row in nodes.items():
            for a, law in row.items():
                for o in law:
                    if o.next_state is not None:
                        after, before = states[o.next_state], states[s]
                        self.assertLess(after.budget, before.budget)
                        self.assertGreater(after.clock, before.clock)
                        self.assertLessEqual(after.clock, 4)
                        self.assertEqual(after.version, before.version)
                        self.assertEqual(after.remaining, before.remaining-1)
                        self.assertGreater(o.cost, 0)
        heavy = nodes[root]["inspect_precise"]
        self.assertTrue(all(states[o.next_state].p == 1 for o in heavy))
        self.assertTrue(all(o.adjustment_cost > 0 for o in heavy))
        self.assertEqual(states[heavy[0].next_state].belief, states[root].belief)

    def test_actor_and_critic_use_the_same_bank_with_strong_dp(self):
        nodes, root, states = build_problem()
        fitted, receipt = sample_model(nodes, 16, random.Random(212))
        pi, report = fit_actor(fitted, root, 213, 2.0, 0.17, steps=30)
        actor = evaluate(fitted, root, pi, 2.0, 0.17)["value"]
        optimum = optimal_policy(fitted, root, 2.0, 0.17)["value"]
        self.assertLessEqual(actor, optimum+1e-12)
        self.assertGreaterEqual(actor, report["history"][0]["empirical_value_before_update"]-1e-12)
        self.assertEqual(receipt["transition_calls"], 16*sum(map(len, nodes.values())))
        self.assertLessEqual(fixed_reference(nodes, root, states, 2.0, 0.17)["value"],
                             optimal_policy(nodes, root, 2.0, 0.17)["value"]+1e-12)

    def test_proper_tabular_moment_stationarity(self):
        nodes, root, _ = build_problem()
        result = optimal_policy(nodes, root, 2.0, 0.17)
        for s, row in nodes.items():
            for a, law in row.items():
                moment = sum(o.probability*math.exp(-2*(o.reward-o.cost-o.adjustment_cost
                    + (math.exp(-0.17*o.duration)*result["values"][o.next_state]
                       if o.next_state is not None else 0))) for o in law)
                v = -2*result["action_values"][s][a]
                self.assertAlmostEqual(math.exp(v)-moment, 0, places=12)


if __name__ == "__main__":
    unittest.main()
