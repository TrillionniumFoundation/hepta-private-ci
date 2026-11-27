"""Paired uncertainty tests: joint source groups, seed means, known contrasts."""

import unittest
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from summarize_cell_study import (ARMS, BUDGETS, SEEDS, bootstrap_counts, canonical, collect_study,
    event_state, fixed_contrasts, inventory_digest, paired_interval, resampled_metrics, sha_file)


def model_state(labels, perfect=True):
    states = []
    for target in labels:
        prediction = target if perfect else 1 - target
        p = np.full((len(target), 2), .1)
        p[np.arange(len(target)), prediction] = .9
        state, _ = event_state(p, target, np.ones(len(target), dtype=bool))
        states.append(state)
    return np.stack(states, axis=1)


class StudySummaryTests(unittest.TestCase):
    def setUp(self):
        self.labels = np.array([[0, 1] * 16, [0, 0, 1, 1] * 8])
        self.groups = [f"source:{i}" for i in range(32)]
        self.counts = bootstrap_counts(self.groups)

    def test_paired_identical_models_have_exactly_zero_interval(self):
        scores = resampled_metrics(model_state(self.labels), self.labels, self.counts)
        for values in scores.values():
            result, difference = paired_interval(values, values.copy())
            self.assertEqual(result["ci95_percentile"], [0, 0])
            np.testing.assert_array_equal(difference, np.zeros(2000))

    def test_known_improvement_preserves_direction_and_nonzero_interval(self):
        good = resampled_metrics(model_state(self.labels), self.labels, self.counts)
        bad = resampled_metrics(model_state(self.labels, False), self.labels, self.counts)
        for name in ("balanced_accuracy", "positive_recall", "overall_success"):
            result, _ = paired_interval(good[name], bad[name])
            self.assertEqual(result["ci95_percentile"], [1, 1])
        nll, _ = paired_interval(good["nll"], bad["nll"])
        self.assertLess(nll["ci95_percentile"][1], -2)

    def test_joint_resampling_keeps_complementary_task_errors_correlated(self):
        labels = np.array([[0, 1] * 16, [1, 0] * 16])
        p = np.tile([.9, .1], (32, 1))
        state = np.stack([event_state(p, y, np.ones(32, dtype=bool))[0] for y in labels], axis=1)
        scores = resampled_metrics(state, labels, self.counts)
        np.testing.assert_array_equal(scores["overall_success"], np.full(2000, .5))

    def test_seed_loss_averaging_does_not_turn_into_prediction_ensemble(self):
        labels = self.labels[:1]
        state = (model_state(labels) + model_state(labels, False)) / 2
        scores = resampled_metrics(state, labels, np.ones((1, 32), dtype=np.uint16))
        self.assertAlmostEqual(scores["nll"][0], -(np.log(.9) + np.log(.1)) / 2)
        self.assertGreater(scores["nll"][0], np.log(2))
        self.assertEqual(scores["overall_success"][0], .5)

    def test_missing_class_draws_are_explicit_and_bad_inputs_reject(self):
        state = model_state(self.labels)
        counts = np.zeros((1, 32), dtype=np.uint16)
        counts[0, 0] = 32
        scores = resampled_metrics(state, self.labels, counts)
        interval, _ = paired_interval(scores["balanced_accuracy"], scores["balanced_accuracy"])
        self.assertIsNone(interval["ci95_percentile"])
        self.assertEqual(interval["undefined_missing_class_draws"], 1)
        for groups in (["duplicate", "duplicate"], ["valid", ""], ["only"]):
            with self.assertRaises(ValueError):
                bootstrap_counts(groups)
        with self.assertRaises(ValueError):
            resampled_metrics(state, self.labels.astype(bool), self.counts)
        with self.assertRaises(ValueError):
            event_state([[.8, .8]], [1], [True])

    def test_bootstrap_and_contrasts_are_predeclared_and_repeatable(self):
        np.testing.assert_array_equal(self.counts, bootstrap_counts(self.groups))
        np.testing.assert_array_equal(self.counts.sum(axis=1), np.full(2000, 32))
        contrast = fixed_contrasts()
        self.assertEqual(len(contrast), 11)
        self.assertEqual(len({item["id"] for item in contrast}), 11)
        self.assertEqual(contrast[-1]["left"], ("embeddinggemma2_740m", 128, "gated", "trained"))
        self.assertEqual(contrast[-1]["right"], ("granite97m", 128, "gated", "trained"))

    def test_reader_checks_all_runs_candidate_order_and_recomputed_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "study"
            curve = root / "curves" / "fixture_task"
            curve.mkdir(parents=True)
            (root / "completed").mkdir()
            feature = root.parent / "features" / "report.json"
            feature.parent.mkdir()
            feature.write_bytes(canonical({"plan": {"candidate": "granite97m"}, "feature_identity": "c" * 64}))
            data, data_sha = {"selected_tasks": ["fixture_task"]}, "d" * 64
            plan = {"dataset_sha256": data_sha, "selected_tasks": data["selected_tasks"],
                "budgets": list(BUDGETS), "seeds": list(SEEDS), "steps": 200, "threshold": .7,
                "task_family_count": 1, "feature_receipt_sha256": sha_file(feature), "feature_identity": "c" * 64}
            (root / "study-plan.json").write_bytes(canonical(plan))
            (root / "summary.json").write_bytes(canonical({"plan": plan, "task_count": 1}))
            labels, ids = np.array([[0, 1, 0, 1]]), ["s0", "s1", "s2", "s3"]
            p, eligibility = [[.9, .1], [.1, .9]] * 2, [True] * 4
            _, metrics = event_state(p, labels[0], eligibility)
            scored = {"probabilities": p, "eligible": eligibility, "semantic": metrics}
            arms = {arm: dict(scored) for arm in ARMS}
            for arm in ARMS[4:]:
                arms[arm]["controls"] = {name: dict(scored) for name in ("parameters_off", "shuffled_parameters")}
            report = {"status": "complete", "unavailable": [], "holdout_source_ids": ids,
                "runs": [{"seed": seed, "budget": budget, "arms": arms} for seed in SEEDS for budget in BUDGETS]}

            def seal():
                (curve / "report.json").write_bytes(canonical(report))
                (root / "completed/fixture_task.json").write_bytes(canonical({"task": "fixture_task",
                    "plan_sha256": hashlib.sha256(canonical(plan)).hexdigest(),
                    "inventory_sha256": inventory_digest(curve)}))

            seal()
            states, rows, _ = collect_study(root, data, data_sha, "granite97m", labels, ids)
            self.assertEqual(len(rows), 9 * 13)
            np.testing.assert_array_equal(states[(128, "gated", "trained")][0], np.ones((1, 4)))
            with self.assertRaisesRegex(ValueError, "candidate"):
                collect_study(root, data, data_sha, "embeddinggemma2_740m", labels, ids)
            report["holdout_source_ids"] = ids[::-1]
            seal()
            with self.assertRaisesRegex(ValueError, "holdout order"):
                collect_study(root, data, data_sha, "granite97m", labels, ids)
            report["holdout_source_ids"] = ids
            report = json.loads(canonical(report))
            report["runs"][0]["arms"]["linear"]["semantic"]["balanced_accuracy"] = .25
            seal()
            with self.assertRaisesRegex(ValueError, "stored semantic metric"):
                collect_study(root, data, data_sha, "granite97m", labels, ids)


if __name__ == "__main__":
    unittest.main()
