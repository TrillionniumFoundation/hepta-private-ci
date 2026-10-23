"""Synthetic adversarial 2x2 cohort and attribution tests; not model evidence."""
from dataclasses import replace
import unittest

from factorial_admission import ARMS, ScoreRow
from registered_factorial import (
    RegisteredFactorialCohort, describe_registered_factorial,
)

H, I, D, R = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
UNIT = "measured_cpu_seconds"


def fixture(*, repeated_easy_draws=1):
    keys, rows = [], []
    for seed in (17, 29):
        for source in ("original-easy", "original-hard"):
            count = repeated_easy_draws if source == "original-easy" else 1
            for draw in range(count):
                world = f"{seed}-{source}"
                keys.append((seed, source, world, draw))
                for arm in ARMS:
                    base = {
                        "base_static": 1.0,
                        "base_ndu": 0.9 if source == "original-easy" else 2.0,
                        "trained_static": 1.0,
                        "trained_ndu": 1.0,
                    }[arm]
                    cost = 2.0 if arm in ("base_static", "trained_static") else 2.2
                    rows.append(ScoreRow(
                        arm, seed, source, world, draw, H, I, D, R,
                        base, cost, UNIT, True))
    return RegisteredFactorialCohort(
        tuple(keys), frozenset(("original-easy", "original-hard")),
        R, UNIT, 3.0), rows


