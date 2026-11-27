"""Independent finite-tree, numerical, and resource-accounting checks."""

from dataclasses import replace
from decimal import Decimal, localcontext
import math
import unittest

from .control import ControllerConfig, WorkBudget, choose, entropic_value


class TableBackend:
    def __init__(self, edges, forecasts, costs=None):
        self.edges, self.forecasts, self.costs = edges, forecasts, costs or {}
        self.actual_calls = {"prediction": 0, "transition": 0}

    def actions(self, state, content_control):
        actions = self.edges.get(state, {})
        return tuple(a for a in actions if content_control or a in {"refine_image", "refine_text"})

    def transition(self, state, action):
        self.actual_calls["transition"] += 1
        return self.edges[state][action]

    def predict(self, state):
        self.actual_calls["prediction"] += 1
        return self.forecasts[state]

    def action_cost(self, state, action):
        return self.costs.get((state, action), 1.0)

    def prediction_cost(self, state):
        return 0.25

    def state_key(self, state):
        return repr(state)

    def identity(self, state):
        return "immutable-input/objective/snapshot"


def decimal_ce(values, probabilities, gamma):
    with localcontext() as context:
        context.prec = 75
        v = [Decimal(str(x)) for x in values]
        p = [Decimal(str(x)) for x in probabilities]
        g = Decimal(str(gamma))
        if g == 0:
            return float(sum(x * q for x, q in zip(v, p)))
        return float(-sum(q * (-g * x).exp() for x, q in zip(v, p)).ln() / g)


def enumerate_paths(backend, state, depth, budget, gamma, penalty, path=(), spent=0.0):
    """Enumerate complete feasible stopping paths independently of controller."""
    values, probabilities = backend.forecasts[state]
    candidates = [(decimal_ce(values, probabilities, gamma) - penalty * spent, path)]
    if depth:
        for action, child in backend.edges.get(state, {}).items():
            cost = backend.action_cost(state, action)
            if cost <= budget:
                candidates.extend(enumerate_paths(backend, child, depth - 1, budget - cost,
                                                  gamma, penalty, path + (action,), spent + cost))
    return candidates


