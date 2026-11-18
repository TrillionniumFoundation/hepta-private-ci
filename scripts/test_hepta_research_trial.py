"""Actual subprocess, replay, failure and budget coverage for development trials."""

import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from hepta_cells.research_trial import TrialLedger, sha256, validate_plan
from hepta_cells.research_trial_runner import DevelopmentTrial


class DevelopmentTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capsule = self.root / "source"
        self.capsule.mkdir()
        (self.capsule / "tool.py").write_text(
            "import pathlib, sys, time\n"
            "output, mode = pathlib.Path(sys.argv[1]), sys.argv[2]\n"
            "(output / 'effect').write_text('one action')\n"
            "if mode == 'sleep': time.sleep(30)\n"
            "if mode == 'fail': raise SystemExit(7)\n"
            "(output / 'answer.json').write_text('1')\n"
        )
        (self.capsule / "oracle.py").write_text(
            "import pathlib, sys, json\n"
            "answer = json.loads((pathlib.Path(sys.argv[1]) / 'answer.json').read_text())\n"
            "print(json.dumps({'success': answer == 1}))\n"
        )
        exe = Path(sys.executable).resolve()
        self.plan = {
            "schema": "hepta.development-trial.v1",
            "mode": "development",
            "runtime": {
                "executable": str(exe),
                "sha256": sha256(exe.read_bytes()),
                "version": sys.version,
            },
            "files": {p.name: sha256(p.read_bytes()) for p in self.capsule.iterdir()},
            "tasks": {
                "task": {
                    "source_groups": ["one_template"],
                    "phase": "development",
                    "exposure": "synthetic_development",
                }
            },
            "tools": {
                "success": ["{python}", "-I", "-B", "tool.py", "{output}", "success"]
            },
            "oracle": ["{python}", "-I", "-B", "oracle.py", "{output}"],
            "arms": ["one", "two"],
            "schedule": [
                dict(attempt_id=a, task_id="task", arm=a, tool_id="success")
                for a in ("one", "two")
            ],
            "attempt_limit_per_arm": 1,
            "timeout_seconds": 5,
            "catalog_scope": "synthetic development tool only; no learned repair",
        }

    def create(self):
        return DevelopmentTrial.create(
            self.root / "trial", plan=self.plan, capsule_root=self.capsule
        )

    def test_both_arms_execute_identical_tools_oracle_and_fresh_copies(self):
        trial = self.create()
        finals = [trial.execute(a) for a in ("one", "two")]
        report = trial.report()
        self.assertEqual([f["outcome"] for f in finals], ["success", "success"])
        self.assertEqual(report["task_observation"]["outcomes"], {"success": 2})
        self.assertEqual(report["declared_source_groups"], ["one_template"])
        self.assertEqual(report["trial"]["charged"], 2)
        self.assertEqual(report["trial"]["pending"], 0)
        self.assertEqual(report["fresh_confirmation"], 0)
        for a in ("one", "two"):
            path = trial.root / "attempts" / a
            self.assertEqual((path / "output/effect").read_text(), "one action")
            self.assertEqual(
                json.loads((path / "oracle/stdout").read_text()), {"success": True}
            )
            self.assertEqual(
                finals[0]["processes"]["tool"]["streams"],
                finals[1]["processes"]["tool"]["streams"],
            )

    def test_failed_command_is_charged_terminal_and_not_retried(self):
        self.plan["tools"]["success"][-1] = "fail"
        trial = self.create()
        result = trial.execute("one")
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["processes"]["tool"]["returncode"], 7)
        self.assertIsNone(result["oracle"])
        with self.assertRaisesRegex(ValueError, "already consumed"):
            trial.execute("one")
        report = trial.report()
        self.assertEqual(report["trial"]["charged"], 1)
        self.assertEqual(report["trial"]["events"][-1]["kind"], "rejected")
        self.assertEqual(report["task_observation"]["unsubmitted_count"], 1)

    def test_timeout_preserves_real_effect_and_unknown_without_retry(self):
        self.plan["tools"]["success"][-1] = "sleep"
        self.plan["timeout_seconds"] = 0.2
        trial = self.create()
        result = trial.execute("one")
        self.assertEqual(result["outcome"], "unknown")
        self.assertTrue(result["processes"]["tool"]["timed_out"])
        self.assertIsNone(result["external_effects"])
        self.assertEqual(
            (trial.root / "attempts/one/output/effect").read_text(), "one action"
        )
        with self.assertRaises(ValueError):
            trial.execute("one")
        self.assertEqual(trial.report()["task_observation"]["outcomes"], {"unknown": 1})

    def test_original_oracle_false_is_a_failure_not_process_success(self):
        path = self.capsule / "oracle.py"
        path.write_text("print('{\"success\": false}')\n")
        self.plan["files"][path.name] = sha256(path.read_bytes())
        trial = self.create()
        self.assertEqual(trial.execute("one")["outcome"], "failed")

    def test_reopen_keeps_charged_pending_attempt_and_cannot_dispatch(self):
        trial = self.create()
        trial.ledger.claim("one")
        recovered = DevelopmentTrial(
            trial.root, expected_plan_sha256=trial.ledger.plan_sha256
        )
        with self.assertRaisesRegex(ValueError, "already consumed"):
            recovered.execute("one")
        self.assertFalse((trial.root / "attempts/one").exists())
        self.assertEqual(recovered.report()["trial"]["pending"], 1)

    def test_byte_drift_leaves_pending_and_retains_interruption(self):
        trial = self.create()
        (trial.root / "capsule/tool.py").write_text("raise SystemExit(0)\n")
        with self.assertRaisesRegex(ValueError, "byte mismatch"):
            trial.execute("one")
        self.assertEqual(trial.report()["trial"]["pending"], 1)
        self.assertEqual(trial.report()["task_observation"]["pending_count"], 1)
        self.assertTrue((trial.root / "attempts/one/INTERRUPTED.json").is_file())
        with self.assertRaisesRegex(ValueError, "already consumed"):
            trial.execute("one")

    def test_tool_cannot_replace_the_oracle_before_dispatch(self):
        path = self.capsule / "tool.py"
        original = (self.capsule / "oracle.py").read_text()
        replacement = (
            "from pathlib import Path\nPath(__file__).write_text("
            + repr(original)
            + ")\nPath('malicious-oracle-ran').touch()\nprint('{\"success\": true}')\n"
        )
        path.write_text(
            path.read_text()
            + "\n(output / 'answer.json').write_text('0')\npathlib.Path('oracle.py').write_text("
            + repr(replacement)
            + ")\n"
        )
        self.plan["files"][path.name] = sha256(path.read_bytes())
        trial = self.create()
        with self.assertRaisesRegex(ValueError, "byte mismatch"):
            trial.execute("one")
        self.assertFalse((trial.root / "attempts/one/oracle").exists())
        self.assertFalse(
            (trial.root / "attempts/one/work/malicious-oracle-ran").exists()
        )
        report = trial.report()
        self.assertEqual(report["trial"]["charged"], 1)
        self.assertEqual(report["trial"]["pending"], 1)
        with self.assertRaisesRegex(ValueError, "already consumed"):
            trial.execute("one")

    def test_original_process_streams_and_outputs_are_checked_on_readback(self):
        trial = self.create()
        trial.execute("one")
        for suffix, reason in (
            ("tool/stdout", "process stream"),
            ("output/answer.json", "tool outputs"),
        ):
            path = trial.root / "attempts/one" / suffix
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, reason):
                trial.report()
            path.write_bytes(original)
        self.assertEqual(trial.report()["task_observation"]["outcomes"], {"success": 1})

    def test_budget_rejections_remain_in_planned_denominator(self):
        self.plan["schedule"] += [
            dict(attempt_id=a + "_extra", task_id="task", arm=a, tool_id="success")
            for a in ("one", "two")
        ]
        trial = self.create()
        for arm in ("one", "two"):
            trial.execute(arm)
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                trial.execute(arm + "_extra")
        report = trial.report()
        self.assertEqual(report["trial"]["planned"], 4)
        self.assertEqual(report["trial"]["charged"], 2)
        self.assertEqual(report["task_observation"]["missing_final_count"], 2)
        self.assertEqual(
            len([e for e in report["trial"]["events"] if e["kind"] == "rejected"]), 2
        )

    def test_frozen_order_and_unscheduled_rejections_never_run_tool(self):
        self.plan["attempt_limit_per_arm"] = 2
        self.plan["schedule"] += [
            dict(attempt_id=a + "_extra", task_id="task", arm=a, tool_id="success")
            for a in ("one", "two")
        ]
        trial = self.create()
        for name, reason in (
            ("one_extra", "frozen arm order"),
            ("unknown", "unscheduled"),
        ):
            with self.assertRaisesRegex(ValueError, reason):
                trial.execute(name)
        self.assertEqual(trial.report()["trial"]["charged"], 0)
        self.assertEqual(list((trial.root / "attempts").iterdir()), [])

    def test_research_phases_and_unmatched_catalogs_are_refused(self):
        for phase in ("A", "B", "C", "D_cold"):
            plan = copy.deepcopy(self.plan)
            plan["tasks"]["task"]["phase"] = phase
            with self.assertRaisesRegex(ValueError, "research-phase"):
                validate_plan(plan)
        plan = copy.deepcopy(self.plan)
        plan["schedule"].pop()
        with self.assertRaisesRegex(ValueError, "same tasks"):
            validate_plan(plan)
        plan = copy.deepcopy(self.plan)
        plan["files"]["../escape.py"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "canonical"):
            validate_plan(plan)

    def test_terminal_artifact_and_plan_mutation_cannot_be_silently_accepted(self):
        trial = self.create()
        with self.assertRaisesRegex(ValueError, "externally retained digest"):
            TrialLedger(trial.root / "trial.sqlite", expected_plan_sha256="f" * 64)
        trial.execute("one")
        final = trial.root / "attempts/one/FINAL.json"
        original = final.read_bytes()
        final.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            trial.report()
        final.write_bytes(original)
        trial.plan["tools"]["success"][-1] = "fail"
        self.assertEqual(trial.execute("two")["outcome"], "success")
        self.assertEqual(trial.plan["tools"]["success"][-1], "success")

    def test_cold_observer_plan_must_match_frozen_trial_schedule(self):
        trial = self.create()
        path = trial.root / "tasks.sqlite"
        with sqlite3.connect(path) as db:
            plan = json.loads(db.execute("SELECT body FROM plan").fetchone()[0])
            plan["tasks"][0]["arm"] = "reassigned"
            db.execute(
                "UPDATE plan SET body=?",
                (json.dumps(plan, sort_keys=True, separators=(",", ":")),),
            )
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "plan.*digest|digest.*plan"):
            DevelopmentTrial(trial.root, expected_plan_sha256=trial.ledger.plan_sha256)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
