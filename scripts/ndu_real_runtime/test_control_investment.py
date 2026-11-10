"""Manufactured shadow-head tests; no real-world policy benefit claim."""

from dataclasses import replace
import unittest

from .control_investment import calibrate_heads, fit_heads, predict
from .control_test_fixtures import row


class ControlInvestmentTests(unittest.TestCase):
    def test_implementation_receipt_cannot_be_transplanted_to_other_row(self):
        for key, value in (
            ("source_id", "other-source"),
            ("pre_state_sha256", "0" * 64),
            ("action", "REPAIR"),
            ("observation_id", "other-observation"),
            ("branch_snapshot_sha256", "0" * 64),
        ):
            sample = row("s")
            sample["implementation"][key] = value
            with self.assertRaisesRegex(ValueError, "Implementation observation"):
                fit_heads([sample])
        sample = row("s")
        sample["branch_snapshot_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "Implementation observation"):
            fit_heads([sample])
        heads = fit_heads([row("training")])
        calibration = row("calibration", split="calibration")
        calibration["implementation"] = row("another")["implementation"]
        with self.assertRaisesRegex(ValueError, "Implementation observation"):
            calibrate_heads(heads, [calibration])

    def test_fit_public_inference_and_training_freeze(self):
        samples = [
            row(f"s{i}", belief=float(i % 2), success=bool(i % 2), gain=i % 2)
            for i in range(24)
        ]
        heads = fit_heads(samples)
        low, high = samples[0]["state"], samples[1]["state"]
        self.assertLess(
            predict(heads, low)["implementation"]["point"],
            predict(heads, high)["implementation"]["point"],
        )
        self.assertLess(
            predict(heads, low)["value"]["point"],
            predict(heads, high)["value"]["point"],
        )
        frozen = predict(heads, high)
        samples[1]["branches"]["continue"]["gross_utility"] = -50
        self.assertEqual(predict(heads, high), frozen)
        self.assertFalse(frozen["production_admitted"])
        with self.assertRaises(ValueError):
            predict(heads, dict(state=high, reference="hidden target"))
        self.assertIsNone(
            predict(heads, replace(high, context="unseen"))["value"]["point"]
        )
        self.assertIsNone(predict(heads, replace(high, budget=90))["value"]["point"])
        self.assertIsNone(
            predict(heads, replace(high, legal_actions=("STOP", "READ")))["value"][
                "point"
            ]
        )
        for changes in (
            dict(belief=-0.1),
            dict(freshness=-1),
            dict(budget=float("inf")),
            dict(action="VERIFY"),
            dict(legal_actions=("STOP", "READ", "UNPAID")),
        ):
            with self.assertRaises(ValueError):
                replace(high, **changes)

    def test_training_partition_duplicate_and_calibration_overlap_reject(self):
        for split in ("calibration", "future", "confirmation"):
            with self.assertRaises(ValueError):
                fit_heads([row("s", split=split)])
        with self.assertRaises(ValueError):
            fit_heads([row("s"), row("s")])
        heads = fit_heads([row("s")])
        with self.assertRaises(ValueError):
            calibrate_heads(heads, [row("s", split="calibration")])

    def test_missing_labels_abstain_without_imputing_zero(self):
        sample = row("s")
        sample.pop("implementation")
        sample.pop("branches")
        heads = fit_heads([sample])
        self.assertEqual(heads.unknown_training_labels, (1, 1))
        self.assertIsNone(predict(heads, sample["state"])["implementation"]["point"])
        self.assertIsNone(predict(heads, sample["state"])["value"]["point"])

    def test_pooled_and_conditional_group_residuals_count_sources(self):
        training = [row("t0"), row("t1", context="changed")]
        calibration = [
            row(f"c{i}", split="calibration", context=context, gain=gain)
            for i in range(12)
            for context, gain in (("stable", 0.3), ("changed", -1.0))
        ]
        for index, sample in enumerate(calibration):
            sample["observation_id"] += f"/{index}"
            sample["implementation"]["observation_id"] = sample["observation_id"]
        heads = calibrate_heads(fit_heads(training), calibration)
        stable = predict(heads, training[0]["state"])["value"]
        changed = predict(heads, training[1]["state"])["value"]
        self.assertEqual(stable["unconditional_residual"][0], 12)
        self.assertEqual(changed["conditional_residual"][0], 12)
        self.assertGreater(
            changed["conditional_residual"][1], stable["conditional_residual"][1]
        )
        with self.assertRaises(ValueError):
            calibrate_heads(heads, calibration)
        small = calibrate_heads(fit_heads(training), calibration[:1])
        self.assertIsNone(
            predict(small, training[0]["state"])["value"]["conditional_residual"][1]
        )


if __name__ == "__main__":
    unittest.main()
