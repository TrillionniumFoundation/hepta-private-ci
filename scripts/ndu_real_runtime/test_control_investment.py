"""Manufactured shadow-head tests; no real-world policy benefit claim."""

from dataclasses import replace
import unittest

from .control_investment import calibrate_heads, fit_heads, predict
from .control_test_fixtures import CRITIC_CONTEXT, row


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
                fit_heads([sample], context=CRITIC_CONTEXT)
        sample = row("s")
        sample["branch_snapshot_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "Implementation observation"):
            fit_heads([sample], context=CRITIC_CONTEXT)
        heads = fit_heads([row("training")], context=CRITIC_CONTEXT)
        calibration = row("calibration", split="calibration")
        calibration["implementation"] = row("another")["implementation"]
        with self.assertRaisesRegex(ValueError, "Implementation observation"):
            calibrate_heads(heads, [calibration], context=CRITIC_CONTEXT)

    def test_fit_public_inference_and_training_freeze(self):
        samples = [
            row(f"s{i}", belief=float(i % 2), success=bool(i % 2), gain=i % 2)
            for i in range(24)
        ]
        heads = fit_heads(samples, context=CRITIC_CONTEXT)
        low, high = samples[0]["state"], samples[1]["state"]
        self.assertLess(
            predict(heads, low, context=CRITIC_CONTEXT)["implementation"]["point"],
            predict(heads, high, context=CRITIC_CONTEXT)["implementation"]["point"],
        )
        self.assertLess(
            predict(heads, low, context=CRITIC_CONTEXT)["value"]["point"],
            predict(heads, high, context=CRITIC_CONTEXT)["value"]["point"],
        )
        frozen = predict(heads, high, context=CRITIC_CONTEXT)
        samples[1]["branches"]["continue"]["gross_utility"] = -50
        self.assertEqual(predict(heads, high, context=CRITIC_CONTEXT), frozen)
        self.assertFalse(frozen["production_admitted"])
        with self.assertRaises(ValueError):
            predict(
                heads,
                dict(state=high, reference="hidden target"),
                context=CRITIC_CONTEXT,
            )
        self.assertIsNone(
            predict(heads, replace(high, context="unseen"), context=CRITIC_CONTEXT)[
                "value"
            ]["point"]
        )
        self.assertIsNone(
            predict(heads, replace(high, budget=90), context=CRITIC_CONTEXT)["value"][
                "point"
            ]
        )
        self.assertIsNone(
            predict(
                heads,
                replace(high, legal_actions=("STOP", "READ")),
                context=CRITIC_CONTEXT,
            )["value"]["point"]
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
                fit_heads([row("s", split=split)], context=CRITIC_CONTEXT)
        with self.assertRaises(ValueError):
            fit_heads([row("s"), row("s")], context=CRITIC_CONTEXT)
        heads = fit_heads([row("s")], context=CRITIC_CONTEXT)
        with self.assertRaises(ValueError):
            calibrate_heads(
                heads, [row("s", split="calibration")], context=CRITIC_CONTEXT
            )

    def test_missing_labels_abstain_without_imputing_zero(self):
        sample = row("s")
        sample.pop("implementation")
        sample.pop("branches")
        heads = fit_heads([sample], context=CRITIC_CONTEXT)
        self.assertEqual(heads.unknown_training_labels, (1, 1))
        self.assertIsNone(
            predict(heads, sample["state"], context=CRITIC_CONTEXT)["implementation"][
                "point"
            ]
        )
        self.assertIsNone(
            predict(heads, sample["state"], context=CRITIC_CONTEXT)["value"]["point"]
        )

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
        heads = calibrate_heads(
            fit_heads(training, context=CRITIC_CONTEXT),
            calibration,
            context=CRITIC_CONTEXT,
        )
        stable = predict(heads, training[0]["state"], context=CRITIC_CONTEXT)["value"]
        changed = predict(heads, training[1]["state"], context=CRITIC_CONTEXT)["value"]
        self.assertEqual(stable["unconditional_residual"][0], 12)
        self.assertEqual(changed["conditional_residual"][0], 12)
        self.assertGreater(
            changed["conditional_residual"][1], stable["conditional_residual"][1]
        )
        with self.assertRaises(ValueError):
            calibrate_heads(heads, calibration, context=CRITIC_CONTEXT)
        small = calibrate_heads(
            fit_heads(training, context=CRITIC_CONTEXT),
            calibration[:1],
            context=CRITIC_CONTEXT,
        )
        self.assertIsNone(
            predict(small, training[0]["state"], context=CRITIC_CONTEXT)["value"][
                "conditional_residual"
            ][1]
        )


if __name__ == "__main__":
    unittest.main()
