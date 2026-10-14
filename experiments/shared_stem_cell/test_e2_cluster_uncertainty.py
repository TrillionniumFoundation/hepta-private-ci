"""Small deterministic negative/positive tests; actual artifacts audited separately."""
import unittest

from experiments.shared_stem_cell.e2_cluster_uncertainty import (
    BUDGETS, SEEDS, CONTRASTS, case_correctness, source_paired_statistics,
)
from experiments.shared_stem_cell.preflight_review import PreflightError


def cohort(n=32):
    groups = {f"item-{i}": f"source-{i}" for i in range(n)}
    outcomes = {(budget, seed, item): 0 for budget in BUDGETS
                for seed in SEEDS for item in groups}
    return groups, outcomes


class PairUncertaintyTests(unittest.TestCase):
    def test_all_ten_contrasts_and_no_seed_pseudoreplication(self):
        groups, values = cohort()
        for item in groups:
            for seed in SEEDS:
                values[(65536, seed, item)] = 1
        result = source_paired_statistics(values, groups, replicates=1000)
        self.assertEqual(len(result), len(CONTRASTS))
        v = next(row for row in result if row["from_budget"] == 16384
                 and row["to_budget"] == 65536)
        self.assertEqual(v["observed_gain_per_original_source_group"], 1.0)
        self.assertEqual(v["source_group_labels_reported"], 32)
        self.assertEqual(v["seed_trajectories_per_original_case"], 3)
        self.assertEqual(v["bootstrap_95_interval"], [1., 1.])
        self.assertFalse(v["independent_source_group_sampling_verified"])

    def test_case_traces_resampled_together_and_deterministic(self):
        groups, values = cohort()
        # Three seeds disagree on the same original case. It must contribute
        # only ONE source-group value equal to their within-case mean.
        for i in range(8):
            values[(65536, 11, f"item-{i}")] = 1
        result = source_paired_statistics(values, groups, replicates=1000)
        chosen = next(row for row in result if row["from_budget"] == 16384
                      and row["to_budget"] == 65536)
        self.assertAlmostEqual(chosen["observed_gain_per_original_source_group"], 8 / (32*3))
        self.assertEqual(result, source_paired_statistics(values, groups, replicates=1000))

    def test_missing_case_or_seed_does_not_inflate_n(self):
        groups, values = cohort()
        del values[(2048, 11, 'item-0')]
        with self.assertRaisesRegex(PreflightError, "incomplete"):
            source_paired_statistics(values, groups, replicates=1000)

    def test_invalid_resample_budget_and_group_rejected(self):
        groups, values = cohort()
        with self.assertRaises(PreflightError):
            source_paired_statistics(values, groups, replicates=999)
        with self.assertRaises(PreflightError):
            source_paired_statistics(values, {key: '' for key in groups}, replicates=1000)

    def test_requires_exact_per_seed_budget_trained_holdout_census(self):
        groups, _ = cohort()
        labels = dict.fromkeys(groups, 0)
        # Missing 14 of the 15 registered budget×seed combinations must fail.
        rows = [{"split": "holdout", "role": "trained", "ceiling": 2048,
                 "seed": 11, "case_id": key, "probabilities": [1., 0., 0., 0.]}
                for key in groups]
        with self.assertRaisesRegex(PreflightError, 'incomplete'):
            case_correctness(rows, labels)

    def test_duplicate_and_invalid_probability_rejected(self):
        groups, _ = cohort()
        labels = dict.fromkeys(groups, 0)
        row = {"split": "holdout", "role": "trained", "ceiling": 2048,
               "seed": 11, "case_id": "item-0", "probabilities": [1., 0., 0., 0.]}
        with self.assertRaisesRegex(PreflightError, 'duplicate'):
            case_correctness([row, dict(row)], labels)
        row["probabilities"] = [.7, .1, .1, .0]
        with self.assertRaisesRegex(PreflightError, 'nonprobabilistic'):
            case_correctness([row], labels)


if __name__ == '__main__':
    unittest.main()
