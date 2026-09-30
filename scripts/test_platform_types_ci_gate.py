#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("platform_types_ci_gate.py")


class PlatformTypesCiGateTest(unittest.TestCase):
    def run_script(self, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
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


if __name__ == "__main__":
    unittest.main()
