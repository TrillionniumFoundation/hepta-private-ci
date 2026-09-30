#!/usr/bin/env python3
"""Hermetic tests for exact-tree receipts, not statistical or host acceptance."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_exact", Path(__file__).with_name("hepta-learning-eval-exact.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExactQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = Path.cwd()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, self.previous)
        for command in [
            ["git", "init", "-q", str(self.root)],
            ["git", "-C", str(self.root), "config", "user.name", "Receipt test"],
            ["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"],
        ]:
            subprocess.run(command, check=True)
        (self.root / "source.txt").write_text("immutable source\n")
        self.commit("initial")
        self.head = MODULE.git(self.root, "rev-parse", "HEAD")
        os.chdir(self.root)

    def commit(self, message):
        subprocess.run(["git", "-C", str(self.root), "add", "source.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", message], check=True)

    def run_main(self):
        return MODULE.main(["--source-commit", self.head, "--candidate-commit", self.head,
                            "--kind", "head"])

    def manifest(self):
        return json.loads((self.root / ".hepta-evidence/learning-eval/head/convergence.json").read_text())

    def test_head_requires_full_exact_clean_commit(self):
        MODULE.validate_checkout(self.root, self.head, self.head, None, "head")
        for source in [self.head[:8], "0" * 40]:
            with self.assertRaises(ValueError):
                MODULE.validate_checkout(self.root, source, self.head, None, "head")
        (self.root / "source.txt").write_text("dirty\n")
        with self.assertRaises(ValueError):
            MODULE.validate_checkout(self.root, self.head, self.head, None, "head")

    def test_merge_requires_exact_ordered_parents(self):
        base = self.head
        (self.root / "source.txt").write_text("candidate\n")
        self.commit("candidate")
        head = MODULE.git(self.root, "rev-parse", "HEAD")
        tree = MODULE.git(self.root, "rev-parse", "HEAD^{tree}")
        merge = MODULE.git(self.root, "commit-tree", tree, "-p", base, "-p", head, "-m", "merge")
        subprocess.run(["git", "checkout", "-q", "--detach", merge], check=True)
        result = MODULE.validate_checkout(self.root, merge, head, base, "merge")
        self.assertEqual(result["orderedParents"], [base, head])
        with self.assertRaises(ValueError):
            MODULE.validate_checkout(self.root, merge, base, head, "merge")

    def test_failed_command_retains_log_exit_code_and_skipped_status(self):
        commands = [
            ("failure", [sys.executable, "-c", "print('durable failure evidence'); raise SystemExit(7)"], "."),
            ("not-executed", [sys.executable, "-c", "raise SystemExit(0)"], "."),
        ]
        with mock.patch.object(MODULE, "commands", return_value=commands):
            self.assertEqual(self.run_main(), 1)
        value = self.manifest()
        first, second = value["commands"]
        self.assertEqual(first["exitCode"], 7)
        self.assertEqual(first["status"], "failed")
        self.assertEqual(second["status"], "not_run_after_failure")
        log = self.root / ".hepta-evidence/learning-eval/head" / first["log"]["path"]
        self.assertEqual(first["log"]["sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
        self.assertIn("durable failure evidence", log.read_text())
        self.assertFalse(value["claims"]["sourceQualifiedByThisRun"])

    def test_success_never_issues_external_acceptance(self):
        commands = [("check", [sys.executable, "-c", "print('source check')"], ".")]
        with mock.patch.object(MODULE, "commands", return_value=commands), \
                mock.patch.object(MODULE, "validate_outputs", return_value={"testFixture": True}):
            self.assertEqual(self.run_main(), 0)
        value = self.manifest()
        self.assertTrue(value["claims"]["sourceQualifiedByThisRun"])
        self.assertTrue(value["trackedSourceUnchanged"])
        self.assertEqual(value["authority"], "DENY_ALL")
        for key in ["targetHostQualified", "independentAcceptance", "activationAuthorized", "releaseAuthorized"]:
            self.assertFalse(value["claims"][key])

    def test_source_mutation_during_execution_cannot_qualify(self):
        commands = [("bad-command", [sys.executable, "-c",
                    "from pathlib import Path; Path('source.txt').write_text('changed')"], ".")]
        with mock.patch.object(MODULE, "commands", return_value=commands), \
                mock.patch.object(MODULE, "validate_outputs", return_value={}):
            self.assertEqual(self.run_main(), 1)
        value = self.manifest()
        self.assertFalse(value["claims"]["sourceQualifiedByThisRun"])
        self.assertTrue(any("dirty" in item for item in value["errors"]))

    def test_launch_error_is_not_exit_zero(self):
        output = self.root / "logs"
        output.mkdir()
        result = MODULE.execute("missing", ["/nonexistent/hepta-test-command"], self.root, output)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["exitCode"])
        self.assertIn("FileNotFoundError", result["error"])


if __name__ == "__main__":
    unittest.main()
