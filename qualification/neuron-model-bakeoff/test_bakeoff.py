#!/usr/bin/env python3
"""Synthetic contract tests; test inputs are never experimental evidence."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bakeoff import (
    CANDIDATES, MODEL_REPOS, SCHEMA, EvidenceError, analyse,
    file_hash, validate_dataset, validate_predictions, metrics,
)
from run_models import calibrate, choose_temperature, normalize


def emit_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))


def example(i: str, split: str, day: int, *, ood: bool = False,
            lang: str = "en", task: str = "route") -> dict:
    return {
        "id": i, "cluster": "c" + i, "split": split,
        "event_time": f"2026-10-{day:02d}T12:00:00Z",
        "language": lang, "slice": task, "ood": ood,
        "options": ["allow", "deny"], "gold": "allow",
        "state": "fixture", "question": "allow or deny?",
    }


class BakeoffContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.dataset_path = self.root / "dataset.jsonl"
        self.rows = [
            example("train", "train", 1),
            example("val", "validation", 2),
            example("cal", "calibration", 3),
            example("test-en", "future_test", 4),
            example("test-zh", "future_test", 4, lang="zh", task="sentinel"),
            example("test-ood", "future_test", 4, ood=True),
        ]
        emit_jsonl(self.dataset_path, self.rows)
        self.plan = {
            "schema": SCHEMA, "kind": "frozen_experiment_plan",
            "source_commit": "a" * 40,
            "registered_before_utc": "2026-09-30T00:00:00Z",
            "abstention_threshold": 0.7,
            "candidates": list(CANDIDATES),
            "baseline": CANDIDATES[0],
            "dataset_sha256": file_hash(self.dataset_path),
            "independent_roles": {
                "dataset_owner": "data-owner", "evaluator": "eval",
                "selector": "select", "executor": "exec",
            },
            "minimum_slice_size": 1,
            "thresholds": {
                "max_ece": 1.0, "max_brier": 1.0,
                "max_ood_false_acceptance": 0.0,
                "max_slice_regression": 0.0, "min_accuracy_gain": 0.0,
            },
        }
        self.runs = self.root / "runs"
        for model in CANDIDATES:
            path = self.runs / model / "predictions.jsonl"
            predictions = [
                {"id": "test-en", "model": model,
                 "probabilities": {"allow": 0.9, "deny": 0.1}, "abstained": False},
                {"id": "test-zh", "model": model,
                 "probabilities": {"allow": 0.8, "deny": 0.2}, "abstained": False},
                {"id": "test-ood", "model": model,
                 "probabilities": {"allow": 0.5, "deny": 0.5}, "abstained": True},
            ]
            emit_jsonl(path, predictions)
            (path.parent / "run.json").write_text(json.dumps({
                "schema": SCHEMA, "model": model, "repository": MODEL_REPOS[model],
                "revision": "f" * 40, "source_commit": "a" * 40,
                "dataset_sha256": file_hash(self.dataset_path),
                "predictions_sha256": file_hash(path),
                "execution": "real_weights", "role": "model_runner",
                "calibration": {"temperature": 1.0, "abstention_threshold": 0.7},
                "digests": {
                    key: "b" * 64 for key in (
                        "weights", "tokenizer", "preprocessor",
                        "head", "quantization", "runtime", "device",
                    )
                },
                "profile": {
                    "head_trainable_parameters": 256, "head_epochs": 6,
                    "head_training_steps": 1, "head_learning_rate": 0.025,
                    "head_l2": 0.005, "head_seed": 1729,
                    "projection": "seeded_gaussian_256",
                    "projection_sha256": "c" * 64,
                },
            }))

    def test_input_metrics_do_not_authorize(self):
        result = analyse(self.plan, self.dataset_path, self.runs)
        self.assertFalse(result["all_blockers_closed"])
        self.assertFalse(result["independent_acceptance"])
        self.assertEqual(result["results"][CANDIDATES[0]]["all"]["accuracy"], 1.0)

    def test_missing_candidate_fails_closed(self):
        (self.runs / CANDIDATES[-1] / "run.json").unlink()
        with self.assertRaisesRegex(EvidenceError, "missing measured run"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_unpinned_head_fails(self):
        path = self.runs / CANDIDATES[1] / "run.json"
        manifest = json.loads(path.read_text())
        manifest["digests"]["head"] = "UNPINNED"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(EvidenceError, "head digest"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_dataset_drift_fails(self):
        self.rows[0]["gold"] = "deny"
        emit_jsonl(self.dataset_path, self.rows)
        with self.assertRaisesRegex(EvidenceError, "dataset hash mismatch"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_cross_split_cluster_fails(self):
        self.rows[1]["cluster"] = self.rows[0]["cluster"]
        with self.assertRaisesRegex(EvidenceError, "cluster crosses split"):
            validate_dataset(self.rows)

    def test_leaking_future_window_fails(self):
        self.rows[3]["event_time"] = self.rows[2]["event_time"]
        with self.assertRaisesRegex(EvidenceError, "time leakage"):
            validate_dataset(self.rows)

    def test_nonholdout_prediction_fails(self):
        dataset = validate_dataset(self.rows)
        row = json.loads(
            (self.runs / CANDIDATES[0] / "predictions.jsonl").read_text().splitlines()[0],
        )
        row["id"] = "train"
        with self.assertRaisesRegex(EvidenceError, "nonholdout"):
            validate_predictions([row], dataset, CANDIDATES[0], 0.7)

    def test_nan_probability_fails(self):
        dataset = validate_dataset(self.rows)
        rows = [
            json.loads(x) for x in (
                self.runs / CANDIDATES[0] / "predictions.jsonl"
            ).read_text().splitlines()
        ]
        rows[0]["probabilities"]["allow"] = float("nan")
        with self.assertRaisesRegex(EvidenceError, "invalid probability"):
            validate_predictions(rows, dataset, CANDIDATES[0], 0.7)

    def test_version_drift_fails(self):
        path = self.runs / CANDIDATES[0] / "run.json"
        record = json.loads(path.read_text())
        record["revision"] = "main"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(EvidenceError, "revision"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_negative_transfer_is_visible(self):
        model = CANDIDATES[2]
        path = self.runs / model / "predictions.jsonl"
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows[1]["probabilities"] = {"allow": 0.1, "deny": 0.9}
        emit_jsonl(path, rows)
        manifest_path = path.parent / "run.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["predictions_sha256"] = file_hash(path)
        manifest_path.write_text(json.dumps(manifest))
        result = analyse(self.plan, self.dataset_path, self.runs)
        self.assertFalse(result["results"][model]["metric_gate"])
        self.assertEqual(result["results"][model]["maximum_slice_regression"], 1.0)
        self.assertLess(result["results"][model]["paired_cluster_accuracy_gain_95ci"]["lower"], 0)

    def test_forged_abstention_is_rejected(self):
        dataset = validate_dataset(self.rows)
        path = self.runs / CANDIDATES[0] / "predictions.jsonl"
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows[0]["abstained"] = True  # confidence remains 0.9 > frozen 0.7
        with self.assertRaisesRegex(EvidenceError, "abstention flag inconsistent"):
            validate_predictions(rows, dataset, CANDIDATES[0], 0.7)

    def test_unregistered_threshold_is_rejected(self):
        path = self.runs / CANDIDATES[0] / "run.json"
        data = json.loads(path.read_text())
        data["calibration"]["abstention_threshold"] = 0.9
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(EvidenceError, "unregistered abstention threshold"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_mixed_source_commits_are_rejected(self):
        path = self.runs / CANDIDATES[2] / "run.json"
        data = json.loads(path.read_text())
        data["source_commit"] = "b" * 40
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(EvidenceError, "mixed or unregistered source"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_unfrozen_template_fails(self):
        self.plan["kind"] = "UNFROZEN_TEMPLATE_NOT_EVIDENCE"
        with self.assertRaisesRegex(EvidenceError, "unfrozen"):
            analyse(self.plan, self.dataset_path, self.runs)

    def test_raw_accuracy_does_not_conflate_abstention(self):
        dataset = validate_dataset(self.rows)
        path = self.runs / CANDIDATES[0] / "predictions.jsonl"
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows[0]["probabilities"] = {"allow": 0.6, "deny": 0.4}
        rows[0]["abstained"] = True
        predicted = validate_predictions(rows, dataset, CANDIDATES[0], 0.7)
        result = metrics(dataset, predicted)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["effective_correct_rate"], 0.5)
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["selective_accuracy"], 1.0)

    def test_class_imbalance_is_visible_not_hidden_by_accuracy(self):
        dataset = {}
        predicted = {}
        for n in range(11):
            rid = f"case-{n}"
            gold = "deny" if n == 10 else "allow"
            dataset[rid] = {
                "gold": gold, "options": ["allow", "deny"],
                "cluster": rid, "ood": False,
            }
            predicted[rid] = {
                "probabilities": {"allow": 0.9, "deny": 0.1},
                "abstained": False,
            }
        dataset["ood"] = {"ood": True, "gold": "deny",
                          "options": ["allow", "deny"], "cluster": "ood"}
        predicted["ood"] = {"probabilities": {"allow": 0.5, "deny": 0.5},
                            "abstained": True}
        score = metrics(dataset, predicted)
        self.assertGreater(score["accuracy"], 0.9)
        self.assertAlmostEqual(score["balanced_accuracy"], 0.5)
        self.assertLess(score["macro_f1"], score["accuracy"])
        self.assertEqual(score["per_class_recall"]["deny"], 0.0)

    def test_paired_bootstrap_is_diagnostic_only(self):
        result = analyse(self.plan, self.dataset_path, self.runs)
        for model in CANDIDATES:
            ci = result["results"][model]["paired_cluster_accuracy_gain_95ci"]
            self.assertEqual(ci["independent_clusters"], 2)
            self.assertEqual(ci["posture"],
                             "diagnostic_only_not_a_preregistered_statistical_acceptance")
            self.assertEqual(ci["lower"], 0.0)
            self.assertEqual(ci["upper"], 0.0)

    def test_calibration_grid_and_normalization(self):
        examples = [
            ({"yes": 0.8, "no": 0.2}, "yes"),
            ({"yes": 0.9, "no": 0.1}, "no"),
        ]
        temperature = choose_temperature(examples)
        self.assertGreater(temperature, 0)
        self.assertAlmostEqual(sum(calibrate(examples[0][0], temperature).values()), 1.0)
        self.assertEqual(normalize({"a": 1, "b": 1}), {"a": 0.5, "b": 0.5})


if __name__ == "__main__":
    unittest.main()
