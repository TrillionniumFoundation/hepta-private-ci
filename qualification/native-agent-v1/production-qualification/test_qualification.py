import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from contracts import BUDGET, CONTROLS, LANES, SOURCES, digest, preflight, validate
from qualify import run
from statistics_gate import distribution, summarize

ROOT = Path(__file__).parent


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = json.loads((ROOT / "plan.example.json").read_text())
        self.corpus = json.loads((ROOT / "corpus.json").read_text())

    def pinned_plan(self):
        self.plan["revisions"]["codex_upstream"] = "1" * 40
        self.plan["source_root"] = str(self.root)
        self.plan["fixture"]["directory"] = str(self.root)
        for name in SOURCES + ("fixture_tool.py", "fixture.txt", "native", "codex", "facade"):
            path = self.root / name
            path.write_text(name + "\n")
            if name in SOURCES:
                self.plan["source_hashes"][name] = digest(path)
            elif name in self.plan["binaries"]:
                self.plan["binaries"][name] = {"path": str(path), "sha256": digest(path)}
            else:
                self.plan["fixture"]["files"][name] = digest(path)
        return self.plan

    def test_preflight_is_readonly_and_missing_pins_prevent_launch(self):
        with patch("fixture_adapter.subprocess.run") as launch:
            self.assertEqual(run(self.plan, self.corpus, self.root / "held", execute=True), 2)
        launch.assert_not_called()
        report = json.loads((self.root / "held/REPORT.json").read_text())
        self.assertEqual(report["statuses"], {"held": 84})
        self.assertEqual(report["production_qualification"], "held")

    def test_changed_input_and_binary_fail_fingerprints(self):
        self.pinned_plan()
        self.assertEqual(preflight(self.plan), [])
        (self.root / "fixture.txt").write_text("changed input")
        (self.root / "native").write_text("changed binary")
        self.assertEqual(sum("mismatch" in e for e in preflight(self.plan)), 2)

    def test_immutable_run_never_overwrites_evidence(self):
        output = self.root / "immutable"
        run(self.plan, self.corpus, output)
        before = (output / "FROZEN.json").read_bytes()
        with self.assertRaises(FileExistsError):
            run(self.plan, self.corpus, output, execute=True)
        self.assertEqual((output / "FROZEN.json").read_bytes(), before)

    def test_small_samples_are_maxima_not_p95(self):
        self.assertEqual(distribution([1, 2, 3, 4, 5, 600])["max"], 600)
        self.assertIsNone(distribution([1, 2, 3, 4, 5, 600])["empirical_p95"])
        self.assertEqual(distribution(range(1, 101))["empirical_p95"], 95)
        for invalid in ([float("nan")], [-1], [True], [None, 1]):
            with self.assertRaises(ValueError):
                distribution(invalid)

    def test_schema_rejects_profile_mismatch_and_removed_cases(self):
        altered = copy.deepcopy(self.plan)
        altered["profiles"]["native"]["output_tokens"] = 1024
        with self.assertRaises(ValueError):
            validate(altered, self.corpus)
        altered = copy.deepcopy(self.corpus)
        altered["cases"].pop()
        with self.assertRaises(ValueError):
            validate(self.plan, altered)
        altered = copy.deepcopy(self.corpus)
        altered["cases"][0]["input"] = "A prompt the old runner cannot apply"
        with self.assertRaises(ValueError):
            validate(self.plan, altered)
        self.plan["owner_scope"] = "production"
        with self.assertRaises(ValueError):
            validate(self.plan, self.corpus)

    def test_optimized_notes_require_nonempty_text_before_launch(self):
        self.pinned_plan()
        self.plan["group"] = "individually_optimized"
        self.plan["optimization_notes"] = {lane: "Explicit lane configuration description" for lane in LANES}
        validate(self.plan, self.corpus)
        for index, value in enumerate((None, "", " \t\n", True, 1, {}, ["description"])):
            with self.subTest(value=value):
                altered = copy.deepcopy(self.plan)
                altered["optimization_notes"]["native"] = value
                output = self.root / f"invalid-note-{index}"
                with patch("fixture_adapter.subprocess.run") as launch:
                    with self.assertRaises(ValueError):
                        run(altered, self.corpus, output, execute=True)
                launch.assert_not_called()
                self.assertFalse(output.exists())

    def test_changed_control_contract_is_rejected_before_launch(self):
        self.pinned_plan()
        mutations = {
            "capabilities": ["production_owner", "pty"],
            "oracle": ["Require an original production PTY terminal receipt."],
            "fault": {"kind": "lose_terminal_ack", "at": "after_physical_effect"},
        }
        for case_id in CONTROLS:
            for field, value in mutations.items():
                with self.subTest(case=case_id, field=field):
                    altered = copy.deepcopy(self.corpus)
                    next(case for case in altered["cases"] if case["id"] == case_id)[field] = value
                    output = self.root / f"invalid-{case_id}-{field}"
                    with patch("fixture_adapter.subprocess.run") as launch:
                        with self.assertRaises(ValueError):
                            run(self.plan, altered, output, execute=True)
                    launch.assert_not_called()
                    self.assertFalse(output.exists())

    def test_matrix_rejects_missing_duplicate_mixed_and_promoted_rows(self):
        run(self.plan, self.corpus, self.root / "matrix")
        rows = json.loads((self.root / "matrix/REPORT.json").read_text())["rows"]
        for bad in (rows[:-1], rows + [rows[0]]):
            with self.assertRaises(ValueError):
                summarize(self.plan, self.corpus, bad)
        bad = copy.deepcopy(rows)
        bad[0]["mode"] = "live"
        with self.assertRaises(ValueError):
            summarize(self.plan, self.corpus, bad)
        bad = copy.deepcopy(rows)
        next(r for r in bad if r["case"] == "pty")["status"] = "passed"
        with self.assertRaises(ValueError):
            summarize(self.plan, self.corpus, bad)

    def test_adapter_retains_failures_unattempted_slots_and_raw_metrics(self):
        self.pinned_plan()
        metrics = {"memory": {"pss_peak_complete_sample_bytes": 123},
                   "cpu": {"process_lifecycle_observed_seconds": 5,
                           "cgroup_nonoverlap_observed_seconds": 7,
                           "process_and_cgroup_totals_overlap_do_not_add": True}}

        def fixture_process(argv, **kwargs):
            lane = argv[argv.index("--lane") + 1]
            raw = Path(argv[argv.index("--output") + 1])
            raw.mkdir()
            executor = "codex" if lane == "app-server" else lane
            report = {"lane": lane, "mode": self.plan["mode"], "model": self.plan["model"]["id"],
                "budgets": BUDGET, "source_fingerprints": self.plan["source_hashes"],
                "executor_sha256": self.plan["binaries"][executor]["sha256"],
                "runtime_helper_sha256": self.plan["binaries"]["native"]["sha256"],
                "model_capture_complete": True, "only_shared_tool_inventory": True,
                "metrics": metrics, "summary": {"p95_nearest_rank": 99999}, "rows": [
                    {"name": "00-sum", "correct": True, "wall_ms": 8, "tool_feedback_audit": {"valid": True}},
                    {"name": "00-lines", "correct": False, "wall_ms": 20, "tool_feedback_audit": {"valid": False}}]}
            (raw / "REPORT.json").write_text(json.dumps(report))
            return subprocess.CompletedProcess(argv, 1)

        with patch("fixture_adapter.subprocess.run", side_effect=fixture_process) as launch:
            run(self.plan, self.corpus, self.root / "attempt", execute=True)
        self.assertEqual(launch.call_count, 3)
        result = json.loads((self.root / "attempt/REPORT.json").read_text())
        self.assertEqual(result["statuses"], {"passed": 3, "failed": 3, "not_run": 12, "held": 66})
        self.assertEqual(result["lanes"][0]["metrics"], metrics)
        self.assertEqual(result["comparative_performance_claims"], "held")
        failed = next(s for s in result["case_summaries"] if s["lane"] == "native" and s["case"] == "control_lines")
        self.assertEqual(failed["attempted_wall_ms_including_failures"]["max"], 20)
        self.assertEqual(failed["successful_wall_ms"]["n"], 0)
        self.assertNotIn("p95_nearest_rank", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
