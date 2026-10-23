import json
import tempfile
import unittest
from pathlib import Path

import bakeoff
import run_live


def h64(c):
    return c * 64


def h40(c):
    return c * 40


class BakeoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = []
        for n, split in enumerate(bakeoff.SPLITS):
            for j in range(8):
                self.data.append({"id": f"{split}-{j}", "source_group": f"s{n}-{j}",
                                  "split": split, "timestamp": (n + 1) * 100 + j,
                                  "language": "en" if j % 2 else "zh", "task_family": "routing", "ood": j == 7,
                                  "label": "yes" if j % 2 else "no", "options": ["yes", "no"]})
        self.dataset_file = self.folder / "gold.jsonl"
        self._write(self.dataset_file, self.data)
        self.models = []
        for i, name in enumerate(bakeoff.MODEL_NAMES):
            model = {"name": name, "kind": "encoder-head" if i >= 3 else "typed",
                     "repo": "owner/model", "revision": h40('a'), "weights_sha256": h64('b'),
                     "tokenizer_sha256": h64('c'), "runtime_sha256": h64('d'),
                     "head_sha256": h64('e'), "license_review": "approved",
                     "parameters": 421000000 if i < 2 else 270000000,
                     "head_steps": 100, "head_seed": 42, "head_optimizer": "adamw",
                     "train_data_sha256": h64('f')}
            self.models.append(model)
        self.plan = {"schema": bakeoff.SCHEMA, "baseline": "laya-english",
                     "source_head": h40('f'), "dataset_sha256": bakeoff.digest(self.dataset_file),
                     "threshold": 0.6, "registered_before_utc": "2026-10-22T00:00:00Z", "models": self.models}
        self.preds = []
        for name in bakeoff.MODEL_NAMES:
            for row in self.data:
                if row["split"] == "train":
                    continue
                p = 0.9 if row["label"] == "yes" else 0.1
                self.preds.append({"model": name, "id": row["id"], "revision": h40('a'),
                                   "weights_sha256": h64('b'), "probabilities": {"yes": p, "no": 1-p},
                                   "abstain": row["ood"], "latency_ms": 2.5,
                                   "origin": "live-model-observation"})
        self.pred_file = self.folder / "pred.jsonl"
        self._write(self.pred_file, self.preds)

    def _write(self, path, items):
        path.write_text("".join(json.dumps(x) + "\n" for x in items), encoding="utf-8")

    def test_blind_input_rejects_gold_leakage(self):
        path = self.folder / "blind.jsonl"
        self._write(path, [{"id": "s1", "split": "future_1", "state": "x",
                            "options": ["yes", "no"], "label": "yes"}])
        with self.assertRaisesRegex(bakeoff.EvidenceError, "gold or unknown"):
            run_live.blind_rows(path)

    def test_local_model_files_fail_on_tamper(self):
        root = self.folder / "weights"
        root.mkdir()
        weight = root / "weights.safetensors"
        weight.write_bytes(b"some offline fixture")
        inventory = {"weights.safetensors": bakeoff.digest(weight)}
        expected = __import__("hashlib").sha256(json.dumps(list(inventory.items()),
                         separators=(",", ":")).encode("ascii")).hexdigest()
        entry = {"files_sha256": inventory, "weights_sha256": expected}
        self.assertEqual(run_live.verified_local_model(root, entry), root)
        weight.write_bytes(b"tampered")
        with self.assertRaisesRegex(bakeoff.EvidenceError, "artifact mismatch"):
            run_live.verified_local_model(root, entry)

    def test_valid_offline_score_does_not_mint_qualification(self):
        report = bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)
        self.assertFalse(report["production_qualified"])
        self.assertIn("missing-external-cas-fence-rollback-restart-attestation", report["blockers"])
        self.assertEqual(set(report["scores"]), set(bakeoff.MODEL_NAMES))
        self.assertEqual(set(report["scores"]["laya-english"]), {"future_1", "future_2"})
        self.assertGreater(report["scores"]["laya-english"]["future_1"]["accuracy"], 0.9)

    def _plan_file(self):
        file = self.folder / "plan.json"
        file.write_text(json.dumps(self.plan), encoding="utf-8")
        return file

    def test_unpinned_model_denied(self):
        self.plan["models"][0]["weights_sha256"] = None
        with self.assertRaisesRegex(bakeoff.EvidenceError, "missing weights_sha256"):
            bakeoff.load_plan(self._plan_file())

    def test_unequal_head_budget_denied(self):
        self.plan["models"][-1]["head_steps"] = 99
        with self.assertRaisesRegex(bakeoff.EvidenceError, "equal training budget"):
            bakeoff.load_plan(self._plan_file())

    def test_dataset_digest_tamper_denied(self):
        self.data[0]["label"] = "yes"
        self._write(self.dataset_file, self.data)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "dataset digest mismatch"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_group_leakage_denied(self):
        self.data[-1]["source_group"] = self.data[0]["source_group"]
        with self.assertRaisesRegex(bakeoff.EvidenceError, "source leakage"):
            bakeoff.validate_data(self.data)

    def test_future_time_leakage_denied(self):
        self.data[-1]["timestamp"] = 30
        with self.assertRaisesRegex(bakeoff.EvidenceError, "future_2 not held out"):
            bakeoff.validate_data(self.data)

    def test_missing_prediction_denied(self):
        self.preds.pop()
        self._write(self.pred_file, self.preds)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "missing observations"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_wrong_model_generation_denied(self):
        self.preds[0]["revision"] = h40('1')
        self._write(self.pred_file, self.preds)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "model identity mismatch"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_bad_probability_denied(self):
        self.preds[0]["probabilities"]["yes"] = float("nan")
        self._write(self.pred_file, self.preds)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "invalid probability"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_temperature_only_calibration(self):
        data = bakeoff.validate_data(self.data)
        ps = bakeoff.validate_predictions(self.preds, data, self.plan)["laya-english"]
        ids = [x["id"] for x in self.data if x["split"] == "calibration"]
        t = bakeoff.temperature(ids, data, ps)
        for sample in self.data:
            if sample["split"] == "future_2":
                ps[sample["id"]]["probabilities"] = {"yes": 0.99, "no": 0.01}
        self.assertEqual(t, bakeoff.temperature(ids, data, ps))

    def test_resource_all_scales_rejects_missing(self):
        rows = [{"model": "laya-english", "logical_cells": 64, "active_cells": 1,
                 "cpu_rss_peak_bytes": 123, "gpu_peak_bytes": 0, "throughput_per_sec": 1,
                 "p95_latency_ms": 1, "p99_latency_ms": 2, "load_latency_ms": 3,
                 "host_id": "test", "driver_receipt": "test", "origin": "observed-target-host"}]
        _, blockers = bakeoff.check_resources(rows, self.models)
        self.assertIn("resource-missing-scales:laya-english", blockers)
        self.assertIn("resource-missing-scales:harrier-270m", blockers)

    def test_uncertainty_report_not_authorizing_even_with_event_strings(self):
        events = [{"model": model, "event": event} for model in bakeoff.MODEL_NAMES
                  for event in ("artifact-cas", "generation-fence", "signed-final-use",
                                "rollback", "restart-recovery", "old-generation-rejected")]
        lifecycle = self.folder / "events.jsonl"
        self._write(lifecycle, events)
        report = bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file,
                                  self.pred_file, lifecycle_path=lifecycle)
        self.assertFalse(report["production_qualified"])
        self.assertIn("external-signature-trust-root-and-live-receipt-verification-required", report["blockers"])


if __name__ == "__main__":
    unittest.main()