class RegisteredFactorialTests(unittest.TestCase):
    def test_complete_panel_is_explicitly_non_authorizing(self):
        cohort, rows = fixture()
        result = describe_registered_factorial(rows, cohort)
        self.assertEqual(result["registered_world_draws"], 4)
        self.assertEqual(result["training_seeds"], 2)
        self.assertEqual(result["original_source_strata"], 4)
        self.assertEqual(result["retained_failed_arm_rows"], 0)
        self.assertEqual(result["physical_cost_unit"], UNIT)
        self.assertEqual(len(result["registered_cohort_digest"]), 64)
        self.assertFalse(result["independent_outcome_attestation_verified"])
        self.assertFalse(result["scientific_causality_or_superiority_established"])

    def test_unbalanced_source_repetitions_cannot_fake_superiority(self):
        cohort, rows = fixture(repeated_easy_draws=100)
        result = describe_registered_factorial(rows, cohort)
        pooled = result["pooled_mean_external_loss_diagnostic"]
        balanced = result["balanced_mean_external_loss"]
        self.assertLess(pooled["base_ndu"] - pooled["base_static"], 0)
        self.assertGreater(balanced["base_ndu"] - balanced["base_static"], 0)
        self.assertAlmostEqual(result["balanced_inference_effect_on_base"], 0.45)
        self.assertEqual(result["registered_world_draws"], 202)

    def test_many_draws_from_one_world_cannot_flip_source_means(self):
        # One original source has two different worlds: 99 favorable draws
        # for one and one adverse draw for the other. Correct hierarchy is
        # seed -> source -> world -> draw; row or source-only averaging fails.
        inherited, rows = fixture(repeated_easy_draws=100)
        adjusted = []
        for r in rows:
            if r.original_source == "original-hard" and r.arm == "base_ndu":
                r = replace(r, external_loss=1.0)
            if r.original_source == "original-easy" and r.draw == 99:
                r = replace(r, world=r.world + "-second-world",
                            external_loss=2.0 if r.arm == "base_ndu"
                            else r.external_loss)
            adjusted.append(r)
        keys = tuple((r.seed, r.original_source, r.world, r.draw)
                     for r in adjusted if r.arm == "base_static")
        cohort = RegisteredFactorialCohort(
            keys, inherited.allowed_sources, R, UNIT, 3.0)
        result = describe_registered_factorial(adjusted, cohort)
        pooled = result["pooled_mean_external_loss_diagnostic"]
        self.assertLess(pooled["base_ndu"] - pooled["base_static"], 0)
        self.assertAlmostEqual(result["balanced_inference_effect_on_base"], 0.225)
        self.assertEqual(result["balancing_hierarchy"],
                         "training_seed/original_source/world/draw")

    def test_missing_world_and_extra_draw_are_both_rejected(self):
        cohort, rows = fixture()
        trimmed = [r for r in rows if not (r.seed == 17 and
                  r.original_source == "original-hard")]
        with self.assertRaisesRegex(ValueError, "cardinality"):
            describe_registered_factorial(trimmed, cohort)
        # Replacing an entire four-arm world with another, still paired,
        # cannot satisfy a pre-registered cohort even at equal row count.
        tampered = [replace(r, draw=999) if r.seed == 17
                    and r.original_source == "original-hard" else r
                    for r in rows]
        with self.assertRaisesRegex(ValueError, "unregistered"):
            describe_registered_factorial(tampered, cohort)

    def test_failed_rows_are_paid_and_cannot_be_relabelled_better_than_failure(self):
        cohort, rows = fixture()
        rows[0] = replace(rows[0], complete=False, external_loss=3.0)
        report = describe_registered_factorial(rows, cohort)
        self.assertEqual(report["retained_failed_arm_rows"], 1)
        self.assertGreater(report["balanced_mean_external_loss"]["base_static"], 1.0)
        for changed in (
            replace(rows[0], external_loss=1.0),
            replace(rows[0], external_loss=float("nan")),
            replace(rows[0], complete=True, external_loss=4.0),
        ):
            sample = rows.copy()
            sample[0] = changed
            with self.subTest(changed=str(changed)[:60]):
                with self.assertRaises(ValueError):
                    describe_registered_factorial(sample, cohort)

    def test_pairwise_randomness_and_decoder_binding_remain_enforced(self):
        cohort, rows = fixture()
        for kwargs in ({"randomness_digest": "e" * 64},
                       {"decoder_digest": "f" * 64},
                       {"scoring_digest": "b" * 64}):
            sample = rows.copy()
            sample[0] = replace(rows[0], **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                describe_registered_factorial(sample, cohort)

    def test_duplicate_or_fake_registration_fails_before_scoring(self):
        cohort, rows = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            RegisteredFactorialCohort(
                cohort.keys + (cohort.keys[0],), cohort.allowed_sources,
                R, UNIT, 3.0)
        with self.assertRaisesRegex(ValueError, "coverage"):
            RegisteredFactorialCohort(
                tuple(k for k in cohort.keys if k[0] == 17),
                cohort.allowed_sources, R, UNIT, 3.0)
        with self.assertRaisesRegex(ValueError, "contract"):
            RegisteredFactorialCohort(
                list(cohort.keys), cohort.allowed_sources, R, UNIT, 3.0)
        with self.assertRaisesRegex(ValueError, "contract"):
            RegisteredFactorialCohort(
                cohort.keys, cohort.allowed_sources, R, UNIT,
                float("inf"))

    def test_nonfinite_or_unmeasured_cost_rejected(self):
        cohort, rows = fixture()
        for value in (float("nan"), float("inf"), -1.0):
            sample = rows.copy()
            sample[0] = replace(rows[0], physical_cost=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                describe_registered_factorial(sample, cohort)
        sample = rows.copy()
        sample[0] = replace(rows[0], unit="estimated_MACs")
        with self.assertRaises(ValueError):
            describe_registered_factorial(sample, cohort)

    def test_repeated_cross_seed_sources_are_not_inflated_into_independence(self):
        cohort, rows = fixture()
        result = describe_registered_factorial(rows, cohort)
        # Four seed/source strata describe just TWO original media/source
        # identities; repeated model seeds do not acquire new raw evidence.
        self.assertEqual(result["original_source_strata"], 4)
        self.assertEqual(result["declared_unique_original_source_ids"], 2)
        self.assertEqual(result["declared_source_ids_reused_across_seeds"], 2)
        self.assertFalse(result["cross_seed_source_independence_verified"])
        self.assertFalse(result["independent_outcome_attestation_verified"])

    def test_distinct_declared_sources_do_not_imply_verified_independence(self):
        cohort, rows = fixture()
        amended = []
        for r in rows:
            if r.seed == 29:
                r = replace(r, original_source="separate-" + r.original_source)
            amended.append(r)
        keys = tuple((r.seed, r.original_source, r.world, r.draw)
                     for r in amended if r.arm == "base_static")
        updated = RegisteredFactorialCohort(
            keys,
            frozenset(r.original_source for r in amended),
            cohort.scoring_digest, cohort.physical_unit, cohort.failed_output_loss)
        report = describe_registered_factorial(amended, updated)
        self.assertEqual(report["original_source_strata"], 4)
        self.assertEqual(report["declared_unique_original_source_ids"], 4)
        self.assertEqual(report["declared_source_ids_reused_across_seeds"], 0)
        # The names and hashes are caller-supplied, not external custody.
        self.assertFalse(report["cross_seed_source_independence_verified"])

    def test_reordering_does_not_change_registered_descriptor(self):
        cohort, rows = fixture(repeated_easy_draws=3)
        a = describe_registered_factorial(rows, cohort)
        b = describe_registered_factorial(list(reversed(rows)), cohort)
        self.assertEqual(a, b)

if __name__ == "__main__":
    unittest.main()
