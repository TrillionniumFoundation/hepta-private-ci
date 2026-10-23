"""Adversarial source-cluster tail tests. All scores are synthetic fixtures."""
from dataclasses import replace
import unittest

from factorial_admission import ARMS, ScoreRow
from registered_factorial import RegisteredFactorialCohort
from registered_tail import (
    describe_source_cluster_tail, fractional_upper_tail,
)

H, I, D, R = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
UNIT = "measured_cpu_seconds"


def fixture(*, easy_draws=1, rare_failure=False):
    keys, rows = [], []
    for seed in (17, 29):
        for source in ("original-easy", "original-hard"):
            count = 10 if rare_failure else (
                easy_draws if source == "original-easy" else 1)
            for draw in range(count):
                world = f"{seed}/{source}"
                keys.append((seed, source, world, draw))
                for arm in ARMS:
                    if rare_failure:
                        # Same low mean can conceal different within-source
                        # distributions; the truth scorer is frozen and external.
                        loss = (4.0 if source == "original-easy" and draw == 9
                                else 0.0) if arm == "base_ndu" else 0.4
                    else:
                        loss = {"base_static": 1.0,
                                "base_ndu": (0.1 if source == "original-easy"
                                             else 2.0),
                                "trained_static": 1.0,
                                "trained_ndu": 1.0}[arm]
                    rows.append(ScoreRow(
                        arm, seed, source, world, draw, H, I, D, R,
                        loss, 2.0 if arm.endswith("static") else 2.4,
                        UNIT, True))
    registration = RegisteredFactorialCohort(
        tuple(keys), frozenset(("original-easy", "original-hard")),
        R, UNIT, 4.0)
    return registration, rows


class SourceClusterTailTests(unittest.TestCase):
    def test_equal_original_source_weight_survives_100_easy_draws(self):
        registration, rows = fixture(easy_draws=100)
        report = describe_source_cluster_tail(rows, registration)
        tail = report["source_mean_cvar90_external_loss"]
        self.assertAlmostEqual(tail["base_ndu"], 2.0)
        self.assertAlmostEqual(tail["base_static"], 1.0)
        self.assertAlmostEqual(
            report["source_tail_cvar90_inference_contrasts"]
            ["base_ndu_minus_static"], 1.0)
        self.assertAlmostEqual(
            report["paired_source_delta_upper_tail90"]["base"], 1.0)
        self.assertEqual(report["source_strata"], 4)
        self.assertFalse(report["scientific_superiority_established"])

    def test_draw_tail_exposes_rare_loss_hidden_in_source_mean(self):
        registration, rows = fixture(rare_failure=True)
        report = describe_source_cluster_tail(rows, registration)
        source_mean = report["source_mean_cvar90_external_loss"]
        draw_tail = report["within_source_draw_tail_cvar90_external_loss"]
        self.assertAlmostEqual(source_mean["base_ndu"], 0.4)
        self.assertAlmostEqual(source_mean["base_static"], 0.4)
        self.assertAlmostEqual(draw_tail["base_ndu"], 4.0)
        self.assertAlmostEqual(draw_tail["base_static"], 0.4)

    def test_paid_failures_remain_in_source_tail(self):
        registration, rows = fixture()
        failed = replace(rows[0], complete=False, external_loss=4.0,
                         physical_cost=9.0)
        rows[0] = failed
        report = describe_source_cluster_tail(rows, registration)
        self.assertEqual(report["retained_failed_arm_rows"], 1)
        self.assertGreater(
            report["within_source_draw_tail_cvar90_physical_cost"]
            ["base_static"], 2.0)
        # One of two independent training seeds has a failed source
        # (CVaR90=4); the other retains CVaR90=1. The registered estimand
        # averages these seed-level tails equally, yielding (4+1)/2=2.5.
        self.assertAlmostEqual(
            report["within_source_draw_tail_cvar90_external_loss"]
            ["base_static"], 2.5)

    def test_fractional_upper_tail_mass_is_not_ceiling_average(self):
        self.assertAlmostEqual(
            fractional_upper_tail([0.0] * 10 + [10.0]), 10.0 / 1.1)
        self.assertEqual(fractional_upper_tail([-7.0, -1.0]), -1.0)
        self.assertEqual(fractional_upper_tail([4.0] * 10), 4.0)

    def test_invalid_and_unregistered_rows_fail_closed(self):
        registration, rows = fixture()
        for changed in (
            rows[:-1],
            rows + [rows[0]],
            [replace(r, randomness_digest="f" * 64) if idx == 0 else r
             for idx, r in enumerate(rows)],
            [replace(r, external_loss=float("nan")) if idx == 0 else r
             for idx, r in enumerate(rows)],
            [replace(r, complete=False) if idx == 0 else r
             for idx, r in enumerate(rows)],
        ):
            with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                describe_source_cluster_tail(changed, registration)

    def test_declared_source_reuse_is_exposed_not_miscounted(self):
        registration, rows = fixture(easy_draws=10)
        report = describe_source_cluster_tail(rows, registration)
        self.assertEqual(report["source_strata"], 4)
        self.assertEqual(report["declared_unique_original_source_ids"], 2)
        self.assertEqual(report["declared_source_ids_reused_across_seeds"], 2)
        self.assertFalse(report["sampling_unit_independence_verified"])
        self.assertIsNone(report["independent_sampling_unit"])
        self.assertEqual(report["within_seed_weighting_unit"],
                         "original_source_within_training_seed")
        self.assertFalse(report["independent_outcome_attestation_verified"])
        self.assertFalse(report["scientific_superiority_established"])

    def test_reordering_does_not_change_tail_evidence(self):
        registration, rows = fixture(easy_draws=19)
        first = describe_source_cluster_tail(rows, registration)
        second = describe_source_cluster_tail(list(reversed(rows)), registration)
        self.assertEqual(first, second)
        self.assertEqual(first["registered_cohort_digest"],
                         registration.cohort_digest)

    def test_tail_input_rejects_empty_bool_and_nonfinite_values(self):
        for values in ([], [True], [float("nan")], [float("inf")],
                       [0.0, float("-inf")], "not numeric"):
            with self.subTest(values=values), self.assertRaises(ValueError):
                fractional_upper_tail(values)

    def test_physical_cost_unit_cannot_be_a_compute_proxy(self):
        registration, rows = fixture()
        rows[0] = replace(rows[0], unit="estimated_MACs")
        with self.assertRaises(ValueError):
            describe_source_cluster_tail(rows, registration)


if __name__ == "__main__":
    unittest.main()
