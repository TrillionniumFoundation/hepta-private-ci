"""Retention evaluator sequencing, fixed-family decisions and source weighting."""

import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_retention_evaluate import (PAIRS, ROLES, compare_scores, equal_month_bootstrap,
                                           evaluate, paired_delta)
from cell_learning_models import canonical


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan():
    return {"seeds": [7, 17, 29], "head_modes": ["linear", "gated"], "action_masks": ["bias", "all"],
            "policies": ["zero", "myopic", "loss2", "extended", "full", "symmetric_loss2"],
            "classes": 4, "bootstrap_seed": 820241, "bootstrap_replicates": 10000,
            "secondary_pairs": [list(pair) for pair in PAIRS],
            "primary_family": {"alpha": 0.05, "comparisons": 8, "mask": "all",
                               "future_roles": ["future_may", "future_june"],
                               "future_pooling": "equal month means", "retention_margin": 0.0}}


class Fixture:
    """Catalog fixtures, not real scientific model or execution evidence."""

    def __init__(self, directory):
        self.base = Path(directory)
        self.root, self.data = self.base / "runs", self.base / "data"
        self.root.mkdir(); self.data.mkdir()
        self.protocol, self.output = self.base / "protocol.json", self.base / "evaluation"
        self.plan = plan()
        self.sources, self.roles = [], {}
        for role, count in zip(ROLES, (12, 12, 20)):
            indices = list(range(len(self.sources), len(self.sources) + count))
            ids = [f"source-{i}" for i in indices]
            self.sources.extend({"source_id": source, "component_id": f"component-{i}", "role": role}
                                for i, source in zip(indices, ids))
            self.roles[role] = {"indices": indices, "source_ids": ids, "labels": list(range(4)) * (count // 4)}
        write(self.data / "sources.json", {"rows": self.sources})
        write(self.data / "final_labels.json", {"roles": self.roles})
        self.records, self.initials, probabilities, initial_probabilities = [], [], [], []
        for seed, head in itertools.product(self.plan["seeds"], self.plan["head_modes"]):
            initial_index, directory = len(self.initials), f"initial/seed{seed}-{head}"
            self.initials.append({"seed": seed, "head": head, "status": "completed", "path": directory})
            for name in ("manifest.json", "state.npz"):
                self.artifact(f"{directory}/{name}")
            initial_probabilities.append(np.full((len(self.sources), 4), 0.25))
            for mask, policy in itertools.product(self.plan["action_masks"], self.plan["policies"]):
                run_id = f"seed{seed}-{head}-{mask}-{policy}"
                paths = {kind: f"{kind}/{run_id}.fixture" for kind in
                         ("reference", "controller", "trajectory", "tangent", "receipts")}
                for path in paths.values(): self.artifact(path)
                paths.update(checkpoint=f"checkpoints/{run_id}", head=f"heads/{run_id}")
                for key, names in (("checkpoint", ("manifest.json", "state.npz")),
                                   ("head", ("manifest.json", "weights.npz"))):
                    for name in names: self.artifact(f"{paths[key]}/{name}")
                self.records.append({"run_id": run_id, "seed": seed, "head": head, "mask": mask,
                                     "policy": policy, "initial_index": initial_index,
                                     "status": "completed", "paths": paths})
                strength = {"zero": 0.0, "myopic": 0.02, "loss2": 0.04, "extended": 0.03,
                            "full": 0.05, "symmetric_loss2": 0.015}[policy]
                shifts = strength * (1 + np.arange(len(self.sources)) % 3)
                probability = np.full((len(self.sources), 4), 0.25) - shifts[:, None] / 3
                probability[np.arange(len(self.sources)), np.arange(len(self.sources)) % 4] = 0.25 + shifts
                probabilities.append(probability)
        self.probabilities, self.initial_probabilities = np.array(probabilities), np.array(initial_probabilities)
        self.refresh()

    def artifact(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic evaluation catalog only\n")

    def refresh(self):
        write(self.protocol, self.plan)
        write(self.data / "data_receipt.json", {"files": {name: {"sha256": digest(self.data / name),
              "bytes": (self.data / name).stat().st_size} for name in ("sources.json", "final_labels.json")}})
        write(self.root / "runs.json", {"protocol_sha256": digest(self.protocol),
              "data_receipt_sha256": digest(self.data / "data_receipt.json"),
              "source_ids": [row["source_id"] for row in self.sources],
              "records": self.records, "initial_order": self.initials})
        np.savez(self.root / "predictions.npz", probabilities=self.probabilities,
                 initial_probabilities=self.initial_probabilities)
        inventory = {str(p.relative_to(self.root)): {"sha256": digest(p), "bytes": p.stat().st_size}
                     for p in self.root.rglob("*") if p.is_file() and p.name != "pre_evaluation_seal.json"}
        write(self.root / "pre_evaluation_seal.json", {"files": inventory,
              "protocol_sha256": digest(self.protocol), "record_count": len(self.records), "final_labels_opened": False})

    def run(self):
        return evaluate(self.root, self.data, self.protocol, self.output)


class RetentionEvaluationTests(unittest.TestCase):
    def test_pooling_weights_months_equally_and_pairs_fixed_models(self):
        first, second = np.array([0.0, 1.0]), np.full(6, 10.0)
        indices = [np.tile(np.arange(len(x)), (10, 1)) for x in (first, second)]
        point, samples = equal_month_bootstrap([first, second], indices)
        self.assertEqual(point, 5.25)
        np.testing.assert_array_equal(samples, np.full(10, 5.25))
        scores = {(seed, "linear", "all", method, "old_test"): {"nll": first + shift}
                  for seed in (7, 17, 29) for method, shift in (("loss2", 1), ("zero", 0))}
        one = paired_delta(scores, [7], "linear", "all", "loss2", "zero", "old_test", "nll")
        three = paired_delta(scores, [7, 17, 29], "linear", "all", "loss2", "zero", "old_test", "nll")
        np.testing.assert_array_equal(one, three)
        self.assertEqual(len(three), 2)

    def test_zero_future_effect_fails_strict_superiority_but_meets_zero_margin_retention(self):
        scores = {(seed, head, mask, policy, role): {"nll": np.zeros(4), "accuracy": np.zeros(4)}
                  for seed, head, mask, policy, role in itertools.product(
                      (7, 17, 29), ("linear", "gated"), ("bias", "all"),
                      (*plan()["policies"], "warmup"), ROLES)}
        draws = {role: np.tile(np.arange(4), (10000, 1)) for role in ROLES}
        secondary, primary, decisions = compare_scores(scores, draws, plan())
        self.assertEqual((len(secondary), len(primary)), (144, 8))
        self.assertEqual([row["met_criteria"] for row in decisions], [2, 2])
        self.assertTrue(all(not row["all_primary_criteria_met"] for row in decisions))
        self.assertEqual(primary[0]["quantiles"], [0.003125, 0.996875])

    def test_complete_catalog_scores_every_condition_and_registered_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            result = fixture.run()
            self.assertEqual((len(result["records"]), len(result["initial"])), (216, 18))
            self.assertEqual((len(result["contrasts"]), len(result["primary_contrasts"])), (144, 8))
            self.assertTrue(result["all_heads_primary_criteria_met"])
            self.assertTrue(all(row["source_components"] == 32 for row in result["primary_contrasts"]
                                if row["endpoint"] == "future_equal_month_nll"))
            for record in result["records"]:
                if record["policy"] == "zero": self.assertAlmostEqual(record["nll"], np.log(4))

    def test_failure_preserves_registered_comparisons_without_dropping_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            index = next(i for i, row in enumerate(fixture.records)
                         if (row["head"], row["mask"], row["policy"]) == ("linear", "all", "loss2"))
            fixture.records[index]["status"] = "failed"
            fixture.probabilities[index] = np.nan
            fixture.refresh()
            result = fixture.run()
            self.assertEqual(len(result["primary_contrasts"]), 8)
            self.assertTrue(all(row["status"] == "incomplete_registered_conditions" for row
                                in result["primary_contrasts"] if row["head"] == "linear"))
            self.assertFalse(result["all_heads_primary_criteria_met"])

    def test_invalid_family_or_predictions_fail_before_final_label_open(self):
        for defect in ("family", "comparison", "nonfinite", "duplicate-condition"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(tmp)
                if defect == "family": fixture.plan["primary_family"]["comparisons"] = 4
                elif defect == "comparison": fixture.plan["secondary_pairs"] = fixture.plan["secondary_pairs"][:-1]
                elif defect == "nonfinite": fixture.probabilities[0, 0] = np.nan
                else: fixture.records[-1] = fixture.records[0]
                fixture.refresh()
                opened, original = [], Path.open

                def traced(path, *args, **kwargs):
                    if path == fixture.data / "final_labels.json": opened.append(path)
                    return original(path, *args, **kwargs)

                with patch.object(Path, "open", traced), self.assertRaises(ValueError): fixture.run()
                self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
