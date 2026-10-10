import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scale import generate, trace_report
from study import (admission, classifier_metrics, paired_group_deltas,
                   validate_dataset, validate_outcomes, validate_predictions)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def inputs():
    split = ["held_out", "held_out", "future_1", "future_2", "ood"]
    return [dict(sample_id=f"s{i}", source_group=f"g{i}", episode_id=f"e{i}",
                 split=s, language=("en", "zh", "cross", "en", "zh")[i], label=i % 2)
            for i, s in enumerate(split)]


def model_outputs(dataset):
    rows = []
    for arm in ("no_change", "mmbert_small"):
        for i, row in enumerate(dataset):
            probs = [0.7, 0.3] if row["label"] == 0 else [0.3, 0.7]
            rows.append({"arm": arm, "sample_id": row["sample_id"], "label": row["label"],
                         "probabilities": probs, "ood_threshold": 0.9,
                         "model_digest": DIGEST_A, "dataset_digest": DIGEST_B,
                         "runtime_digest": DIGEST_C, "latency_path": "cold_encoder" if i % 2 else "cache_hit_head",
                         "latency_ms": 2.5})
    return rows


def owner_outcomes(dataset):
    return [dict(arm=arm, sample_id=r["sample_id"], observer_digest=DIGEST_B,
                 snapshot_digest=[DIGEST_A, DIGEST_B, DIGEST_C][i % 3],
                 external_ndu_utility=(1.0 if arm == "no_change" else 1.2),
                 total_cost=1.0) for arm in ("no_change", "mmbert_small")
            for i, r in enumerate(dataset)]


class StemStudyTests(unittest.TestCase):
    def setUp(self):
        self.dataset = inputs()
        self.ds = validate_dataset(self.dataset)
        self.pred = validate_predictions(model_outputs(self.dataset), self.ds)
        self.joined = validate_outcomes(owner_outcomes(self.dataset), self.pred)

    def test_partition_leakage_group(self):
        ds = inputs()
        ds[1]["source_group"] = ds[2]["source_group"]
        with self.assertRaisesRegex(ValueError, "source-group leakage"):
            validate_dataset(ds)

    def test_partition_leakage_episode(self):
        ds = inputs()
        ds[1]["episode_id"] = ds[2]["episode_id"]
        with self.assertRaisesRegex(ValueError, "episode leakage"):
            validate_dataset(ds)

    def test_duplicate_sample(self):
        with self.assertRaisesRegex(ValueError, "duplicate sample"):
            validate_dataset(inputs() + [inputs()[0]])

    def test_prediction_mutates_observer(self):
        outputs = model_outputs(self.dataset)
        outputs[0]["external_ndu_utility"] = 10
        with self.assertRaisesRegex(ValueError, "model-generated"):
            validate_predictions(outputs, self.ds)

    def test_probability_normalization(self):
        outputs = model_outputs(self.dataset)
        outputs[0]["probabilities"] = [0.9, 0.9]
        with self.assertRaisesRegex(ValueError, "probability"):
            validate_predictions(outputs, self.ds)

    def test_prediction_coverage(self):
        outputs = model_outputs(self.dataset)
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            validate_predictions(outputs[:-1], self.ds)

    def test_dataset_mislabeled(self):
        outputs = model_outputs(self.dataset)
        outputs[0]["label"] = 1
        with self.assertRaisesRegex(ValueError, "mismatching label"):
            validate_predictions(outputs, self.ds)

    def test_missing_independent_outcome(self):
        with self.assertRaisesRegex(ValueError, "missing independent"):
            validate_outcomes(owner_outcomes(self.dataset)[:-1], self.pred)

    def test_fake_self_observer(self):
        outcomes = owner_outcomes(self.dataset)
        outcomes[0]["observer_digest"] = DIGEST_A
        with self.assertRaisesRegex(ValueError, "own outcome observer"):
            validate_outcomes(outcomes, self.pred)

    def test_brier_accuracy_calibration(self):
        rows = [dict(self.ds[sid], **pred) for sid, pred in self.joined["no_change"].items()]
        metrics = classifier_metrics(rows)
        self.assertEqual(metrics["accuracy"], 1)
        self.assertAlmostEqual(metrics["multiclass_brier"], 0.18)
        self.assertAlmostEqual(metrics["ece_15"], 0.3)
        self.assertEqual(metrics["ood_false_acceptance"], 0.0)

    def test_paired_group_bootstrap_not_cell_calls(self):
        paired = paired_group_deltas(self.ds, self.joined, "no_change", "mmbert_small")
        self.assertEqual(len(paired), 4)  # OOD is not reward evidence
        self.assertTrue(all(abs(v - 0.2) < 1e-8 for v in paired))

    def test_admission_requires_support_and_native(self):
        cfg = {"frozen_admission": {"no_change_arm": "no_change", "confidence_level": 0.95,
               "bootstrap_replicates": 50, "independent_episode_groups_minimum": 400,
               "minimum_ndu_gain_lcb": 0.0, "future_windows_minimum": 2,
               "independent_snapshots_minimum": 3, "max_ood_false_acceptance": 0.005,
               "max_old_task_degradation": 0.02, "maximum_cost_ratio": 1.0}}
        result = admission(cfg, self.ds, self.joined)["mmbert_small"]
        self.assertFalse(result["shadow_eligible"])
        self.assertFalse(result["production_authorized"])
        self.assertIn("independent_episode_support", result["rejections"])
        self.assertIn("native_worker_evidence_missing", result["rejections"])


