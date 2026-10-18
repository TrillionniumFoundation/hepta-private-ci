"""Nonlinear-terminal FBSDE reference: contraction, matching and budget truth."""

import json
import math
import subprocess
import sys
import unittest
from pathlib import Path

from hepta_sngr_nonlinear_shadow import (
    ContinuationOracle,
    ShadowError,
    TanhTerminal,
    matched_budget_comparison,
    manufactured_sweep,
    nonlinear_shoot,
)


class NonlinearMultipleShootingTests(unittest.TestCase):
    def test_reduces_to_constant_terminal_when_slope_zero(self):
        result = nonlinear_shoot(1.0, (0.2, 0.3, 0.5), TanhTerminal(0.0, 0.7))
        self.assertTrue(result.accepted)
        self.assertAlmostEqual(result.initial_utility, 0.7)
        self.assertAlmostEqual(result.final_state, 1.7)
        self.assertLess(result.maximum_interface_residual, 1e-12)

    def test_nonlinear_continuation_matches_unsplit_shooting(self):
        for terminal in (TanhTerminal(0.5, 0.2), TanhTerminal(-0.7, -0.3), TanhTerminal(0.0, 0.5)):
            with self.subTest(terminal=terminal):
                single = nonlinear_shoot(0.3, (1.0,), terminal)
                split = nonlinear_shoot(0.3, (0.1, 0.2, 0.3, 0.4), terminal)
                self.assertTrue(single.accepted)
                self.assertTrue(split.accepted)
                self.assertAlmostEqual(single.initial_utility, split.initial_utility, places=9)
                self.assertAlmostEqual(single.final_state, split.final_state, places=9)
                self.assertLess(split.maximum_interface_residual, 1e-9)

    def test_terminal_reset_may_look_good_but_violates_interface(self):
        t = TanhTerminal(0.6, 0.25)
        result = matched_budget_comparison(0.4, (0.25, 0.25, 0.5), t)
        self.assertTrue(result["segmented_continuation"]["accepted"])
        self.assertFalse(result["naive_terminal_reset"]["accepted"])
        self.assertLess(result["naive_terminal_reset"]["terminal_residual"], 1e-8)
        self.assertGreater(result["naive_terminal_reset"]["maximum_interface_residual"], 1e-3)

    def test_global_contraction_guard_even_when_local_slices_short(self):
        with self.assertRaisesRegex(ShadowError, "whole-horizon"):
            nonlinear_shoot(0.0, (0.1,) * 10, TanhTerminal(1.0, 0.1))
        with self.assertRaisesRegex(ShadowError, "whole-horizon"):
            nonlinear_shoot(0.0, (0.1,) * 10, TanhTerminal(-1.0, 0.1))

    def test_explicit_budget_exhaustion_not_fake_acceptance(self):
        with self.assertRaisesRegex(ShadowError, "budget exhausted"):
            nonlinear_shoot(0.4, (0.25, 0.25, 0.5), TanhTerminal(0.6, 0.25), budget=2)

    def test_guard_nonfinite_horizon_and_invalid_budget(self):
        bad = [(math.nan,), (0.0,), (-0.1,), (), (math.inf,), (0.01,)*65]
        for durations in bad:
            with self.subTest(durations=durations), self.assertRaises(ShadowError):
                nonlinear_shoot(0.2, durations, TanhTerminal(0.4, 0.3))
        for terminal in (TanhTerminal(math.nan, 0.0), TanhTerminal(0.1, math.inf)):
            with self.assertRaises(ShadowError):
                nonlinear_shoot(0.2, (0.1,), terminal)
        for budget in (0, -1, 100000, 1.5):
            with self.assertRaises(ShadowError):
                nonlinear_shoot(0.2, (0.1,), TanhTerminal(0.1, 0.0), budget=budget)

    def test_fixed_point_residual_bounds(self):
        t = TanhTerminal(0.4, 0.2)
        oracle = ContinuationOracle(t, 1000, 1e-12)
        y = oracle.value(0.3, 0.9)
        self.assertLess(abs(y - t.evaluate(0.3 + 0.9*y)), 1e-12)
        self.assertGreater(oracle.calls, 0)

    def test_strict_oracle_limit_prevents_unbounded_computation(self):
        with self.assertRaises(ShadowError):
            ContinuationOracle(TanhTerminal(0.1, 0.0), 1, 0.0)
        with self.assertRaises(ShadowError):
            ContinuationOracle(TanhTerminal(0.1, 0.0), 1, math.nan)

    def test_matched_budget_accounts_actual_cost(self):
        result = matched_budget_comparison(0.4, (0.25, 0.25, 0.5), TanhTerminal(0.6, 0.25), 2048)
        for arm in ("single_shoot", "segmented_continuation", "naive_terminal_reset"):
            self.assertLessEqual(result[arm]["oracle_calls"], 2048)
        self.assertGreater(result["segmented_continuation"]["oracle_calls"], result["single_shoot"]["oracle_calls"])
        self.assertEqual(result["evidence_class"], "synthetic_nonlinear_zero_noise_not_model_efficacy")

    def test_manufactured_sweep_is_auditable_and_costed(self):
        report = manufactured_sweep()
        self.assertEqual(report["case_count"], 24)
        self.assertEqual(report["segmented_passes"], 24)
        self.assertLess(report["reset_passes"], 24)
        self.assertGreater(report["mean_segmented_calls"], report["mean_single_calls"])
        self.assertTrue(all(row["segmented_calls"] <= report["budget_each_arm"] for row in report["cases"]))
        self.assertEqual(report, manufactured_sweep())

    def test_sweep_guards(self):
        for count in (0, -1, 129, 1.5):
            with self.assertRaises(ShadowError):
                manufactured_sweep(case_count=count)
        with self.assertRaises(ShadowError):
            manufactured_sweep(budget=0)

    def test_command_line_deterministic(self):
        script = Path(__file__).with_name("hepta_sngr_nonlinear_shadow.py")
        a = subprocess.check_output([sys.executable, str(script), "--demo"], text=True)
        b = subprocess.check_output([sys.executable, str(script), "--demo"], text=True)
        self.assertEqual(a, b)
        self.assertTrue(json.loads(a)["segmented_continuation"]["accepted"])


if __name__ == "__main__":
    unittest.main()
