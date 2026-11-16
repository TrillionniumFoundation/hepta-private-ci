"""Final-label sequencing and source-paired evaluation checks with small fixtures."""

import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_evaluate import evaluate, metrics, stratified_draws
from cell_learning_models import canonical


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvaluationFixture:
    """Sealed input catalog; placeholder artifacts are never model execution evidence."""

    def __init__(self, directory, seeds=(7,)):
        self.base = Path(directory)
        self.root, self.data = self.base / "runs", self.base / "data"
        self.root.mkdir(parents=True)
        self.data.mkdir()
        self.protocol = self.base / "protocol.json"
        self.destination = self.base / "evaluation"
        self.plan = {"seeds": list(seeds), "head_modes": ["linear"], "action_masks": ["all"],
                     "policies": ["zero", "myopic", "loss2", "extended", "full"],
                     "classes": 4, "bootstrap_seed": 103, "bootstrap_replicates": 80}
        write_json(self.protocol, self.plan)
        self.sources, self.roles = [], {}
        for role in ("old_test", "future_may", "future_june"):
            indices = list(range(len(self.sources), len(self.sources) + 12))
            source_ids = [f"source-{i}" for i in indices]
            self.sources.extend({"source_id": source_id, "component_id": f"component-{i}", "role": role}
                                for source_id, i in zip(source_ids, indices))
            self.roles[role] = {"indices": indices, "labels": list(range(4)) * 3, "source_ids": source_ids}
        write_json(self.data / "sources.json", {"rows": self.sources})
        write_json(self.data / "final_labels.json", {"roles": self.roles})
        self.records, self.initials = [], []
        predictions, initial = [], []
        for seed in seeds:
            initial_index = len(self.initials)
            initial_path = f"initial/seed{seed}-linear"
            self.initials.append({"seed": seed, "head": "linear", "status": "completed", "path": initial_path})
            for name in ("manifest.json", "state.npz"):
                self._artifact(f"{initial_path}/{name}")
            initial.append(np.full((len(self.sources), 4), 0.25))
            for mask, policy in itertools.product(self.plan["action_masks"], self.plan["policies"]):
                run_id = f"seed{seed}-linear-{mask}-{policy}"
                paths = {kind: f"{kind}/{run_id}.{suffix}" for kind, suffix in
                         (("controller", "npz"), ("reference", "npz"), ("trajectory", "npz"),
                          ("tangent", "npz"), ("receipts", "json"))}
                paths.update(checkpoint=f"checkpoints/{run_id}", head=f"heads/{run_id}")
                for key in ("controller", "reference", "trajectory", "tangent", "receipts"):
                    self._artifact(paths[key])
                for key, names in (("checkpoint", ("manifest.json", "state.npz")),
                                   ("head", ("manifest.json", "weights.npz"))):
                    for name in names:
                        self._artifact(f"{paths[key]}/{name}")
                self.records.append({"run_id": run_id, "seed": seed, "head": "linear", "mask": mask,
                                     "policy": policy, "initial_index": initial_index,
                                     "status": "completed", "paths": paths})
                probability = np.full((len(self.sources), 4), 0.25)
                # Differences vary by source, but each seed repeats exactly the same fits.
                if policy != "zero":
                    strength = {"myopic": 0.03, "loss2": 0.06, "extended": 0.07, "full": 0.08}[policy]
                    for i in range(len(probability)):
                        shift = strength * (1 + i % 3)
                        probability[i] -= shift / 3
                        probability[i, i % 4] = 0.25 + shift
                predictions.append(probability)
        self.probabilities, self.initial_probabilities = np.asarray(predictions), np.asarray(initial)
        self.refresh()

    def _artifact(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test catalog artifact; no scientific outcome claim\n")

    def refresh(self):
        receipt = {"files": {name: {"sha256": digest(self.data / name),
                                    "bytes": (self.data / name).stat().st_size}
                              for name in ("sources.json", "final_labels.json")}}
        write_json(self.data / "data_receipt.json", receipt)
        report = {"protocol_sha256": digest(self.protocol),
                  "data_receipt_sha256": digest(self.data / "data_receipt.json"),
                  "source_ids": [row["source_id"] for row in self.sources],
                  "row_roles": [row["role"] for row in self.sources],
                  "records": self.records, "initial_order": self.initials}
        write_json(self.root / "runs.json", report)
        np.savez(self.root / "predictions.npz", probabilities=self.probabilities,
                 initial_probabilities=self.initial_probabilities)
        inventory = {str(path.relative_to(self.root)): {"sha256": digest(path), "bytes": path.stat().st_size}
                     for path in self.root.rglob("*") if path.is_file() and path != self.root / "pre_evaluation_seal.json"}
        write_json(self.root / "pre_evaluation_seal.json", {"files": inventory,
                   "protocol_sha256": digest(self.protocol), "record_count": len(self.records),
                   "final_labels_opened": False})

    def run(self):
        return evaluate(self.root, self.data, self.protocol, self.destination)


class MetricTests(unittest.TestCase):
    def test_exact_accuracy_logloss_and_multiclass_brier(self):
        probability = np.array([[1, 0, 0, 0], [0, 0.5, 0.5, 0],
                                [0.25, 0.25, 0.25, 0.25], [0.2, 0.3, 0.1, 0.4]])
        summary, losses, correct = metrics(probability, np.arange(4))
        self.assertEqual(summary["accuracy"], 0.75)
        self.assertEqual(summary["balanced_accuracy"], 0.75)
        self.assertAlmostEqual(summary["nll"], (np.log(2) + np.log(4) + np.log(2.5)) / 4)
        self.assertAlmostEqual(summary["brier"], 0.4375)
        np.testing.assert_array_equal(correct, [1, 1, 0, 1])
        np.testing.assert_allclose(losses, [0, np.log(2), np.log(4), np.log(2.5)])

    def test_invalid_probabilities_labels_and_missing_classes_reject(self):
        for probability, labels in ((np.full((4, 4), 0.3), np.arange(4)),
                                     (np.full((4, 4), 0.25), np.arange(4, dtype=float)),
                                     (np.full((4, 4), 0.25), np.array([0, 0, 1, 2])),
                                     (np.empty((0, 4)), np.array([], dtype=int))):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                metrics(probability, labels)

    def test_bootstrap_resamples_sources_with_fixed_class_counts(self):
        labels = np.array([0, 0, 0, 1, 1, 2, 2, 2, 2, 3])
        draws = stratified_draws(labels, np.random.default_rng(51), 50)
        self.assertEqual(draws.shape, (50, 10))
        np.testing.assert_array_equal(draws, stratified_draws(labels, np.random.default_rng(51), 50))
        for row in draws:
            np.testing.assert_array_equal(np.bincount(labels[row], minlength=4), [3, 2, 4, 1])


class LabelSequencingTests(unittest.TestCase):
    def assert_closed_gate(self, fixture):
        opened = []
        original = Path.open

        def traced(path, *args, **kwargs):
            if path == fixture.data / "final_labels.json":
                opened.append(str(path))
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", traced), self.assertRaises(ValueError):
            fixture.run()
        self.assertEqual(opened, [], "invalid pre-evaluation inputs opened final labels")

    def test_inventory_and_census_fail_before_final_label_access(self):
        for defect in ("extra", "missing", "duplicate", "tamper", "nested-seal"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                fixture = EvaluationFixture(tmp)
                if defect == "extra":
                    (fixture.root / "unexpected").write_text("unsealed")
                elif defect == "nested-seal":
                    (fixture.root / "nested").mkdir()
                    (fixture.root / "nested/pre_evaluation_seal.json").write_text("unsealed")
                elif defect == "tamper":
                    (fixture.root / "runs.json").write_bytes((fixture.root / "runs.json").read_bytes() + b" ")
                else:
                    fixture.records = fixture.records[:-1] if defect == "missing" else fixture.records[:-1] + [fixture.records[0]]
                    fixture.refresh()
                self.assert_closed_gate(fixture)

    def test_initial_identity_probability_and_checkpoint_gates(self):
        for defect in ("initial-index", "invalid-probability", "row-order", "missing-checkpoint"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                fixture = EvaluationFixture(tmp, seeds=(7, 17))
                if defect == "initial-index":
                    fixture.records[0]["initial_index"] = 1
                elif defect == "invalid-probability":
                    fixture.probabilities[0, 0] = np.nan
                elif defect == "missing-checkpoint":
                    (fixture.root / fixture.records[0]["paths"]["checkpoint"] / "state.npz").unlink()
                else:
                    fixture.sources[0]["source_id"], fixture.sources[1]["source_id"] = fixture.sources[1]["source_id"], fixture.sources[0]["source_id"]
                    # Source receipt retains the original order; only prediction metadata changes.
                fixture.refresh()
                self.assert_closed_gate(fixture)

    def test_final_role_indices_require_exact_integer_census(self):
        for defect in ("duplicate", "negative", "float", "wrong-role", "float-label"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                fixture = EvaluationFixture(tmp)
                row = fixture.roles["future_may"]
                if defect == "duplicate":
                    row["indices"][1], row["source_ids"][1] = row["indices"][0], row["source_ids"][0]
                elif defect == "negative":
                    row = fixture.roles["future_june"]
                    row["indices"][-1] = -1
                elif defect == "float":
                    row["indices"][0] = float(row["indices"][0]) + 0.1
                elif defect == "float-label":
                    row["labels"][0] = 0.1
                else:
                    row["indices"][0], row["source_ids"][0] = 0, fixture.sources[0]["source_id"]
                write_json(fixture.data / "final_labels.json", {"roles": fixture.roles})
                fixture.refresh()
                with self.assertRaises(ValueError):
                    fixture.run()
                self.assertFalse((fixture.destination / "evaluation.json").exists())

    def test_failed_initial_is_retained_without_scoring_nan_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = EvaluationFixture(tmp, seeds=(7, 17))
            fixture.initials[1]["status"] = "failed"
            fixture.initials[1]["error"] = "synthetic warmup failure"
            fixture.initial_probabilities[1] = np.nan
            for number, record in enumerate(fixture.records):
                if record["seed"] == 17:
                    record["status"], record["error"] = "failed", "synthetic warmup failure"
                    fixture.probabilities[number] = np.nan
            fixture.refresh()
            result = fixture.run()
            self.assertEqual(sum(row["status"] == "failed" for row in result["records"]), 15)
            self.assertTrue(all(row["status"] == "incomplete_registered_conditions" for row in result["contrasts"]))

    def test_duplicate_fitted_seeds_do_not_increase_source_sample_size(self):
        summaries = []
        with tempfile.TemporaryDirectory() as tmp:
            for count in (1, 3):
                fixture = EvaluationFixture(Path(tmp) / str(count), seeds=(7, 17, 29)[:count])
                result = fixture.run()
                summaries.append([{key: row[key] for key in ("head", "mask", "role", "left", "right", "metric",
                                     "difference_left_minus_right", "pointwise_percentile_95", "source_components")}
                                  for row in result["contrasts"]])
        self.assertEqual(len(summaries[0]), 24)
        for left, right in zip(*summaries):
            self.assertEqual(left["source_components"], 12)
            self.assertEqual(left.keys(), right.keys())
            for key in ("difference_left_minus_right", "pointwise_percentile_95"):
                np.testing.assert_allclose(left[key], right[key], atol=1e-15, rtol=0)


if __name__ == "__main__":
    unittest.main()
