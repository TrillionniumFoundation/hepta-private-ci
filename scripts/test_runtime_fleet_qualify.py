"""Actual Git-object regressions; no Rust/toolchain dependency or network."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime_fleet_qualify import CandidateInvalid, digest, git, qualify, run_logged, validate_candidate


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        (self.root / "scripts").mkdir()
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / "scripts/runtime_fleet_qualify.py").write_text("# fixture\n")
        (self.root / ".github/workflows/runtime-fleet-focused.yml").write_text("# fixture\n")
        self.base = self.commit_file("base", "base\n")
        self.source = self.commit_file("source", "source\n")
        self.output = Path(self.temporary.name) / "evidence"

    def commit_file(self, name, value):
        (self.root / name).write_text(value)
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", name)
        return git(self.root, "rev-parse", "HEAD")

    def merge(self, tree=None, parents=None):
        tree = tree or git(self.root, "merge-tree", "--write-tree", self.base, self.source)
        args = ["commit-tree", tree]
        for parent in parents or [self.base, self.source]:
            args += ["-p", parent]
        result = git(self.root, *args, "-m", "synthetic fixture")
        git(self.root, "checkout", "--detach", "-q", result)
        return result

    def run_qualify(self, kind="exact-source", commands=None):
        if commands is None:
            commands = [("fixture", self.root, [sys.executable, "-c", "print('fixture passed')"])]
        with patch("runtime_fleet_qualify.qualification_commands", return_value=commands):
            with redirect_stdout(io.StringIO()):
                code = qualify(self.root, self.output, kind, self.source, self.base)
        return code, json.loads((self.output / "receipt.json").read_text())

    def test_exact_source(self):
        value = validate_candidate(self.root, "exact-source", self.source, self.base)
        self.assertEqual(value["tested_commit"], self.source)

    def test_real_merge(self):
        self.merge()
        value = validate_candidate(self.root, "synthetic-merge", self.source, self.base)
        self.assertEqual(value["tested_tree"], value["expected_merge_tree"])

    def test_correct_parents_with_wrong_tree_are_rejected(self):
        self.merge(tree=git(self.root, "rev-parse", f"{self.base}^{{tree}}"))
        with self.assertRaisesRegex(CandidateInvalid, "content differs"):
            validate_candidate(self.root, "synthetic-merge", self.source, self.base)

    def test_wrong_parent_order_is_rejected(self):
        self.merge(parents=[self.source, self.base])
        with self.assertRaisesRegex(CandidateInvalid, "parents"):
            validate_candidate(self.root, "synthetic-merge", self.source, self.base)

    def test_tracked_dirty_entry_is_rejected(self):
        (self.root / "source").write_text("changed\n")
        with self.assertRaisesRegex(CandidateInvalid, "clean"):
            validate_candidate(self.root, "exact-source", self.source, self.base)

    def test_untracked_entry_is_rejected(self):
        (self.root / "new-file").write_text("untracked\n")
        with self.assertRaisesRegex(CandidateInvalid, "clean"):
            validate_candidate(self.root, "exact-source", self.source, self.base)

    def test_staged_entry_is_rejected(self):
        (self.root / "source").write_text("staged\n")
        git(self.root, "add", ".")
        with self.assertRaisesRegex(CandidateInvalid, "clean"):
            validate_candidate(self.root, "exact-source", self.source, self.base)

    def test_floating_ref_is_rejected(self):
        with self.assertRaisesRegex(CandidateInvalid, "immutable"):
            validate_candidate(self.root, "exact-source", "HEAD", self.base)

    def test_preflight_failure_still_has_failed_receipt(self):
        (self.root / "source").write_text("dirty\n")
        code, receipt = self.run_qualify()
        self.assertEqual(code, 1)
        self.assertEqual(receipt["outcome"], "candidate_invalid")
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["commands"], [])
        self.assertIn(digest(self.output / "receipt.json"), (self.output / "receipt.sha256").read_text())

    def test_zero_exit_does_not_hide_mutation(self):
        code, receipt = self.run_qualify(commands=[("mutator", self.root, [sys.executable, "-c", "from pathlib import Path; Path('source').write_text('changed')"])])
        self.assertEqual(receipt["commands"][0]["exit_code"], 0)
        self.assertEqual(code, 1)
        self.assertEqual(receipt["outcome"], "candidate_invalid")
        self.assertFalse(receipt["passed"])

    def test_nonzero_command_has_failed_receipt(self):
        code, receipt = self.run_qualify(commands=[("fail", self.root, [sys.executable, "-c", "raise SystemExit(3)"])])
        self.assertEqual(code, 1)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(receipt["commands"][0]["exit_code"], 3)

    def test_missing_program_is_infrastructure_invalid(self):
        code, receipt = self.run_qualify(commands=[("missing", self.root, [str(self.root / "no-such-program")])])
        self.assertEqual(code, 1)
        self.assertEqual(receipt["outcome"], "infrastructure_invalid")
        self.assertFalse(receipt["passed"])

    def test_success_binds_logs_archive_and_checkout(self):
        code, receipt = self.run_qualify()
        self.assertEqual(code, 0)
        self.assertTrue(receipt["entry_candidate_validated"])
        self.assertTrue(receipt["exit_candidate_validated"])
        self.assertEqual(receipt["source_archive_sha256"], digest(self.output / "runtime-fleet-source.tgz"))
        self.assertEqual(receipt["commands"][0]["log_sha256"], digest(self.output / "fixture.log"))
        self.assertFalse(receipt["product_deployment"])
        self.assertFalse(receipt["independent_acceptance"])

    def test_no_reuse_of_previous_attempt(self):
        self.output.mkdir()
        (self.output / "old.log").write_text("old")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.run_qualify()
        self.assertEqual((self.output / "old.log").read_text(), "old")

    def test_no_evidence_inside_candidate(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            qualify(self.root, self.root / "evidence", "exact-source", self.source, self.base)

    @unittest.skipUnless(os.name == "posix", "POSIX process groups")
    def test_timeout_is_invalid_and_parent_is_reaped(self):
        log = Path(self.temporary.name) / "timeout.log"
        code, invalid = run_logged([sys.executable, "-c", "import time; time.sleep(60)"], self.root, log, timeout=0.05)
        self.assertEqual(code, 124)
        self.assertTrue(invalid)
        self.assertIn("child group terminated", log.read_text())


if __name__ == "__main__":
    unittest.main()
