"""Finite differential checks and actual waited tool-process integration tests."""

import unittest
from unittest.mock import patch

import numpy as np

from ...oracle import Branch, policy_gradient
from .tool_factorial import (
    ACTIONS,
    break_even,
    build_model,
    fit,
    flat_gradient,
    recursive_gradient,
    references,
    qualification_conforms,
)
from .tool_runtime import invoke, run_episode
from . import tool_runtime


class ToolGradientTests(unittest.TestCase):
    def test_gradients_match_inherited_complete_path_oracle_and_finite_difference(self):
        model = build_model()
        logits = np.random.default_rng(701).normal(0, 0.4, (len(model["histories"]), 3))
        value, flat = flat_gradient(model, logits)
        recursive_value, recursive = recursive_gradient(model, logits)
        self.assertAlmostEqual(value, recursive_value, places=13)
        np.testing.assert_allclose(flat, recursive, rtol=1e-11, atol=1e-13)
        nodes = {
            str(i): {
                action: tuple(
                    Branch(mass, cost, str(child) if child >= 0 else None, terminal if child < 0 else None)
                    for aj, mass, child, terminal, cost in edges
                    if aj == ai
                )
                for ai, action in enumerate(ACTIONS)
            }
            for i, edges in enumerate(model["branches"])
        }
        supplied = {str(i): dict(zip(ACTIONS, row)) for i, row in enumerate(logits.tolist())}
        old = policy_gradient(nodes, "0", supplied, 2.0)
        self.assertAlmostEqual(old["value"], value, places=13)
        expected = [[old["gradient"][str(i)][a] for a in ACTIONS] for i in range(len(logits))]
        np.testing.assert_allclose(flat, expected, rtol=1e-11, atol=1e-13)
        for state, action in ((0, 1), (1, 2), (len(logits) - 1, 0)):
            plus, minus = logits.copy(), logits.copy()
            plus[state, action] += 1e-5
            minus[state, action] -= 1e-5
            numerical = (flat_gradient(model, plus)[0] - flat_gradient(model, minus)[0]) / 2e-5
            self.assertAlmostEqual(numerical, recursive[state, action], places=9)

    def test_equal_initialization_real_updates_and_parameter_equivalence(self):
        model = build_model()
        flat, a = fit(model, 709, "inherited_flat_ce", updates=25)
        recursive, b = fit(model, 709, "recursive_ce", updates=25)
        np.testing.assert_allclose(flat, recursive, atol=1e-12, rtol=1e-12)
        self.assertEqual((a["actual_updates"], b["actual_updates"]), (25, 25))
        self.assertEqual(a["initial_parameter_sha256"], b["initial_parameter_sha256"])
        self.assertNotEqual(a["initial_parameter_sha256"], a["final_parameter_sha256"])
        self.assertGreater(a["final_stochastic_ce"], a["ce_trace"][0])

    def test_fixed_schedule_is_exhaustive_and_adaptive_reference_has_legal_information(self):
        model = build_model()
        result = references(model)
        self.assertEqual(result["schedules_enumerated"], 31)
        self.assertEqual(result["fixed"]["schedule"], ("REPAIR", "REPAIR", "STOP"))
        self.assertGreater(result["adaptive_ce"], result["fixed"]["ce"])
        self.assertEqual(result["adaptive_policy"][()], "CHECK")
        self.assertEqual(result["adaptive_policy"][(("CHECK", "0"),)], "STOP")
        self.assertEqual(result["adaptive_policy"][(("CHECK", "2"),)], "REPAIR")

    def test_break_even_requires_equal_quality_positive_cpu_savings_and_complete_cost(self):
        fixed = {"quality": 1.0, "cpu_s": 2.0}
        saved = break_even(5.0, fixed, {"quality": 1.0, "cpu_s": 1.0})
        self.assertEqual(saved["services_measured_scope_only"], 6)
        self.assertIsNone(saved["services"])
        self.assertIsNone(break_even(5.0, fixed, {"quality": 0.5, "cpu_s": 1.0})["services"])
        self.assertIsNone(break_even(5.0, fixed, {"quality": 1.0, "cpu_s": 3.0})["services_measured_scope_only"])

    def test_expired_qualification_retains_failed_verifier_without_dereferencing_null(self):
        def corrupt_oracle(mode, path, *args, **kwargs):
            if mode == "ORACLE":
                path.write_text("def solve(: pass", encoding="utf-8")
            return invoke(mode, path, *args, **kwargs)

        task = {"id": "development-expiry-and-verifier-failure", "scale": 2, "offset": 3, "bugs": []}
        with patch.object(tool_runtime, "invoke", side_effect=corrupt_oracle):
            row = run_episode(lambda h: "CHECK" if len(h) % 2 == 0 else "REPAIR", task)
        self.assertFalse(qualification_conforms([row]))
        self.assertEqual((row["status"], row["verification_status"]), ("expired", "failed"))
        self.assertEqual(len(row["events"]), 6)
        self.assertIsNone(row["events"][-1]["result"])
        self.assertIn("SyntaxError", row["events"][-1]["stderr"])


if __name__ == "__main__":
    unittest.main()
