import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from scale import generate, trace_report
from study import (admission, classifier_metrics, load_jsonl, paired_group_deltas, wilson_upper,
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

    def test_ood_rate_must_have_confidence_support(self):
        self.assertGreater(wilson_upper(0, 100), 0.005)
        self.assertLess(wilson_upper(0, 1000), 0.005)

    def test_paired_group_bootstrap_not_cell_calls(self):
        paired = paired_group_deltas(self.ds, self.joined, "no_change", "mmbert_small")
        self.assertEqual(len(paired), 4)  # OOD is not reward evidence
        self.assertTrue(all(abs(v - 0.2) < 1e-8 for v in paired))

    def test_cli_produces_digest_bound_non_authorizing_report(self):
        from unittest.mock import patch
        import sys
        from study import main as study_main

        with tempfile.TemporaryDirectory() as root:
            dataset_path = Path(root, "dataset.jsonl")
            prediction_path = Path(root, "prediction.jsonl")
            outcome_path = Path(root, "outcome.jsonl")
            report_path = Path(root, "report.json")
            dataset_path.write_text("".join(json.dumps(row) + "\n" for row in self.dataset))
            digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            predictions = model_outputs(self.dataset)
            for row in predictions:
                row["dataset_digest"] = digest
            prediction_path.write_text("".join(json.dumps(row) + "\n" for row in predictions))
            outcome_path.write_text("".join(json.dumps(row) + "\n" for row in owner_outcomes(self.dataset)))
            args = ["study.py", "--dataset", str(dataset_path), "--predictions", str(prediction_path),
                    "--outcomes", str(outcome_path), "--output", str(report_path)]
            with patch.object(sys, "argv", args):
                study_main()
            report = json.loads(report_path.read_text())
            self.assertEqual(report["dataset_sha256"], digest)
            self.assertEqual(report["model_metrics"]["no_change"]["overall"]["count"], 5)
            self.assertFalse(report["admission_diagnostic"]["mmbert_small"]["shadow_eligible"])
            self.assertFalse(report["production_authorized"])
            self.assertEqual(len(report["protocol_sha256"]), 64)

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
                                    scope=j["scope"], enqueued_us=9000 + j["submitted_at_us"],
                                    start_us=9100 + j["submitted_at_us"],
                                    end_us=9250 + j["submitted_at_us"] + i,
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
        self.assertGreater(result["cold_and_cached_latency"]["cold_encoder"]["p99_ms"],
                           result["cold_and_cached_latency"]["cold_encoder"]["execution_p99_ms"])
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

    def test_bad_native_clock_domain_rejected(self):
        self.events[0]["enqueued_us"] = self.events[0]["end_us"] + 1
        with self.assertRaisesRegex(ValueError, "non-monotone native"):
            trace_report(self.jobs, self.events)

    def test_missing_request_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            trace_report(self.jobs, self.events[1:])




class OfflineHeadExecutionTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("torch") is not None, "optional torch unavailable")
    def test_frozen_local_encoder_head_train_without_real_model(self):
        """Synthetic backend smoke test: NOT evidence about any candidate weights."""
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import patch
        import torch
        import model_runner

        class Tokenizer:
            def __call__(self, text, return_tensors, truncation, max_length=None):
                vals = [1] + [2 + (ord(c) % 90) for c in text]
                if truncation:
                    vals = vals[:max_length]
                ids = torch.tensor([vals], dtype=torch.long)
                return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embed = torch.nn.Embedding(128, 16)

            def forward(self, input_ids, attention_mask):
                return SimpleNamespace(last_hidden_state=self.embed(input_ids))

        hf = ModuleType("transformers")
        hf.AutoTokenizer = SimpleNamespace(from_pretrained=lambda *args, **kw: Tokenizer())
        hf.AutoModel = SimpleNamespace(from_pretrained=lambda *args, **kw: Model())
        with tempfile.TemporaryDirectory() as root:
            snap = Path(root, "model")
            snap.mkdir()
            (snap / "config.json").write_text('{"model_type":"mock"}')
            dataset_path = Path(root, "dataset.jsonl")
            output_path = Path(root, "pred.jsonl")
            rows = []
            for split, count in (("train", 8), ("calibration", 4), ("held_out", 4),
                                 ("future_1", 2), ("future_2", 2), ("ood", 2)):
                for i in range(count):
                    rows.append(dict(sample_id=f"{split}-{i}", source_group=f"g-{split}-{i}",
                                     episode_id=f"e-{split}-{i}", split=split,
                                     language="zh" if i % 2 else "en", label=i % 2,
                                     state="shared state", question=f"question {i}",
                                     options=["yes", "no"], scope="same-approved-scope"))
            dataset_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
            args = ["model_runner.py", "--dataset", str(dataset_path), "--snapshot", str(snap),
                    "--expected-snapshot-digest", model_runner.snapshot_digest(snap),
                    "--model-key", "mmbert_small", "--representation", "cross_attention",
                    "--head", "linear", "--budget", "2048", "--shots-per-class", "2",
                    "--train-steps", "3", "--export-q24", "--output", str(output_path)]
            with patch.dict(sys.modules, {"transformers": hf}), patch.object(sys, "argv", args):
                model_runner.main()
            predictions = list(load_jsonl(output_path))
            manifest = json.loads(Path(str(output_path) + ".run.json").read_text())
            self.assertEqual(manifest["predictions_sha256"], hashlib.sha256(output_path.read_bytes()).hexdigest())
            self.assertFalse(manifest["production_authorized"])
            self.assertEqual(manifest["head_parameters"], 66)
            self.assertEqual(len(predictions), 10)
            self.assertTrue(all("external_ndu_utility" not in r for r in predictions))
            self.assertTrue(all(r["head_parameters"] <= 2048 for r in predictions))
            self.assertTrue(all(abs(sum(r["probabilities"]) - 1) < 1e-6 for r in predictions))
            self.assertTrue(all(r["backend_kind"] == "offline_hf_shadow" for r in predictions))
            q24_path = Path(str(output_path) + ".q24.json")
            artifact = json.loads(q24_path.read_text())
            self.assertFalse(artifact["production_authorized"])
            self.assertEqual(artifact["source_head_kind"], "linear")
            self.assertEqual(artifact["calibration_source"], "calibration_fold_only")
            self.assertEqual(hashlib.sha256(q24_path.read_bytes()).hexdigest(),
                             manifest["native_q24_shadow_artifact_sha256"])
            self.assertEqual(artifact["native_stored_coefficients"],
                             manifest["native_q24_stored_coefficients"])
            with patch.dict(sys.modules, {"transformers": hf}), patch.object(sys, "argv", args):
                with self.assertRaises(FileExistsError):
                    model_runner.main()

if __name__ == "__main__":
    unittest.main()
