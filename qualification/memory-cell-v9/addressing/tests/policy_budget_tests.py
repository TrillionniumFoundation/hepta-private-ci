"""Global error-budget constraints and deterministic operating-point choices."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap
from addressing.contracts import OPERATIONS
from v9_addressing.policy import contract_comparison, fit_policies


class PolicyBudgetTests(unittest.TestCase):
    def test_contract_comparison_preserves_both_false_rejections_and_ood_benefit(self):
        rows = [{"operation": "current"}, {"operation": "reject"}]
        raw = [{"raw_operation": "current", "score": 0.9, "margin": 0.5, "capability_reason": None} for _ in rows]
        guarded = [{"raw_operation": "reject", "score": 1.0, "margin": 1.0, "capability_reason": "boundary"} for _ in rows]
        policies = {operation: {"threshold": 0.5, "margin": 0.0} for operation in OPERATIONS}
        result = contract_comparison(rows, raw, guarded, policies)
        self.assertEqual(result["explicit_contract_rejections"], {"known": 1, "ood": 1})
        self.assertEqual(result["raw_learned_with_same_frozen_policy"]["known_correct"], 1)
        self.assertEqual(result["after_contract_with_same_frozen_policy"]["known_correct"], 0)
        self.assertEqual(result["raw_learned_with_same_frozen_policy"]["ood_accepted"], 1)
        self.assertEqual(result["after_contract_with_same_frozen_policy"]["ood_accepted"], 0)

    def test_one_global_ood_allowance_is_not_rounded_down_six_times(self):
        rows = [{"operation": operation} for operation in OPERATIONS] + [{"operation": "reject"} for _ in range(20)]
        predictions = [{"raw_operation": operation, "score": 0.82, "margin": 0.5} for operation in OPERATIONS]
        predictions += [{"raw_operation": "current", "score": 0.83, "margin": 0.6}]
        predictions += [{"raw_operation": "reject", "score": 0.9, "margin": 0.7} for _ in range(19)]
        result = fit_policies(rows, predictions)
        self.assertEqual((result["global_ood_allowance"], result["global_ood_used"]), (1, 1))
        self.assertEqual((result["metrics"]["known_correct"], result["metrics"]["ood_accepted"]), (6, 1))
        self.assertEqual(sum(result["operation_ood_allocation"].values()), 1)
        self.assertTrue(result["empirical_gate_passed"])

    def test_wrong_supported_operation_cannot_spend_the_ood_budget(self):
        rows = [{"operation": operation} for operation in OPERATIONS] + [{"operation": "reject"} for _ in range(40)]
        predictions = [{"raw_operation": operation, "score": 0.85, "margin": 0.4} for operation in OPERATIONS]
        predictions[1] = {"raw_operation": OPERATIONS[0], "score": 0.95, "margin": 0.7}
        predictions += [{"raw_operation": "reject", "score": 0.9, "margin": 0.7} for _ in range(40)]
        result = fit_policies(rows, predictions)
        self.assertEqual(result["metrics"]["known_wrong_accepted"], 0)
        self.assertGreater(result["policies"][OPERATIONS[0]]["threshold"], 0.95)
        self.assertEqual(result["metrics"]["known_correct"], 4)
        self.assertFalse(result["empirical_gate_passed"])

    def test_calibration_cannot_restore_coverage_by_lowering_an_operating_point(self):
        rows = [{"operation": operation} for operation in OPERATIONS] + [{"operation": "reject"} for _ in range(40)]
        predictions = [{"raw_operation": operation, "score": 0.8, "margin": 0.4} for operation in OPERATIONS]
        predictions += [{"raw_operation": "reject", "score": 0.9, "margin": 0.7} for _ in range(40)]
        previous = {operation: {"threshold": 0.9, "margin": 0.15} for operation in OPERATIONS}
        result = fit_policies(rows, predictions, previous=previous)
        self.assertEqual(result["metrics"]["known_correct"], 0)
        self.assertTrue(all(result["policies"][name]["threshold"] >= 0.9
                            and result["policies"][name]["margin"] == 0.15 for name in OPERATIONS))
        self.assertFalse(result["empirical_gate_passed"])


if __name__ == "__main__":
    unittest.main()
