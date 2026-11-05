"""Behavioral independent references and objective-confusion regressions."""

import math
import unittest

from .semantics import (
    Action,
    Model,
    Outcome,
    counterexamples,
    decimal_policy_value,
    difference_gradient,
    enumerate_trees,
    evaluate,
    example_model,
    inherited_crosscheck,
    optimal,
    path_value_gradient,
    risk_scaled_value,
)


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.model = example_model()
        self.theta = (0.3, -0.2, 0.5, -0.4, -0.1, 0.2)

    def test_bellman_equals_independent_all_trees(self):
        for eta in (0, 0.2, 2):
            for rate in (0, 0.13):
                with self.subTest(eta=eta, rate=rate):
                    dp, trees = optimal(self.model, eta, rate), enumerate_trees(self.model, eta, rate)
                    self.assertAlmostEqual(dp["value"], trees["value"], places=13)
                    self.assertGreater(trees["root_trees"], 1)

    def test_actor_derivative_independent_decimal(self):
        for theta in (self.theta, tuple(-x for x in self.theta), (0,) * 6):
            for eta, rate in ((0, 0.13), (0.2, 0), (2, 0.13)):
                with self.subTest(theta=theta, eta=eta, rate=rate):
                    actor = evaluate(self.model, theta, eta, rate)
                    independent = difference_gradient(self.model, theta, eta, rate)
                    self.assertLess(max(abs(x - y) for x, y in zip(actor["gradient"], independent)), 1e-12)
                    self.assertAlmostEqual(
                        actor["value"], float(decimal_policy_value(self.model, theta, eta, rate)), places=13
                    )

    def test_complete_path_score_when_objectives_coincide(self):
        for eta, rate in ((0, 0), (0, 0.13), (0.2, 0), (2, 0)):
            with self.subTest(eta=eta, rate=rate):
                recursive = evaluate(self.model, self.theta, eta, rate)
                paths = path_value_gradient(self.model, self.theta, eta, rate)
                self.assertAlmostEqual(recursive["value"], paths["value"], places=13)
                self.assertLess(max(abs(x - y) for x, y in zip(recursive["gradient"], paths["gradient"])), 1e-12)

    def test_discounted_static_ce_is_not_fixed_eta_nested_ce(self):
        recursive = evaluate(self.model, self.theta, 2, 0.13)
        static = path_value_gradient(self.model, self.theta, 2, 0.13)
        self.assertGreater(abs(recursive["value"] - static["value"]), 0.008)
        self.assertAlmostEqual(risk_scaled_value(self.model, self.theta, 2, 0.13), static["value"], places=13)
        self.assertGreater(max(abs(x - y) for x, y in zip(recursive["gradient"], static["gradient"])), 0.001)

    def test_risk_neutral_limit_value_and_gradient(self):
        neutral = evaluate(self.model, self.theta, rate=0.13)
        errors = []
        for eta in (0.1, 0.001, 1e-6, 1e-9):
            result = evaluate(self.model, self.theta, eta, 0.13)
            errors.append(abs(result["value"] - neutral["value"]))
            if eta == 1e-9:
                self.assertLess(errors[-1], 1e-9)
                self.assertLess(max(abs(x - y) for x, y in zip(result["gradient"], neutral["gradient"])), 1e-9)
        self.assertEqual(errors, sorted(errors, reverse=True))

    def test_stop_prevents_fictitious_bootstrap(self):
        states = {
            "root": {"STOP": Action(0.2, (Outcome(1, 0, payoff=0.8),))},
            "unreachable": {"STOP": Action(0, (Outcome(1, 0, payoff=99),))},
        }
        model = Model(states, "root")
        self.assertAlmostEqual(evaluate(model, (0, 0), 2, 0.7)["value"], 0.6)
        self.assertEqual(evaluate(model, (0, 0), 2, 0.7)["gradient"], (0, 0))
        states["root"]["STOP"] = Action(0, (Outcome(1, 0, "unreachable"),))
        with self.assertRaises(ValueError):
            Model(states, "root")

    def test_upfront_cost_and_failed_branch_are_retained(self):
        model = Model({"root": {"work": Action(0.4, (Outcome(0.5, 2, payoff=1), Outcome(0.5, 1, payoff=0)))}}, "root")
        self.assertAlmostEqual(evaluate(model, (0,), rate=math.log(2))["value"], -0.4 + 0.125)
        dropped = Model({"root": {"work": Action(0.4, (Outcome(1, 2, payoff=1),))}}, "root")
        self.assertNotEqual(evaluate(model, (0,))["value"], evaluate(dropped, (0,))["value"])

    def test_duration_must_remain_joint_with_continuation(self):
        model = Model({"root": {"work": Action(0, (Outcome(0.5, 1, payoff=0), Outcome(0.5, 3, payoff=2)))}}, "root")
        actual = evaluate(model, (0,), rate=-math.log(0.9))["value"]
        result = counterexamples()["duration_correlation"]
        self.assertAlmostEqual(actual, result["correct_expected_discounted_value"])
        self.assertGreater(result["incorrect_product_of_expectations"] - actual, 0.08)

    def test_GAE_counterexamples_reverse_gradient(self):
        records = counterexamples()
        for proper, ordinary in (
            (records["duration_GAE"]["correct_gradient"], records["duration_GAE"]["fixed_step_gradient"]),
            (
                records["entropic_GAE"]["entropic"]["gradient"],
                records["entropic_GAE"]["ordinary_expected_return"]["gradient"],
            ),
        ):
            self.assertLess(sum(x * y for x, y in zip(proper, ordinary)), 0)

    def test_inherited_undiscounted_oracle_agrees(self):
        result = inherited_crosscheck(self.model, self.theta)
        self.assertLess(max(result[k] for k in ("value_error", "gradient_error", "optimal_value_error")), 1e-12)

    def test_invalid_probability_and_nonfinite_inputs_reject(self):
        for p in (0, -0.1, math.nan, math.inf, True, 1 - 5e-13):
            with self.subTest(p=p), self.assertRaises(ValueError):
                Model({"root": {"work": Action(0, (Outcome(p, 0, payoff=1),))}}, "root")
        for v in (math.nan, math.inf, -1, True):
            with self.subTest(v=v), self.assertRaises(ValueError):
                evaluate(self.model, self.theta, eta=v)
        with self.assertRaises(ValueError):
            evaluate(self.model, self.theta[:-1])
        with self.assertRaises(ValueError):
            evaluate(self.model, self.theta[:-1] + (31,))

    def test_mutable_input_does_not_change_validated_model(self):
        states = {"root": {"STOP": Action(0, (Outcome(1, 0, payoff=1),))}}
        model = Model(states, "root")
        states["root"].clear()
        self.assertEqual(evaluate(model, (0,))["value"], 1)
        with self.assertRaises(TypeError):
            model.states["root"]["bad"] = Action(0, ())

    def test_cycles_and_ambiguous_terminal_laws_reject(self):
        for outcomes in (
            (Outcome(1, 1, "root"),),
            (Outcome(1, 1, "other"),),
            (Outcome(1, 1, "root", 2),),
            (Outcome(1, -1, payoff=2),),
        ):
            with self.subTest(outcomes=outcomes), self.assertRaises(ValueError):
                Model({"root": {"work": Action(0, outcomes)}}, "root")

    def test_enumeration_caps_fail_without_pruning(self):
        with self.assertRaises(ValueError):
            enumerate_trees(self.model, cap=1)
        with self.assertRaises(ValueError):
            path_value_gradient(self.model, self.theta, max_paths=1)

    def test_local_logit_gauge_and_large_risk_stability(self):
        shifted = tuple(x + 8 for x in self.theta)
        original, other = evaluate(self.model, self.theta, 20, 10), evaluate(self.model, shifted, 20, 10)
        self.assertAlmostEqual(original["value"], other["value"], places=12)
        self.assertLess(max(abs(x - y) for x, y in zip(original["gradient"], other["gradient"])), 1e-12)
        for state in self.model.states:
            mass = sum(g for (s, _), g in zip(self.model.coordinates(), original["gradient"]) if s == state)
            self.assertAlmostEqual(mass, 0, places=13)


if __name__ == "__main__":
    unittest.main()
