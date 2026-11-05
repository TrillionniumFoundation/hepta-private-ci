"""Independent full evaluation of policies built from local certificates."""

import random
import unittest

from .core import Outcome, evaluate, softmax_policy
from .policy_gate import guarded_update, initial_value_gate


class PolicyGateTests(unittest.TestCase):
    def test_rounding_mass_cannot_invent_gain_at_large_constant_value(self):
        base, proposal = {"s": {"a": 1 - 5e-13}}, {"s": {"a": 1.0}}
        result = guarded_update(base, proposal, {"s": {"a": (1e12, 1e12)}}, "s", 0.1)
        self.assertEqual(result["decision"], "no-update")
        self.assertEqual(result["proposed_gated_policy_gain_lower"], 0.0)
        base = {"s": {"a": 0.1, "b": 0.2, "c": 0.7}}
        proposal = {"s": {"a": 0.2, "b": 0.3, "c": 0.5}}
        result = guarded_update(base, proposal,
            {"s": {a: (1e12, 1e12) for a in base["s"]}}, "s", 0.0)
        self.assertEqual(result["decision"], "no-update")

    def test_delayed_gain_requires_full_value_or_staged_improvement(self):
        nodes = {"s": {"STOP": (Outcome(1),),
                       "learn": (Outcome(1, cost=0.1, next_state="next"),)},
                 "next": {"STOP": (Outcome(1),), "use": (Outcome(1, reward=1),)}}
        base = {s: {a: float(a == "STOP") for a in row} for s, row in nodes.items()}
        proposal = {s: {a: float(a != "STOP") for a in row} for s, row in nodes.items()}
        old, new = evaluate(nodes, "s", base), evaluate(nodes, "s", proposal)
        intervals = {s: {a: (q, q) for a, q in row.items()}
                     for s, row in old["action_values"].items()}
        self.assertEqual(guarded_update(base, proposal, intervals, "s", 0.01)["decision"], "no-update")
        gate = initial_value_gate((new["value"], new["value"]), (0.0, 0.0), 0.01)
        self.assertEqual(gate["decision"], "adopt")
        self.assertAlmostEqual(gate["net_gain_lower"], 0.89)

    def test_random_models_preserve_global_bound(self):
        rng = random.Random(19027)
        for trial in range(50):
            nodes = {}
            for i in range(4):
                nodes[str(i)] = {"STOP": (Outcome(1, reward=rng.uniform(-0.5, 0.5)),),
                    "continue": tuple(Outcome(0.5, reward=rng.uniform(-0.2, 0.8),
                        cost=rng.uniform(0, 0.1), duration=rng.uniform(0, 2),
                        next_state=str(i + 1) if i < 3 else None) for _ in range(2))}
            make = lambda: {s: {a: rng.uniform(-1, 1) for a in acts} for s, acts in nodes.items()}
            base, proposed = softmax_policy(nodes, make()), softmax_policy(nodes, make())
            ev = evaluate(nodes, "0", base, eta=1.3, rho=0.2)
            intervals = {s: {a: (q - 0.001, q + 0.001) for a, q in row.items()}
                         for s, row in ev["action_values"].items() if s != "2"}
            result = guarded_update(base, proposed, intervals, "0", verification_cost=0.0001)
            actual = evaluate(nodes, "0", result["policy"], eta=1.3, rho=0.2)["value"]
            self.assertGreaterEqual(actual - ev["value"] - 0.0001 + 1e-12,
                                    result["returned_policy_net_gain_lower"])
            self.assertEqual(result["policy"]["2"], base["2"])

    def test_continue_beats_stop_but_is_worse_than_baseline(self):
        nodes = {"s": {"STOP": (Outcome(1, reward=0),),
                       "continue": (Outcome(1, reward=0.3),),
                       "base": (Outcome(1, reward=0.8),)}}
        base = {"s": {"STOP": 0.0, "continue": 0.0, "base": 1.0}}
        proposal = {"s": {"STOP": 0.0, "continue": 1.0, "base": 0.0}}
        q = evaluate(nodes, "s", base)["action_values"]
        bounds = {s: {a: (v, v) for a, v in row.items()} for s, row in q.items()}
        result = guarded_update(base, proposal, bounds, "s", verification_cost=0.02)
        self.assertEqual(result["decision"], "no-update")
        self.assertEqual(result["returned_policy_net_gain_lower"], -0.02)
        self.assertEqual(result["policy"], base)

    def test_missing_coverage_and_cost_block_update(self):
        base, proposed = {"s": {"a": 1.0, "b": 0.0}}, {"s": {"a": 0.0, "b": 1.0}}
        self.assertEqual(guarded_update(base, proposed, {}, "s")["decision"], "no-update")
        bounds = {"s": {"a": (0.0, 0.0), "b": (0.5, 0.5)}}
        self.assertEqual(guarded_update(base, proposed, bounds, "s", 0.51)["decision"], "no-update")
        self.assertEqual(guarded_update(base, proposed, bounds, "s", 0.49)["decision"], "adopt")

    def test_invalid_evidence_is_not_treated_as_zero_error(self):
        base, proposed = {"s": {"a": 1.0, "b": 0.0}}, {"s": {"a": 0.0, "b": 1.0}}
        for bounds in ({"s": {}}, {"s": {"a": (0, 0), "b": (1, float("nan"))}}):
            with self.assertRaises(ValueError):
                guarded_update(base, proposed, bounds, "s")


if __name__ == "__main__":
    unittest.main()
