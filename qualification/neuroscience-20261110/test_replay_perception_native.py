"""Constructed contract tests only; no real task/source/owner qualification."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

import replay_perception_native as runner


def case(source, marker, role="development"):
    return {"id": source + "-case", "source_id": source, "source_sha256": marker * 64,
            "role": role, "reference": {"path": "MUST_NOT_OPEN"}}


def registered(value, seed=7):
    return {"source_id": value["source_id"], "case_id": value["id"], "case": value,
            "seed": seed, "read_condition": "original"}


def report(repeats=1):
    return {"evidence_kind": "native_macro", "rows": [
        {"source_id": "one-source", "case_id": "one-case", "seed": seed, "arm_id": arm,
         "status": "COMPLETED", "quality": quality, "task_cost": 0.1}
        for seed in range(repeats) for arm, quality in (("tuned-fixed", 0.5), ("conditional", 0.7))]}


def planned(repeats=1):
    return {"registered_cases": [{"source_id": "one-source", "case_id": "one-case", "seed": seed}
                                 for seed in range(repeats)]}


class PhaseContractTests(unittest.TestCase):
    def setUp(self):
        self.collection = {"pairs": [{"split": split, "case": case(split, marker, "train")}
                           for split, marker in (("train", "1"), ("calibration", "2"))]}
        self.model = SimpleNamespace(data={"fit_sources": ["train"], "calibration_sources": ["calibration"],
            "source_bindings": {"train": "1" * 64, "calibration": "2" * 64}})
        self.phases = {p: [registered(case(p, marker))] for p, marker in (("B", "3"), ("C", "4"))}

    def test_source_split_does_not_open_reference_or_count_seed_as_source(self):
        self.phases["B"].append(registered(case("B", "3"), 99))
        groups = runner.validate_partitions(self.phases, self.collection, self.model)
        self.assertEqual(groups, {"train": ["train"], "calibration": ["calibration"], "B": ["B"], "C": ["C"]})

    def test_original_collection_cannot_smuggle_development_b_or_c(self):
        # Before this guard an upstream collection row relabeled as B or C
        # passed this boundary if its digest matched the future roster.
        for split in ("B", "C", "future", "holdout"):
            with self.subTest(split=split):
                collection = deepcopy(self.collection)
                source = self.phases["B" if split == "B" else "C"][0]["case"]
                collection["pairs"].append({"split": split, "case": deepcopy(source)})
                with self.assertRaisesRegex(ValueError, "train/calibration only"):
                    runner.validate_partitions(self.phases, collection, self.model)

    def test_cross_phase_same_source_or_physical_alias_rejected(self):
        for value in (case("B", "3"), case("different-name", "3"), case("train", "1")):
            with self.subTest(value=value):
                phases = deepcopy(self.phases)
                phases["C"] = [registered(value, 12345)]
                with self.assertRaises(ValueError):
                    runner.validate_partitions(phases, self.collection, self.model)

    def test_sealed_case_and_training_source_mismatch_rejected(self):
        self.phases["C"][0]["case"]["role"] = "confirmation"
        with self.assertRaises(ValueError):
            runner.validate_partitions(self.phases, self.collection, self.model)
        self.phases["C"][0]["case"]["role"] = "development"
        self.model.data["fit_sources"].append("C")
        with self.assertRaises(ValueError):
            runner.validate_partitions(self.phases, self.collection, self.model)
        self.model.data["fit_sources"].pop()
        self.model.data["source_bindings"]["train"] = "9" * 64
        with self.assertRaises(ValueError):
            runner.validate_partitions(self.phases, self.collection, self.model)

    def test_missing_outcome_preserves_plan_and_blocks_effect_estimate(self):
        original = report(3)
        original["rows"][3].update(status="UNKNOWN", quality=None)
        result = runner.summarize(original, planned(3))
        self.assertEqual((result["planned"], result["incomplete"], result["planned_source_clusters"]), (6, 1, 1))
        self.assertIsNone(result["observed_latency_net_difference"])
        self.assertEqual(runner.summarize(report(3), planned(3))["planned_source_clusters"], 1)

    def test_fixture_and_duplicate_arm_cannot_be_admitted(self):
        fixture = report()
        fixture["evidence_kind"] = "fixture"
        with self.assertRaises(ValueError):
            runner.summarize(fixture, planned())
        original = report()
        original["rows"][1] = deepcopy(original["rows"][0])
        with self.assertRaises(ValueError):
            runner.summarize(original, planned())

    def test_self_consistent_replaced_context_cannot_replace_frozen_roster(self):
        original = report()
        for row in original["rows"]:
            row.update(source_id="replacement-source", case_id="replacement-case", seed=991)
        with self.assertRaises(ValueError):
            runner.summarize(original, planned())

    def test_quality_and_cost_domains_and_missing_owner_decision(self):
        for key, value in (("quality", 1.01), ("quality", -0.01), ("task_cost", -1), ("task_cost", float("inf"))):
            original = report()
            original["rows"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                runner.summarize(original, planned())
        result = runner.summarize(report(), planned())
        self.assertEqual((result["adoption"], result["owner_decision"]), ("NOT_REQUESTED", None))

    def test_external_pin_duplicate_json_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for payload in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
                path.write_text(payload)
                with self.assertRaises(ValueError):
                    runner.read(path)
            path.write_text('{"a":1}')
            with self.assertRaises(ValueError):
                runner.read(path, "0" * 64)

    def test_process_death_retains_unknown_and_never_redispatches(self):
        child = """
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[2])
import replay_perception_native as r
root = Path(sys.argv[1])
def dispatch(*args, **kwargs):
    with (root / 'contact').open('a') as stream:
        stream.write('once\\n')
    os._exit(9)
