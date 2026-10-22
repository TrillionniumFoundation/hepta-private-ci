"""Phase/resume/report contract tests; no model capability is simulated here."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import experiment as ex
from backend import OBSERVATION_FIELDS
from generation import COMPONENTS
from verification import Verifier


class InlineJobs:
    def __init__(self, owner, **kwargs):
        self.owner, self.phase = owner, kwargs["initargs"][-1]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def map(self, function, jobs, chunksize=1):
        for job in jobs:
            self.owner.jobs.append(copy.deepcopy(job))
            yield self.owner.episode(job, self.phase)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.training = self.root / "training"
        self.training.mkdir()
        (self.root / "manifest.json").write_text("{}\n")
        for name in ("cells.pt", "policies.pt"):
            (self.training / name).write_bytes(name.encode())
        self.args = SimpleNamespace(model="unused", cohort=str(self.root), work=str(self.root), budget=10., workers=2)
        self.pairs, self.jobs, self.missing = [], [], set()
        for index in range(2):
            task = f"task{index}"
            obs = {"task_id": task, "image_path": "not-opened.png", "image_sha256": "0" * 64,
                   "prompt": "Count cats.", "target_category": "cat"}
            ref = {"task_id": task, "source_id": task, "image_size": [32, 24],
                   "boxes": [[0.1, 0.1, 0.4, 0.8]], "label": "cat", "count": 1, "largest_side": "left"}
            self.pairs.append((obs, ref))
        records = [{"generated": {"tokens": [0, 2], "boxes": ref["boxes"], "controls": [], "termination": "eos"},
                    "quality": float(index), "severe": float(1 - index), "split": "train"}
                   for index, (_, ref) in enumerate(self.pairs)]
        Verifier.fit(records).save(self.training / "verifier.json")
        patches = [patch.object(ex, "iter_pairs", side_effect=lambda *args: iter(self.pairs)),
                   patch.object(ex, "ProcessPoolExecutor", side_effect=lambda **kw: InlineJobs(self, **kw)),
                   patch.object(ex, "score_episode", side_effect=self.score),
                   patch.object(ex, "evaluate", return_value={"engineering_pass": True, "experiment_pass": False,
                                                              "production_pass": False, "errors": [], "points": []}),
                   patch("builtins.print")]
        for replacement in patches:
            replacement.start()
            self.addCleanup(replacement.stop)

    def score(self, row, reference):
        quality = float(reference["task_id"] == "task1")
        return {"quality": quality, "loss": 1 - quality, "severe": 1 - quality,
                "source_id": reference["source_id"], "validation_errors": []}

    def episode(self, job, phase):
        observation, method, seed, risk, partner, budget = job
        self.assertEqual(set(observation), OBSERVATION_FIELDS)
        self.assertEqual(set(partner), OBSERVATION_FIELDS)
        names = ("cells.pt",) if phase == "collect" else (
            "cells.pt", "policies.pt", "verifier-calibrated.json" if phase == "test" else "verifier.json")
        generated = {"tokens": [0, 2], "boxes": [[0.1, 0.1, 0.4, 0.8]], "controls": [], "termination": "eos"}
        return {"task_id": observation["task_id"], "method": method, "seed": seed, "risk_weight": risk,
                "budget_cap": budget, "budget_unit": "wall_seconds", "actual_wall_seconds": 1., "actual_cpu_seconds": 0.4,
                "ledger_minus_wall_seconds": 0., "failures": [], "controls": [], "termination": "completed",
                "verification": {"severe_probability": None if method in self.missing else 0.25, "quality": 0.5},
                "resident_initialization": {"worker_pid": 123, "load_seconds": 0.2,
                                            "frozen_tensor_sha256": "0" * 64, "threads": 4},
                "generated_for_verifier": generated,
                "checkpoint_identities": {name: ex.sha(self.training / name) for name in names},
                "costs": [{"component": name, "calls": int(name == "backbone"),
                           "wall_seconds": float(name == "backbone")} for name in COMPONENTS]}

    def collect_receipts(self):
        return ex.execute(self.args, "collect", "train", [("explore", 23, 0.5)])

    def test_jobs_are_reference_free_and_resume_does_not_rerun_complete_work(self):
        rows, _ = self.collect_receipts()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.jobs), 2)
        resumed, _ = self.collect_receipts()
        self.assertEqual(rows, resumed)
        self.assertEqual(len(self.jobs), 2)

    def test_phase_split_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            ex.execute(self.args, "collect", "test", [("explore", 23, 0.5)])

    def test_resume_validator_rejects_mismatched_identity_and_duplicate_rows(self):
        row = {"task_id": "task0", "method": "base", "seed": 23, "risk_weight": 0.5,
               "checkpoint_identities": {"cells.pt": "hash"}, "split": "test", "budget_cap": 10.,
               "budget_unit": "wall_seconds"}
        expected = {("task0", "base", 23, 0.5)}
        arguments = (expected, {"cells.pt": "hash"}, "test", 10.)
        self.assertEqual(ex.validate_resume([row], *arguments), expected)
        for key, value in (("task_id", "foreign"), ("split", "train"), ("budget_cap", 11.),
                           ("checkpoint_identities", {"cells.pt": "different"})):
            with self.assertRaises(ValueError):
                ex.validate_resume([dict(row, **{key: value})], *arguments)
        with self.assertRaises(ValueError):
            ex.validate_resume([row, row], *arguments)

    def test_risk_summary_counts_missing_invalid_and_available_separately(self):
        rows = []
        for probability, severe in ((0.25, 1), (0.75, 0), (None, 1), (1.2, 0), (float("nan"), 1)):
            rows.append({"method": "base", "verification": {"severe_probability": probability},
                         "calibrated_risk": probability, "score": {"severe": severe}})
        rows.append({"method": "ndu", "verification": {"severe_probability": None},
                     "calibrated_risk": None, "score": {"severe": 1}})
        summary = ex.risk_calibration_summary(rows)
        self.assertEqual([summary["base"][key] for key in ("available", "missing", "invalid")], [2, 1, 2])
        self.assertAlmostEqual(summary["base"]["brier"], 0.5625)
        self.assertAlmostEqual(summary["base"]["risk_coverage"], 0.4)
        self.assertIsNone(summary["ndu"]["brier"])
        self.assertEqual(summary["ndu"]["risk_coverage"], 0)

    def test_resume_rejects_changed_worker_count_and_checkpoint(self):
        self.collect_receipts()
        self.args.workers = 1
        with self.assertRaises(ValueError):
            self.collect_receipts()
        self.args.workers = 2
        (self.training / "cells.pt").write_bytes(b"different weights")
        with self.assertRaises(ValueError):
            self.collect_receipts()

    def test_resume_rejects_foreign_rows_and_claimed_checkpoint_mismatch(self):
        rows, _ = self.collect_receipts()
        journal = self.root / "collect.episodes.jsonl"
        foreign = dict(rows[0], task_id="not-in-this-cohort")
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows + [foreign]))
        with self.assertRaises(ValueError):
            self.collect_receipts()
        rows[0]["checkpoint_identities"]["cells.pt"] = "wrong"
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaises(ValueError):
            self.collect_receipts()

    def test_completed_journal_score_tampering_is_not_resealed_by_resume(self):
        rows, _ = self.collect_receipts()
        rows[0]["score"]["quality"] = 0.99
        journal = self.root / "collect.episodes.jsonl"
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaises(ValueError):
            self.collect_receipts()

    def test_test_rejects_uncalibrated_artifact_and_test_used_selection(self):
        ex.select(self.args)
        ex.calibrate(self.args)
        calibrated = self.training / "verifier-calibrated.json"
        actual_calibration = calibrated.read_bytes()
        calibrated.write_bytes((self.training / "verifier.json").read_bytes())
        with self.assertRaises(ValueError):
            ex.final_test(self.args)
        calibrated.write_bytes(actual_calibration)
        path = self.root / "selection.json"
        selection = json.loads(path.read_text())
        selection["test_used"] = True
        path.write_text(json.dumps(selection))
        with self.assertRaises(ValueError):
            ex.final_test(self.args)

    def test_final_preconditions_bind_calibration_to_trained_weights_and_selected_risk(self):
        ex.select(self.args)
        ex.calibrate(self.args)
        selected = ex.check_final_preconditions(self.root, self.root)
        self.assertEqual(selected["split"], "dev")
        calibrated_path = self.training / "verifier-calibrated.json"
        original = calibrated_path.read_bytes()
        calibrated = Verifier.load(calibrated_path)
        calibrated.quality_weights[0] += 0.1
        calibrated.save(calibrated_path)
        with self.assertRaises(ValueError):
            ex.check_final_preconditions(self.root, self.root)
        calibrated_path.write_bytes(original)
        selected["chosen_risk_weight"] = 1.0 if selected["chosen_risk_weight"] != 1.0 else 0.0
        (self.root / "selection.json").write_text(json.dumps(selected))
        with self.assertRaises(ValueError):
            ex.check_final_preconditions(self.root, self.root)

    def test_missing_risk_probability_still_writes_complete_report(self):
        ex.select(self.args)
        ex.calibrate(self.args)
        self.missing = {"base", "ndu"}
        ex.final_test(self.args)
        report = json.loads((self.root / "report.json").read_text())
        self.assertEqual(report["execution"]["episodes"], 2 * len(ex.METHODS))
        self.assertIsNone(report["calibration"]["base"]["brier"])
        self.assertIsNone(report["calibration"]["ndu"]["brier"])
        self.assertAlmostEqual(report["calibration"]["static_cells"]["brier"], 0.3125)
        self.assertFalse(report["experiment_pass"])
        self.assertFalse(report["production_pass"])


if __name__ == "__main__":
    unittest.main()
