"""Fixture-only prospective-boundary tests for a retrospective diagnostic."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from experiments.shared_stem_cell import postseal_sparse_portfolio_probe as p
from experiments.shared_stem_cell import test_postseal_historical_audit as f


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.lock = {"selected": "residual_corrected",
                     "profile": {"classes": 4, "cells": 2},
                     "parameter_counts": {"bank": 12384, "shared": 6224,
                                          "linear_distilled": 3080,
                                          "residual_corrected": 9304}}
        self.cohort = [{"case_id": str(i), "cell": i % 2,
                        "split": "confirmation" if i < 512 else "evaluation"}
                       for i in range(1024)]
        self.labels = [0] * 512
        self.probabilities = {arm: [[.9, .0333333, .0333333, .0333334]
                                  for _ in range(1024)]
                              for arm in ("bank", "shared",
                                          "linear_distilled", "residual_corrected")}
        self.confirm = {"confirmation_labels": self.labels,
                        "confirmation_ids": [row["case_id"] for row in self.cohort[:512]]}

    def test_confirmation_only_hybrid_reduces_allocated_heads(self):
        # Half the rows in one Cell are selectively wrong in frozen candidates.
        # This code changes NO evaluation labels.
        wrong = [.05, .85, .05, .05]
        for i in range(512):
            if i % 2 == 0:
                if i < 100:
                    self.probabilities["bank"][i] = wrong
                if i < 10:
                    self.probabilities["shared"][i] = wrong
                if i < 30:
                    self.probabilities["residual_corrected"][i] = wrong
            else:
                if i < 20:
                    self.probabilities["bank"][i] = wrong
                if i < 50:
                    self.probabilities["shared"][i] = wrong
                if i < 8:
                    self.probabilities["residual_corrected"][i] = wrong
        data = {"case_ids": [r["case_id"] for r in self.cohort],
                "predictions": self.probabilities}
        plan = p.freeze_from_confirmation(self.lock, self.cohort, data, self.confirm)
        self.assertEqual(plan["chosen_per_cell"], {"0": "shared", "1": "residual_corrected"})
        self.assertEqual(plan["deployed_head_parameters"], 7764)
        self.assertEqual(plan["head_bytes_if_f32"], 31056)
        self.assertTrue(plan["strict_parameter_saving"])
        self.assertFalse(plan["production_accepted"])

    def test_mutating_unseen_evaluation_probabilities_cannot_change_selection(self):
        data = {"case_ids": [r["case_id"] for r in self.cohort],
                "predictions": deepcopy(self.probabilities)}
        original = p.freeze_from_confirmation(self.lock, self.cohort, data, self.confirm)
        # Evaluation examples are deliberately altered; the frozen decision
        # cannot see their labels or candidate quality.
        for rows in data["predictions"].values():
            for i in range(512, 1024):
                rows[i] = [.01, .97, .01, .01]
        later = p.freeze_from_confirmation(self.lock, self.cohort, data, self.confirm)
        self.assertEqual(original, later)

    def test_partial_scope_or_cell_and_bad_counts_refuse(self):
        data = {"case_ids": [r["case_id"] for r in self.cohort],
                "predictions": self.probabilities}
        with self.assertRaises(p.a.AuditError):
            p.freeze_from_confirmation(self.lock, self.cohort[:-1], data, self.confirm)
        bad = deepcopy(self.lock)
        bad["parameter_counts"]["residual_corrected"] = 9303
        with self.assertRaises(p.a.AuditError):
            p.freeze_from_confirmation(bad, self.cohort, data, self.confirm)
        self.cohort[0]["cell"] = 1
        with self.assertRaises(p.a.AuditError):
            p.freeze_from_confirmation(self.lock, self.cohort, data, self.confirm)

    def test_selection_file_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "selection.json"
            first = p._sealed_json(file, {"production_accepted": False})
            self.assertEqual(first, p.a.digest(file.read_bytes()))
            with self.assertRaises(FileExistsError):
                p._sealed_json(file, {"production_accepted": True})

    def test_historical_negative_fixture_cannot_be_relabelled(self):
        # The real archive needs its externally pinned SHA. This fixture is
        # solely for deterministic structure/no-promotion regression.
        case = f.fixture()
        case["candidate-lock.json"]["profile"].update(cells=2)
        case["candidate-lock.json"]["parameter_counts"] = self.lock["parameter_counts"]
        case["predictions.json"]["candidate_lock_sha256"] = p.a.digest(
            f.raw(case["candidate-lock.json"]))
        case["confirmation.json"]["candidate_lock_sha256"] = p.a.digest(
            f.raw(case["candidate-lock.json"]))
        case["confirmation.json"]["predictions_sha256"] = p.a.digest(
            f.raw(case["predictions.json"]))
        case["confirmation.json"]["proposed"] = "residual_corrected"
        case["report.json"]["predictions_sha256"] = p.a.digest(
            f.raw(case["predictions.json"]))
        case["report.json"]["confirmation_sha256"] = p.a.digest(
            f.raw(case["confirmation.json"]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f.write_fixture(root, case)
            out = root / "selection-study"
            result = p.run(root, None, out)
            self.assertEqual(result["original_bank_score"]["correct"], 512)
            self.assertFalse(result["production_accepted"])
            self.assertTrue((out / "selection.json").is_file())
            with self.assertRaises(FileExistsError):
                p.run(root, None, out)


if __name__ == "__main__":
    unittest.main()
