"""Manufactured producer-change regressions; no measured policy improvement."""

from dataclasses import fields, replace
import unittest

from .control_investment import calibrate_heads, fit_heads, predict
from .control_observations import continuation_label
from .control_test_fixtures import CRITIC_CONTEXT, row
from .critic_context import CriticContext, CriticContextError, context_digest


class ControlCriticContextTests(unittest.TestCase):
    def test_identical_numeric_state_cannot_reuse_heads_or_residuals_after_change(self):
        training = row("train")
        heads = calibrate_heads(
            fit_heads([training], context=CRITIC_CONTEXT),
            [row(f"cal-{i}", split="calibration") for i in range(12)],
            context=CRITIC_CONTEXT,
        )
        valid = predict(heads, training["state"], context=CRITIC_CONTEXT)
        self.assertIsNotNone(valid["value"]["conditional_residual"][1])
        for field in fields(CriticContext):
            changed = replace(CRITIC_CONTEXT, **{field.name: "0" * 64})
            with self.subTest(field=field.name):
                result = predict(heads, training["state"], context=changed)
                self.assertTrue(result["recalibration_required"])
                self.assertIn("recalibration_required", result["reason"])
                for name in ("implementation", "value"):
                    self.assertEqual(
                        result[name],
                        dict(
                            point=None,
                            supported=False,
                            unconditional_residual=None,
                            conditional_residual=None,
                        ),
                    )
        self.assertEqual(
            predict(heads, training["state"], context=CRITIC_CONTEXT), valid
        )

    def test_missing_context_cannot_be_inferred_from_rows_or_heads(self):
        sample = row("train")
        with self.assertRaises(CriticContextError):
            fit_heads([sample])
        heads = fit_heads([sample], context=CRITIC_CONTEXT)
        with self.assertRaises(CriticContextError):
            calibrate_heads(heads, [row("cal", split="calibration")])
        self.assertTrue(predict(heads, sample["state"])["recalibration_required"])
        legacy = replace(heads, context=None)
        self.assertTrue(
            predict(legacy, sample["state"], context=CRITIC_CONTEXT)[
                "recalibration_required"
            ]
        )
        with self.assertRaises(CriticContextError):
            calibrate_heads(
                legacy, [row("cal", split="calibration")], context=CRITIC_CONTEXT
            )
        sample.pop("context")
        with self.assertRaises(CriticContextError):
            fit_heads([sample], context=CRITIC_CONTEXT)

    def test_mixed_training_and_calibration_producers_are_rejected(self):
        changed = replace(CRITIC_CONTEXT, answer_sha256="0" * 64)
        training = row("train")
        altered = row("other", critic_context=changed)
        altered.pop("implementation")
        altered.pop("branches")
        with self.assertRaises(CriticContextError):
            fit_heads([training, altered], context=CRITIC_CONTEXT)
        heads = fit_heads([training], context=CRITIC_CONTEXT)
        with self.assertRaises(CriticContextError):
            calibrate_heads(
                heads,
                [row("cal", split="calibration", critic_context=changed)],
                context=CRITIC_CONTEXT,
            )
        with self.assertRaises(CriticContextError):
            calibrate_heads(
                heads,
                [row("cal", split="calibration", critic_context=changed)],
                context=changed,
            )
        self.assertEqual(heads.calibration_sources, ())

    def test_new_row_identity_cannot_relabel_old_observation_receipts(self):
        changed = replace(CRITIC_CONTEXT, generator_sha256="0" * 64)
        for label in ("implementation", "value"):
            with self.subTest(label=label):
                sample = row("train")
                sample["context"] = changed
                if label == "value":
                    sample.pop("implementation")
                with self.assertRaises(ValueError):
                    fit_heads([sample], context=changed)
        for key in ("evaluator_sha256", "utility_profile_sha256", "tariff_sha256"):
            sample = row("train")
            for branch in sample["branches"].values():
                branch[key] = "0" * 64
            with self.subTest(profile=key), self.assertRaises(ValueError):
                continuation_label(sample)

    def test_fresh_fit_and_disjoint_calibration_restore_bound_prediction(self):
        changed = replace(CRITIC_CONTEXT, answer_sha256="0" * 64)
        sample = row("new-train", critic_context=changed)
        heads = calibrate_heads(
            fit_heads([sample], context=changed),
            [
                row(f"new-cal-{i}", split="calibration", critic_context=changed)
                for i in range(12)
            ],
            context=changed,
        )
        result = predict(heads, sample["state"], context=changed)
        self.assertFalse(result["recalibration_required"])
        self.assertEqual(result["critic_context_sha256"], context_digest(changed))
        self.assertIsNotNone(result["value"]["point"])
        self.assertIsNotNone(result["value"]["conditional_residual"][1])
        self.assertFalse(result["production_admitted"])

    def test_uncalibrated_and_too_small_calibration_abstain(self):
        sample = row("training")
        fitted = fit_heads([sample], context=CRITIC_CONTEXT)
        missing = predict(fitted, sample["state"], context=CRITIC_CONTEXT)
        self.assertTrue(missing["recalibration_required"])
        self.assertIsNone(missing["implementation"]["point"])
        self.assertIsNone(missing["value"]["point"])
        sparse = calibrate_heads(
            fitted,
            [row("cal-one", split="calibration")],
            context=CRITIC_CONTEXT,
        )
        result = predict(sparse, sample["state"], context=CRITIC_CONTEXT)
        self.assertTrue(result["recalibration_required"])
        self.assertIsNone(result["value"]["point"])

    def test_partial_calibration_labels_cannot_publish_joint_points(self):
        sample = row("training")
        calibration = [row(f"cal-{i}", split="calibration") for i in range(12)]
        for observed in calibration:
            observed.pop("branches")
        heads = calibrate_heads(
            fit_heads([sample], context=CRITIC_CONTEXT),
            calibration,
            context=CRITIC_CONTEXT,
        )
        self.assertFalse(any(name == "value" for name, *_ in heads.residuals))
        result = predict(heads, sample["state"], context=CRITIC_CONTEXT)
        self.assertTrue(result["recalibration_required"])
        self.assertIsNone(result["implementation"]["point"])
        self.assertIsNone(result["value"]["point"])

    def test_wire_round_trip_and_invalid_manifest_rejection(self):
        wire = CRITIC_CONTEXT.to_wire()
        self.assertEqual(CriticContext.from_wire(wire), CRITIC_CONTEXT)
        self.assertEqual(
            context_digest(CriticContext.from_wire(wire)),
            context_digest(CRITIC_CONTEXT),
        )
        for key, value in (
            ("encoder_sha256", None),
            ("generator_sha256", "A" * 64),
            ("answer_sha256", "short"),
            ("unknown_identity", "0" * 64),
            ("schema", "old.schema"),
        ):
            with self.subTest(key=key), self.assertRaises(CriticContextError):
                CriticContext.from_wire(dict(wire, **{key: value}))
        wire.pop("settlement_sha256")
        with self.assertRaises(CriticContextError):
            CriticContext.from_wire(wire)


if __name__ == "__main__":
    unittest.main()
