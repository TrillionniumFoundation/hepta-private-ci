"""Adversarial paired-factorial receipt tests; all outcomes are synthetic."""
from dataclasses import replace
import unittest
from factorial_admission import ARMS, ScoreRow, describe_factorial, verify_and_pair

H = "a" * 64
I = "b" * 64
D = "c" * 64
R = "d" * 64


def fixture():
    result = []
    for seed in (17, 29):
        for source in ("original-1", "original-2"):
            for index, arm in enumerate(ARMS):
                result.append(ScoreRow(
                    arm, seed, source, f"{seed}:{source}", 0, H, I, D, R,
                    (1.0, 0.8, 0.9, 0.6)[index],
                    (2.0, 2.1, 2.0, 2.2)[index],
                    "measured_cpu_seconds", True))
    return result


def evaluate(rows):
    return describe_factorial(
        rows, frozen_scoring_digest=R,
        allowed_sources={"original-1", "original-2"})


class FactorialTests(unittest.TestCase):
    def test_paired_contrasts_are_descriptive_not_causal(self):
        report = evaluate(fixture())
        self.assertEqual(report["paired_world_draws"], 4)
        self.assertEqual(report["independent_training_seeds"], 2)
        self.assertAlmostEqual(report["inference_effect_on_base"], -0.2)
        self.assertAlmostEqual(report["training_effect_under_static"], -0.1)
        self.assertAlmostEqual(report["inference_effect_after_training"], -0.3)
        self.assertAlmostEqual(report["factorial_interaction"], -0.1)
        self.assertFalse(report["causal_or_statistical_superiority_established"])

    def test_missing_arm_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            evaluate([r for r in fixture()
                      if not (r.seed == 17 and r.arm == "base_ndu")])

    def test_unpaired_draw_rejected(self):
        rows = fixture()
        rows[3] = replace(rows[3], randomness_digest="f" * 64)
        with self.assertRaisesRegex(ValueError, "unpaired"):
            evaluate(rows)

    def test_changed_shared_decoder_rejected(self):
        rows = fixture()
        rows[2] = replace(rows[2], decoder_digest="f" * 64)
        with self.assertRaisesRegex(ValueError, "unpaired"):
            evaluate(rows)

    def test_scoring_redefinition_rejected(self):
        rows = fixture()
        rows[2] = replace(rows[2], scoring_digest="f" * 64)
        with self.assertRaisesRegex(ValueError, "untrusted"):
            evaluate(rows)

    def test_wrong_input_or_cost_units_rejected(self):
        for kwargs in ({"input_digest": "e" * 64},
                       {"unit": "estimated_MACs"},
                       {"unit": "measured_wall_seconds"}):
            rows = fixture()
            rows[0] = replace(rows[0], **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                evaluate(rows)

    def test_failed_outputs_not_dropped(self):
        rows = fixture()
        rows[0] = replace(rows[0], complete=False)
        with self.assertRaisesRegex(ValueError, "failed output"):
            evaluate(rows)

    def test_one_seed_and_duplicate_arms_rejected(self):
        with self.assertRaisesRegex(ValueError, "seeds"):
            evaluate([r for r in fixture() if r.seed == 17])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate(fixture() + [fixture()[0]])

    def test_nonfinite_and_negative_external_loss_rejected(self):
        for loss in (-1, float("nan"), float("inf")):
            rows = fixture()
            rows[0] = replace(rows[0], external_loss=loss)
            with self.subTest(loss=loss), self.assertRaises(ValueError):
                evaluate(rows)

    def test_no_unregistered_original_source(self):
        rows = fixture()
        rows[0] = replace(rows[0], original_source="unregistered")
        with self.assertRaises(ValueError):
            evaluate(rows)


if __name__ == "__main__":
    unittest.main()
