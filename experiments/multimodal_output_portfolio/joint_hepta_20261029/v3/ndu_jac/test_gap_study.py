"""Behavioral checks for empirical optimization and its transfer boundary."""

import random
import unittest

from .core import Outcome, evaluate, optimal_policy, policy_gradient, softmax_policy
from .finite_study import build_problem, sample_model
from .gap_study import (empirical_policy_iteration, greedy_policy, initialize,
                        mirror_actor, residual_bound)


class GapStudyTests(unittest.TestCase):
    def test_residual_bounds_actual_gap_and_iteration_closes_it(self):
        truth, root, _ = build_problem()
        for seed in (803, 804, 805, 806, 807):
            model, _ = sample_model(truth, 13, random.Random(seed))
            initial = softmax_policy(model, initialize(model, seed + 200))
            result = evaluate(model, root, initial, 2.0, 0.17)
            _, bounds = residual_bound(model, result, 0.17)
            optimum = optimal_policy(model, root, 2.0, 0.17)
            for state in model:
                gap = optimum["values"][state] - result["values"][state]
                self.assertGreaterEqual(gap, -1e-12)
                self.assertLessEqual(gap, bounds[state] + 1e-12)
            policy, report = empirical_policy_iteration(model, root, initial, 2.0, 0.17)
            self.assertTrue(report["converged"])
            self.assertLessEqual(report["updates"], 4)
            self.assertAlmostEqual(evaluate(model, root, policy, 2.0, 0.17)["value"],
                                   optimum["value"], places=12)
            trace = [r["value"] for r in report["empirical_trace"]]
            self.assertTrue(all(b >= a - 1e-12 for a, b in zip(trace, trace[1:])))

    def test_mirror_improvement_is_monotone_on_fixed_empirical_law(self):
        truth, root, _ = build_problem()
        for seed in (810, 811, 812):
            model, _ = sample_model(truth, 11, random.Random(seed))
            policy, report = mirror_actor(model, root, seed, 2.0, 0.17, steps=40)
            trace = report["empirical_trace"] + [evaluate(model, root, policy, 2.0, 0.17)["value"]]
            self.assertTrue(all(b >= a - 1e-12 for a, b in zip(trace, trace[1:])))
            self.assertLessEqual(trace[-1], optimal_policy(model, root, 2.0, 0.17)["value"] + 1e-12)

    def test_planning_updates_root_unreachable_states(self):
        model = {"root": {"STOP": (Outcome(1.0, reward=2.0),)},
                 "unreachable": {"bad": (Outcome(1.0, reward=-1.0),),
                                 "good": (Outcome(1.0, reward=1.0),)}}
        logits = {"root": {"STOP": 0.0}, "unreachable": {"bad": 0.0, "good": 0.0}}
        gradient = policy_gradient(model, "root", logits, 2.0, 0.17)
        self.assertEqual(gradient["gradient"]["unreachable"], {"bad": 0.0, "good": 0.0})
        policy, _ = mirror_actor(model, "root", 10, 2.0, 0.17, steps=5)
        self.assertGreater(policy["unreachable"]["good"], 0.99)

    def test_empirical_improvement_can_harm_true_utility(self):
        true_model = {"root": {"safe": (Outcome(1.0, reward=0.1),),
            "risky": (Outcome(0.45, reward=1.0), Outcome(0.55, reward=-1.0))}}
        fitted = {"root": {"safe": true_model["root"]["safe"],
                            "risky": (Outcome(1.0, reward=1.0),)}}
        baseline = {"root": {"safe": 1.0, "risky": 0.0}}
        proposed, report = empirical_policy_iteration(fitted, "root", baseline, 2.0, 0.17)
        self.assertTrue(report["converged"])
        self.assertGreater(evaluate(fitted, "root", proposed, 2.0, 0.17)["value"],
                           evaluate(fitted, "root", baseline, 2.0, 0.17)["value"])
        self.assertLess(evaluate(true_model, "root", proposed, 2.0, 0.17)["value"],
                        evaluate(true_model, "root", baseline, 2.0, 0.17)["value"])

    def test_rounding_a_policy_is_not_guaranteed_to_improve(self):
        model = {"root": {"bad": (Outcome(1.0, reward=-1.0),),
                          "good": (Outcome(1.0, reward=1.0),)}}
        policy = {"root": {"bad": 0.51, "good": 0.49}}
        rounded = greedy_policy(policy)
        self.assertLess(evaluate(model, "root", rounded)["value"],
                        evaluate(model, "root", policy)["value"])


if __name__ == "__main__":
    unittest.main()