class ScaleTraceTests(unittest.TestCase):
    def setUp(self):
        self.jobs = generate(64, 0.1, 0.5, "mixed_family", DIGEST_A)
        self.events = []
        for i, j in enumerate(self.jobs):
            cold = i < 3
            self.events.append(dict(kind="request", request_id=j["request_id"],
                                    generation=j["generation"], model_digest=j["model_digest"],
                                    scope=j["scope"], start_us=j["submitted_at_us"] + 100,
                                    end_us=j["submitted_at_us"] + 250 + i,
                                    status="ok", path="cold_encoder" if cold else "cache_hit_head",
                                    batch_id="batch1" if cold else None,
                                    cpu_us=50, rss_bytes=1000000))
        # No batch_id means the key should be absent for cached requests.
        for row in self.events:
            if row["batch_id"] is None:
                del row["batch_id"]
        self.events.append(dict(kind="backend_batch", batch_id="batch1", backend="native_hepta",
                                batch_size=3, model_digest=DIGEST_A))
        self.events.append(dict(kind="wal_fsync", latency_us=800))
        self.events.append(dict(kind="restart", recovery_ms=12, checksum_verified=True))

    def test_matrix_size_and_determinism(self):
        self.assertEqual(self.jobs, generate(64, 0.1, 0.5, "mixed_family", DIGEST_A))
        self.assertEqual(len(self.jobs), 7)
        self.assertEqual(len({r["request_id"] for r in self.jobs}), 7)

    def test_real_trace_is_still_unverified(self):
        result = trace_report(self.jobs, self.events)
        self.assertEqual(result["backend_batches"], 1)
        self.assertEqual(result["actual_backend_multi_request_batches"], 1)
        self.assertEqual(result["completed"], 7)
        self.assertAlmostEqual(result["wal_fsync_p99_ms"], 0.8)
        self.assertTrue(result["all_recoveries_checksums_verified"])
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["native_worker_attested"])

    def test_batch_claim_requires_matching_members(self):
        self.events[-3]["batch_size"] = 4
        with self.assertRaisesRegex(ValueError, "batch size"):
            trace_report(self.jobs, self.events)

    def test_wrong_scope_rejected(self):
        self.events[0]["scope"] = "other tenant"
        with self.assertRaisesRegex(ValueError, "cross-scope"):
            trace_report(self.jobs, self.events)

    def test_missing_request_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            trace_report(self.jobs, self.events[1:])


if __name__ == "__main__":
    unittest.main()
