#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import platform_types_ci_gate as gate_module

SCRIPT = Path(__file__).with_name("platform_types_ci_gate.py")


class PlatformTypesCiGateTest(unittest.TestCase):
    def run_script(
        self, *arguments: str, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_failed_gate_is_recorded_before_summary_asserts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            run = self.run_script(
                "run",
                "--name",
                "failing",
                "--evidence-root",
                str(evidence),
                "--",
                sys.executable,
                "-c",
                "import sys; print('diagnostic', file=sys.stderr); raise SystemExit(7)",
                cwd=root,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            gate = json.loads((evidence / "gates" / "failing.json").read_text())
            self.assertEqual(gate["exitCode"], 7)
            self.assertEqual(gate["status"], "failed")
            self.assertIn("diagnostic", gate["stderrSummary"])
            self.assertTrue((evidence / gate["generatedDiff"]).is_file())

            summary = self.run_script(
                "summary",
                "--evidence-root",
                str(evidence),
                "--candidate-kind",
                "source-head",
                "--required",
                "failing",
                cwd=root,
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            assertion = self.run_script(
                "assert",
                "--summary",
                str(evidence / "qualification-summary.json"),
                cwd=root,
            )
            self.assertEqual(assertion.returncode, 1)

    def test_passing_required_gate_yields_passing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            run = self.run_script(
                "run",
                "--name",
                "passing",
                "--evidence-root",
                str(evidence),
                "--",
                sys.executable,
                "-c",
                "print('ok')",
                cwd=root,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = self.run_script(
                "summary",
                "--evidence-root",
                str(evidence),
                "--candidate-kind",
                "synthetic-merge",
                "--required",
                "passing",
                cwd=root,
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            assertion = self.run_script(
                "assert",
                "--summary",
                str(evidence / "qualification-summary.json"),
                cwd=root,
            )
            self.assertEqual(assertion.returncode, 0, assertion.stderr)

    def test_missing_required_gate_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            summary = self.run_script(
                "summary",
                "--evidence-root",
                str(evidence),
                "--candidate-kind",
                "source-head",
                "--required",
                "schema",
                cwd=root,
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            payload = json.loads((evidence / "qualification-summary.json").read_text())
            self.assertEqual(payload["failureReasons"], ["missing:schema"])


class GateEvidenceIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = {"checkedOutCommit": "a" * 40, "sourceSha": "a" * 40}
        self.runner = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        self.gate = {
            "schema": gate_module.GATE_SCHEMA,
            "gate": "schema",
            "required": True,
            "status": "passed",
            "exitCode": 0,
            "launchError": None,
            "candidateAtStart": self.candidate.copy(),
            "candidateAtCompletion": self.candidate.copy(),
            "runner": self.runner.copy(),
        }

    def summarize(self, gates, required=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "gates").mkdir()
            for index, record in enumerate(gates):
                (root / "gates" / f"{index}.json").write_text(json.dumps(record))
            with (
                patch.object(
                    gate_module, "_candidate_identity", return_value=self.candidate
                ),
                patch.object(gate_module, "_runner_identity", return_value=self.runner),
            ):
                gate_module.build_summary(
                    argparse.Namespace(
                        evidence_root=str(root),
                        candidate_kind="source-head",
                        required=["schema"] if required is None else required,
                        output=None,
                    )
                )
            return json.loads((root / "qualification-summary.json").read_text())

    def test_workflow_required_gate_cannot_be_downgraded_to_optional(self):
        self.gate.update(required=False, status="failed", exitCode=7)
        self.assertEqual(self.summarize([self.gate])["status"], "failed")
        self.assertEqual(self.summarize([self.gate], required=[])["status"], "passed")

    def test_stale_or_changed_candidate_records_fail(self):
        for field in ("candidateAtStart", "candidateAtCompletion"):
            with self.subTest(field=field):
                record = copy.deepcopy(self.gate)
                record[field]["checkedOutCommit"] = "b" * 40
                self.assertIn(
                    "candidate_mismatch:schema",
                    self.summarize([record])["failureReasons"],
                )

    def test_different_run_attempt_fails(self):
        self.gate["runner"]["GITHUB_RUN_ATTEMPT"] = "2"
        self.assertIn(
            "runner_mismatch:schema", self.summarize([self.gate])["failureReasons"]
        )

    def test_duplicate_gate_records_fail(self):
        self.assertIn(
            "duplicate:schema", self.summarize([self.gate, self.gate])["failureReasons"]
        )

    def test_passed_label_cannot_hide_failure_exit_code(self):
        for exit_code in (7, False, "0", None):
            with self.subTest(exit_code=exit_code):
                self.gate["exitCode"] = exit_code
                self.assertEqual(self.summarize([self.gate])["status"], "failed")

    def test_assert_revalidates_records_and_current_candidate(self):
        summary = self.summarize([self.gate])
        self.assertEqual(summary["status"], "passed")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "summary.json"
            with (
                patch.object(
                    gate_module, "_candidate_identity", return_value=self.candidate
                ),
                patch.object(gate_module, "_runner_identity", return_value=self.runner),
            ):
                path.write_text(json.dumps(summary))
                args = argparse.Namespace(summary=str(path))
                self.assertEqual(gate_module.assert_summary(args), 0)
                summary["gates"][0]["exitCode"] = 7
                path.write_text(json.dumps(summary))
                self.assertEqual(gate_module.assert_summary(args), 1)
                summary["gates"][0]["exitCode"] = 0
                path.write_text(json.dumps(summary))
                self.candidate["checkedOutCommit"] = "b" * 40
                self.assertEqual(gate_module.assert_summary(args), 1)

    def test_tail_reads_only_the_bounded_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "stderr.log"
            path.write_bytes(b"x" * 100_000 + b"\nlast line\n")
            with patch.object(
                Path, "read_bytes", side_effect=AssertionError("unbounded read")
            ):
                self.assertEqual(
                    gate_module._tail(path, maximum_lines=1, maximum_bytes=32),
                    "last line",
                )


if __name__ == "__main__":
    unittest.main()
