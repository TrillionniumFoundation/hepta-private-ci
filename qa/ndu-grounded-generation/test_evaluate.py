"""Behavioral tests of the independent scorer, not model capability claims."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

import evaluate as ev


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "annotation.png"
        Image.new("RGB", (32, 24), "white").save(self.path)
        self.ref = {"task_id": "task", "source_id": "source", "image_size": [32, 24],
                    "boxes": [[0.1, 0.1, 0.4, 0.9]], "label": "cat", "count": 1,
                    "largest_side": "left"}
        self.episode = {"task_id": "task", "method": "ndu", "seed": 7,
                        "budget_cap": 10, "budget_unit": "wall_seconds", "termination": "completed",
                        "text": "There are 1 cat instances. The largest instance is on the left.",
                        "boxes": copy.deepcopy(self.ref["boxes"]), "label": "cat",
                        "artifact_path": str(self.path), "artifact_sha256": self.digest(),
                        "controls": [], "model_revision": "frozen-sha", "policy_version": "v1",
                        "costs": [{"component": name, "calls": int(name == "backbone"),
                                   "wall_seconds": float(name == "backbone")}
                                  for name in sorted(ev.REQUIRED_COST_COMPONENTS)]}

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_exact_fractional_cvar(self):
        self.assertAlmostEqual(ev.cvar([0, 1, 2, 3], 0.625), 8 / 3)
        self.assertEqual(ev.cvar([0, 1, 2, 3], 0), 1.5)
        self.assertEqual(ev.cvar([0, 1, 2, 3], 0.99), 3)
        for losses, alpha in (([], 0.9), ([float("nan")], 0.9), ([1], 1)):
            with self.assertRaises(ValueError):
                ev.cvar(losses, alpha)

    def test_matching_is_one_to_one_and_uses_augmenting_paths(self):
        box = self.ref["boxes"][0]
        self.assertAlmostEqual(ev.matching_score([box, box], [box])["box_f1"], 2 / 3)
        gold = [[0, 0, 0.75, 1], [0.25, 0, 1, 1]]
        pred = [[0.125, 0, 0.875, 1], [0, 0, 0.5, 1]]
        self.assertEqual(ev.matching_score(pred, gold)["matches"], 2)
        self.assertEqual(ev.matching_score([[0.7, 0, 1, 1]], [box])["matches"], 0)
        with self.assertRaises(ValueError):
            ev.matching_score([[1, 0, 0, 1]], [box])

    def test_terminal_quality_and_text_disagreement(self):
        good = ev.score_episode(self.episode, self.ref)
        self.assertEqual((good["quality"], good["severe"]), (1, 0))
        self.episode["text"] = "There are 2 cat instances. The largest instance is on the right."
        bad = ev.score_episode(self.episode, self.ref)
        self.assertEqual((bad["quality"], bad["text_consistent"], bad["severe"]), (0.9, False, 1))
        self.assertIsNone(ev.parse_text("There are 0 cat instances. The largest instance is on the left."))

    def test_artifact_tamper_and_dimensions_are_rejected(self):
        Image.new("RGB", (32, 24), "black").save(self.path)
        tampered = ev.score_episode(self.episode, self.ref)
        self.assertFalse(tampered["artifact_valid"])
        self.assertEqual(tampered["quality"], 0)
        self.assertTrue(ev.score_episode(dict(self.episode, termination="incomplete"), self.ref)["validation_errors"])
        Image.new("RGB", (31, 24)).save(self.path)
        self.episode["artifact_sha256"] = self.digest()
        self.assertFalse(ev.score_episode(self.episode, self.ref)["artifact_valid"])

    def test_missing_costs_and_over_budget_fail_without_zeroing_cost(self):
        incomplete = copy.deepcopy(self.episode)
        incomplete["costs"] = incomplete["costs"][:-1]
        result = ev.score_episode(incomplete, self.ref)
        self.assertIsNone(result["wall_seconds"])
        self.assertTrue(result["validation_errors"])
        mismatch = ev.score_episode(dict(self.episode, actual_wall_seconds=0.5), self.ref)
        self.assertTrue(mismatch["validation_errors"])
        self.episode["costs"].append({"component": "backbone", "calls": 1, "wall_seconds": 12})
        result = ev.score_episode(self.episode, self.ref)
        self.assertEqual(result["wall_seconds"], 13)
        self.assertTrue(result["budget_exceeded"])
        self.assertEqual(result["quality"], 0)

    def test_full_roster_and_negative_results_do_not_prove_experiment(self):
        episodes = [dict(self.episode, method=method) for method in ev.METHODS]
        report = ev.evaluate([self.ref], episodes, bootstrap_samples=12)
        self.assertTrue(report["engineering_pass"], report["errors"])
        self.assertFalse(report["experiment_pass"])
        self.assertFalse(report["production_pass"])
        self.assertEqual(len(report["points"]), 12)
        negative = [dict(row, boxes=[], text="There are 0 cat instances. No largest instance.")
                    for row in episodes]
        report = ev.evaluate([self.ref], negative, bootstrap_samples=12)
        self.assertTrue(report["engineering_pass"])
        self.assertTrue(all(row["severe"] == 1 for row in report["scores"]))
        self.assertFalse(report["experiment_pass"])
        for broken in (episodes[:-1], episodes + [episodes[0]],
                       [dict(row, seed=8) if row["method"] == "base" else row for row in episodes]):
            report = ev.evaluate([self.ref], broken, bootstrap_samples=12)
            self.assertFalse(report["engineering_pass"])
            self.assertEqual(report["empirical_frontier"], [])

    def test_source_cluster_pairing_and_frontier(self):
        row = ev.score_episode(self.episode, self.ref)
        rows = [dict(row, seed=seed) for seed in (1, 2, 3)]
        result = ev.paired_source_bootstrap(rows, rows, samples=12)
        self.assertEqual(result["source_groups"], 1)
        self.assertTrue(all(x == {"low": 0, "high": 0} for x in result["deltas"].values()))
        with self.assertRaises(ValueError):
            ev.paired_source_bootstrap(rows, rows[:-1], samples=12)
        point = {"point_id": "good", "budget_unit": "wall_seconds", "budget_cap": 10,
                 "quality": 0.8, "cvar": 0.2, "coverage": 1, "wall_seconds": 2}
        points = [point, dict(point, point_id="dominated", cvar=0.3),
                  dict(point, point_id="missing", wall_seconds=None),
                  dict(point, point_id="other_budget", cvar=0.3, budget_cap=20)]
        self.assertEqual(ev.empirical_frontier(points), ["good", "other_budget"])

    def test_cli_writes_report_and_fails_incomplete_roster(self):
        directory = Path(self.temp.name)
        refs, episodes, output = (directory / name for name in ("refs.jsonl", "episodes.jsonl", "report.json"))
        refs.write_text(json.dumps(self.ref) + "\n")
        for methods, exit_code in ((ev.METHODS, 0), (ev.METHODS[:-1], 2)):
            episodes.write_text("".join(json.dumps(dict(self.episode, method=method)) + "\n"
                                        for method in methods))
            run = subprocess.run([sys.executable, str(Path(ev.__file__)), "--references", str(refs),
                                  "--episodes", str(episodes), "--output", str(output),
                                  "--bootstrap-samples", "8"], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, exit_code, run.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["engineering_pass"], exit_code == 0)
            self.assertFalse(report["production_pass"])


if __name__ == "__main__":
    unittest.main()