class ControlTests(unittest.TestCase):
    def test_tiny_gamma_wide_payoffs_and_zero_mass(self):
        for values, probabilities, gamma in [
            ([-1e8, 1e8], [0.5, 0.5], 1e-14),
            ([-1e8, 1e8], [0.5, 0.5], 1e-8),
            ([0.0, 100.0], [0.8, 0.2], 0.03),
            ([3.0, 6.0, -100.0], [0.7, 0.3, 0.0], 0.5),
        ]:
            expected = decimal_ce(values, probabilities, gamma)
            self.assertAlmostEqual(entropic_value(values, probabilities, gamma), expected,
                                   delta=max(1e-12, abs(expected) * 2e-12))
        self.assertEqual(entropic_value([7, 7], [0.1, 0.9], 10), 7)
        self.assertEqual(entropic_value([1, 5], [0.75, 0.25], 0), 2)
        extreme = entropic_value([-1e308, 1e308], [0.5, 0.5], 1e-308)
        self.assertAlmostEqual(extreme / 1e308, -math.log(math.cosh(1)), places=14)

    def test_invalid_probability_or_nonfinite_inputs_fail(self):
        for values, probabilities, gamma in [([], [], 1), ([1], [0], 1),
                                             ([1, 2], [0.4, 0.4], 1),
                                             ([1, 2], [-1, 2], 1),
                                             ([math.nan], [1], 1), ([1], [1], -1)]:
            with self.assertRaises(ValueError):
                entropic_value(values, probabilities, gamma)

    def test_recursive_policy_and_values_match_independent_oracle(self):
        backend = TableBackend(
            {"s": {"a": "a", "b": "b"}, "b": {"c": "c"}},
            {"s": ([0], [1]), "a": ([2], [1]), "b": ([-0.2, 0.4], [0.25, 0.75]),
             "c": ([4, 6], [0.8, 0.2])})
        config = ControllerConfig(horizon=2, cost_penalty=0.1, search_work_limit=20)
        budget = WorkBudget(100, 2, initial_work=1)
        result = choose(backend, "s", budget, config)
        expected, path = max(enumerate_paths(backend, "s", 2, result.generation_envelope,
                                            config.gamma, config.cost_penalty), key=lambda x: x[0])
        self.assertTrue(result.complete)
        self.assertEqual(result.action, path[0])
        self.assertAlmostEqual(result.value, expected, places=12)
        self.assertEqual(result.search_calls, backend.actual_calls)
        self.assertEqual(result.search_work, 4.0)
        self.assertEqual(choose(backend, "s", WorkBudget(100, 2), replace(config, policy="greedy")).action, "a")

    def test_risk_and_state_conditional_law_change_choice(self):
        backend = TableBackend({"s": {"safe": "safe", "risk": "risk"}},
                               {"s": ([0], [1]), "safe": ([4], [1]),
                                "risk": ([0, 12], [0.5, 0.5])})
        config = ControllerConfig(horizon=1, search_work_limit=10)
        aware = choose(backend, "s", WorkBudget(100, 1), config)
        neutral = choose(backend, "s", WorkBudget(100, 1), replace(config, policy="risk_neutral_mpc"))
        self.assertEqual((aware.action, neutral.action), ("safe", "risk"))
        backend.forecasts["risk"] = ([0, 12], [0.999, 0.001])
        self.assertEqual(choose(backend, "s", WorkBudget(100, 1), replace(config, policy="risk_neutral_mpc")).action, "safe")

    def test_oracle_respects_reserved_search_and_future_generation_cost(self):
        backend = TableBackend({"s": {"a": "a", "b": "b"}, "b": {"c": "c"}},
                               {"s": ([0], [1]), "a": ([2], [1]),
                                "b": ([0.1], [1]), "c": ([5], [1])})
        config = ControllerConfig(horizon=2, search_work_limit=10, search_fraction=1)
        for limit, expected_action in [(12, "a"), (13, "b")]:
            result = choose(backend, "s", WorkBudget(limit, 1), config)
            oracle = max(enumerate_paths(backend, "s", 2, result.generation_envelope, 1, 0),
                         key=lambda x: x[0])
            self.assertEqual((result.complete, result.action, result.value),
                             (True, expected_action, oracle[0]))

    def test_search_spend_execution_and_stop_conserve_budget(self):
        backend = TableBackend({"s": {"a": "a"}}, {"s": ([0], [1]), "a": ([2], [1])})
        budget = WorkBudget(5.5, 2, initial_work=1)
        result = choose(backend, "s", budget, ControllerConfig(search_work_limit=1.5, search_fraction=0.6))
        self.assertEqual((result.action, result.complete, result.search_work), ("a", True, 1.5))
        budget.charge_execution(backend.action_cost("s", result.action))
        self.assertEqual(budget.available, 0)
        with self.assertRaises(ValueError):
            budget.charge_execution(0.1)
        budget.finish_stop(2)
        self.assertEqual((budget.used, budget.finished, budget.calls),
                         (5.5, True, {"prediction": 2, "transition": 1, "execution": 1, "stop": 1}))
        with self.assertRaises(ValueError):
            choose(backend, "s", budget, ControllerConfig())

    def test_search_truncation_charges_attempted_neural_work(self):
        backend = TableBackend({"s": {"a": "a", "b": "b"}},
                               {"s": ([0], [1]), "a": ([2], [1]), "b": ([3], [1])})
        budget = WorkBudget(20, 1)
        result = choose(backend, "s", budget, ControllerConfig(search_work_limit=1.25))
        self.assertEqual((result.action, result.complete, result.search_work, result.search_calls),
                         (None, False, 1.25, {"prediction": 1, "transition": 1}))
        self.assertEqual(result.search_calls, backend.actual_calls)

    def test_fixed_router_and_allocation_ablation(self):
        backend = TableBackend({"s": {"refine_semantic": "best", "refine_image": "image"}},
                               {"s": ([0], [1]), "best": ([5], [1]), "image": ([1], [1])})
        fixed = choose(backend, "s", WorkBudget(20, 1), ControllerConfig(policy="fixed_dev_tuned"))
        router = choose(backend, "s", WorkBudget(20, 1), ControllerConfig(policy="learned_router"),
                        router=lambda state, actions: "refine_image")
        ablation = choose(backend, "s", WorkBudget(20, 1),
                          ControllerConfig(policy="allocation_only", horizon=1))
        self.assertEqual((fixed.action, router.action, ablation.action),
                         ("refine_semantic", "refine_image", "refine_image"))
        self.assertEqual(router.search_calls, {"router": 1})
        self.assertEqual(fixed.search_work, 0)

    def test_identity_drift_and_in_place_prediction_rejected(self):
        backend = TableBackend({"s": {"a": "a"}}, {"s": ([0], [1]), "a": ([1], [1])})
        backend.identity = lambda state: state
        with self.assertRaisesRegex(ValueError, "identity"):
            choose(backend, "s", WorkBudget(20, 1), ControllerConfig())
        backend = TableBackend({}, {"s": ([0], [1])})
        backend.state_key = lambda state: str(backend.actual_calls["prediction"])
        with self.assertRaisesRegex(ValueError, "mutated"):
            choose(backend, "s", WorkBudget(20, 1), ControllerConfig())
        backend = TableBackend({}, {"s": ([0], [1])})
        backend.identity = lambda state: str(backend.actual_calls["prediction"])
        with self.assertRaisesRegex(ValueError, "identity"):
            choose(backend, "s", WorkBudget(20, 1), ControllerConfig())


if __name__ == "__main__":
    unittest.main()
