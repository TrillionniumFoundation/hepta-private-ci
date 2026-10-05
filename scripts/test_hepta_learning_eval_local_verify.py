#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_local_verify",
    Path(__file__).with_name("hepta-learning-eval-local-verify.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

COMMIT = "1" * 40
TREE = "2" * 40


class LocalDeterministicVerifierTests(unittest.TestCase):
    def test_source_identity_requires_exact_clean_commit(self):
        values = iter([COMMIT, TREE, ""])
        with mock.patch.object(MODULE, "git", side_effect=lambda *args: next(values)):
            self.assertEqual(
                MODULE.source_identity(Path("."), COMMIT),
                {"commit": COMMIT, "tree": TREE},
            )

        values = iter([COMMIT, TREE, " M tracked.rs"])
        with mock.patch.object(MODULE, "git", side_effect=lambda *args: next(values)):
            with self.assertRaisesRegex(ValueError, "dirty"):
                MODULE.source_identity(Path("."), COMMIT)

        values = iter([COMMIT, TREE])
        with mock.patch.object(MODULE, "git", side_effect=lambda *args: next(values)):
            with self.assertRaisesRegex(ValueError, "requested"):
                MODULE.source_identity(Path("."), "9" * 40)

    def test_execute_retains_failure_log_and_exit_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = MODULE.execute(
                "failure",
                [
                    __import__("sys").executable,
                    "-c",
                    "print('durable local failure'); raise SystemExit(7)",
                ],
                output,
                output,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["exitCode"], 7)
            log = output / result["log"]["path"]
            self.assertIn("durable local failure", log.read_text())
            self.assertEqual(result["log"]["sha256"], MODULE.digest_file(log))

    def test_execute_launch_error_is_not_exit_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = MODULE.execute(
                "missing",
                ["/nonexistent/hepta-local-command"],
                output,
                output,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["exitCode"])
            self.assertIn("FileNotFoundError", result["error"])

    def test_summary_is_scoped_and_fail_closed(self):
        passed = [
            {
                "name": "check",
                "status": "passed",
                "exitCode": 0,
            }
        ]
        value = MODULE.build_summary(
            {"commit": COMMIT, "tree": TREE},
            passed,
            "2026-09-30T00:00:00Z",
            "2026-09-30T00:00:01Z",
        )
        self.assertTrue(
            value["claims"]["localDeterministicVerifiedByThisRun"]
        )
        self.assertEqual(value["authority"], "DENY_ALL")
        self.assertEqual(value["releasePosture"], "NO_GO")
        for name in (
            "exactHeadExecuted",
            "orderedParentSyntheticMergeExecuted",
            "targetHostQualified",
            "independentAcceptanceIssued",
            "activationAuthorized",
            "releaseAuthorized",
        ):
            self.assertFalse(value["claims"][name])

        failed = [dict(passed[0], status="failed", exitCode=1)]
        value = MODULE.build_summary(
            {"commit": COMMIT, "tree": TREE},
            failed,
            "2026-09-30T00:00:00Z",
            "2026-09-30T00:00:01Z",
        )
        self.assertFalse(
            value["claims"]["localDeterministicVerifiedByThisRun"]
        )

    def test_summary_digest_detects_tampering(self):
        value = MODULE.build_summary(
            {"commit": COMMIT, "tree": TREE},
            [{"name": "check", "status": "passed", "exitCode": 0}],
            "2026-09-30T00:00:00Z",
            "2026-09-30T00:00:01Z",
        )
        value["commands"][0]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "claim/result mismatch|digest mismatch"):
            MODULE.validate_summary(value)

    def test_repository_projects_local_deterministic_contract(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / ".git").is_dir():
            self.skipTest("repository checkout is not mounted in this unit-test sandbox")
        docs = root / "docs/modules/learning.eval"
        contract = docs / "LOCAL_DETERMINISTIC_VERIFICATION.md"
        self.assertTrue(contract.is_file())
        audit = (docs / "AUDIT_INDEX.md").read_text(encoding="utf-8")
        self.assertIn(contract.name, audit)
        matrix = json.loads((docs / "QUALIFICATION_MATRIX.json").read_text())
        self.assertEqual(matrix["authority"], "DENY_ALL")
        self.assertEqual(matrix["releasePosture"], "NO_GO")
        self.assertEqual(matrix["sourceFacts"]["trustedReporterRegressionCount"], 60)
        for value in matrix["externalClaims"].values():
            self.assertIs(value, False)

    def test_python_source_inventory_requires_hardened_entry_and_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            required = (
                "hepta-learning-eval-trusted-entry.py",
                "test_hepta_learning_eval_trusted_entry.py",
                "hepta-learning-eval-local-verify.py",
                "test_hepta_learning_eval_local_verify.py",
                "test_hepta_learning_eval_trusted_report.py",
                "test_hepta_learning_eval_trusted_report_base.py",
            )
            for name in required:
                (scripts / name).write_text("# fixture\n", encoding="utf-8")
            (scripts / "hepta-nextest-require.py").write_text("# fixture\n")
            (scripts / "test_hepta_nextest_require.py").write_text("# fixture\n")
            inventory = MODULE.python_sources(root)
            for name in required:
                self.assertIn(f"scripts/{name}", inventory)
            (scripts / required[0]).unlink()
            with self.assertRaisesRegex(ValueError, "incomplete"):
                MODULE.python_sources(root)


if __name__ == "__main__":
    unittest.main()
