"""Frozen measurement specifications and partial-label calibration controls."""

from copy import deepcopy
import unittest

from .contracts import digest
from .cost_ledger import CostItem
from .policy_metrics import calibration_metrics, freeze_evaluation_spec
from .shadow_risk import DISPOSITIONS


class PolicyMetricsTests(unittest.TestCase):
    def specification(self, **changes):
        options = dict(
            cost_rosters={
                policy: (CostItem(policy, "attempt", "other", policy, "clock"),)
                for policy in ("baseline", "candidate")
            },
            losses={action: dict(correct=0, error=1) for action in DISPOSITIONS},
            rates=dict(
                wall_seconds=1,
                process_cpu_seconds=1,
                energy_joules=1,
                external_charge=1,
            ),
            utility_unit="declared-loss",
        )
        options.update(changes)
        return freeze_evaluation_spec(**options)

    def test_spec_detaches_loss_and_pricing_aliases(self):
        losses = {action: dict(correct=0, error=1) for action in DISPOSITIONS}
        rates = dict(
            wall_seconds=1, process_cpu_seconds=1, energy_joules=1, external_charge=1
        )
        spec = self.specification(losses=losses, rates=rates)
        original = deepcopy(spec)
        losses["accept"]["error"] = 0
        rates["wall_seconds"] = 0
        self.assertEqual(spec, original)
        self.assertNotEqual(
            digest(self.specification(losses=losses, rates=rates)), digest(spec)
        )

    def test_duplicate_physical_operations_and_unbounded_calibration_spec_refuse(self):
        shared = CostItem("same-execution", "attempt", "other", "resource", "clock")
        with self.assertRaisesRegex(ValueError, "duplicate planned"):
            self.specification(
                cost_rosters={"baseline": (shared,), "candidate": (shared,)}
            )
        for bins in (
            [0, 0.5, 0.5, 1],
            [0, True, 1],
            [0, float("nan"), 1],
            [0, 0.5],
            [0] * 22,
        ):
            with self.subTest(bins=bins), self.assertRaises(ValueError):
                self.specification(bins=bins)

    def test_calibration_retains_unscored_predictions_and_unknown_truth(self):
        rows = [
            dict(probability=probability, truth=truth)
            for probability, truth in (
                (0.1, False),
                (0.9, True),
                (0.2, None),
                (None, None),
            )
        ]
        report = calibration_metrics(rows, [0, 0.5, 1])
        self.assertEqual(
            (
                report["planned"],
                report["predictions"],
                report["scored"],
                report["missing_or_unsupported_predictions"],
                report["unknown_labels_among_predictions"],
            ),
            (4, 3, 2, 1, 1),
        )
        self.assertEqual(
            (
                report["reliability"][0]["predictions"],
                report["reliability"][0]["unknown_labels"],
            ),
            (2, 1),
        )
        self.assertAlmostEqual(report["brier_known"], 0.01)
        self.assertAlmostEqual(report["ece_known"], 0.1)


if __name__ == "__main__":
    unittest.main()