m = {'digest': lambda x: 'plan-pin',
     'macro_execution_plan': SimpleNamespace(validate_plan=lambda *a: None, check_inputs=lambda *a: None),
     'macro_execution': SimpleNamespace(execute=dispatch)}
r.run_phase(root, 'B', {'execution_plan_sha256s': {'B': 'plan-pin'}, 'planned': {'B': 2}}, (m,))
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner.save(root / "FROZEN.json", {})
            runner.save(root / "B_PLAN.json", {})
            command = [sys.executable, "-c", child, str(root), str(Path(runner.__file__).parent)]
            first = subprocess.run(command, capture_output=True, timeout=10)
            second = subprocess.run(command, capture_output=True, timeout=10)
            self.assertEqual(first.returncode, 9)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn(b"FileExistsError", second.stderr)
            self.assertEqual((root / "contact").read_text(), "once\n")
            self.assertEqual(runner.read(root / "B_START.json")["status"], "MAY_HAVE_DISPATCHED")
            self.assertFalse((root / "B_TERMINAL.json").exists())
            with self.assertRaises(ValueError):
                runner.reconcile(root, "B", {"digest": lambda x: "changed"}, {"execution_plan_sha256s": {"B": "plan-pin"}})
            with self.assertRaises(ValueError):
                runner.run_phase(root, "C", {}, ({},))

    def test_native_dependencies_are_checked_before_unchanged_driver_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            driver, analysis, dependency = [root / p for p in (
                "scripts/ctrl_macro_study.py", "scripts/ctrl_macro_analysis.py", "dependency.py")]
            driver.write_text("raise AssertionError('MUST_NOT_IMPORT')\n")
            analysis.write_text("pass\n")
            dependency.write_text("pass\n")
            pin = runner.save(root / "FROZEN.json", {
                "driver_sha256": runner.sha(driver.read_bytes()),
                "analysis_sha256": runner.sha(analysis.read_bytes()),
                "collection_plan": {"source_pins": [{"path": str(dependency),
                    "sha256": runner.sha(dependency.read_bytes())}]}})
            registration = {"repository": str(root), "training_run": str(root), "training_freeze_sha256": pin}
            for path in (dependency, analysis):
                original = path.read_bytes()
                path.write_bytes(original + b"# changed\n")
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "before import"):
                    runner.load_native(registration)
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
