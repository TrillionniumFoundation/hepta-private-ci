#!/usr/bin/env python3
"""Real Git identity and nextest-output regressions for the diagnostic runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).with_name("hepta-learning-artifacts-qualification.py")
SPEC = importlib.util.spec_from_file_location("learning_artifact_qualification", SOURCE)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class CheckoutIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = mock.patch.object(qualification, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.git("init", "-q")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("config", "user.name", "Qualification fixture")
        self.git("config", "user.email", "fixture@invalid.example")
        (self.root / "payload.txt").write_text("base bytes\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "source.txt").write_text("source bytes\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture source")
        self.source = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE
        ).strip()

    def identity(self, lane: str = "source") -> dict:
        return qualification.materialize_candidate(self.source, self.base, lane)

    def test_source_checkout_identity_is_accepted(self) -> None:
        qualification.verify_checkout_identity(self.identity(), self.source)

    def test_another_commit_with_identical_tree_is_rejected(self) -> None:
        identity = self.identity()
        self.git("commit", "--allow-empty", "-qm", "Same tree, different commit")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), identity["candidateTree"])
        with self.assertRaisesRegex(ValueError, "checkout commit"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_dirty_tracked_source_is_rejected(self) -> None:
        identity = self.identity()
        (self.root / "payload.txt").write_text("changed bytes\n")
        with self.assertRaisesRegex(ValueError, "dirty tracked"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_altered_parent_list_is_rejected(self) -> None:
        identity = self.identity()
        identity["parents"] = []
        with self.assertRaisesRegex(ValueError, "candidate parents"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_source_tree_mismatch_is_rejected(self) -> None:
        identity = self.identity()
        identity["sourceTree"] = self.git("rev-parse", f"{self.base}^{{tree}}")
        with self.assertRaisesRegex(ValueError, "source tree"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_ordered_merge_identity_is_accepted(self) -> None:
        identity = self.identity("merge")
        self.assertEqual(identity["parents"], [self.base, self.source])
        qualification.verify_checkout_identity(identity, self.source)

    def test_changed_merge_parent_order_is_rejected(self) -> None:
        identity = self.identity("merge")
        identity["parents"] = [self.source, self.base]
        with self.assertRaisesRegex(ValueError, "candidate parents"):
            qualification.verify_checkout_identity(identity, self.source)

    def test_replace_refs_do_not_change_selected_git_identity(self) -> None:
        source_tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("replace", self.source, self.base)
        identity = self.identity()
        self.assertEqual(identity["candidateTree"], source_tree)
        self.assertEqual(identity["sourceTree"], source_tree)
        qualification.verify_checkout_identity(identity, self.source)


class NextestOutputTests(unittest.TestCase):
    def test_counter_and_legacy_pass_lines_bind_the_same_test(self) -> None:
        legacy = "PASS [   0.032s] codex-app-server tests::completed\n"
        counter = "PASS [   0.032s] (   1/7539) codex-app-server tests::completed\n"
        expected = [{"binary": "codex-app-server", "function": "tests::completed"}]
        self.assertEqual(qualification.passed_tests(legacy), expected)
        self.assertEqual(qualification.passed_tests(counter), expected)
        self.assertEqual(qualification.passed_tests(legacy + counter), expected)

    def test_failed_skipped_and_malformed_lines_are_not_passes(self) -> None:
        text = (
            "FAIL [0.032s] (1/3) package tests::failed\n"
            "SKIP [0.032s] package tests::skipped\n"
            "PASS [0.032s] (unknown/3) package tests::unknown\n"
            "PASS [0.032s] package tests::one extra-token\n"
        )
        self.assertEqual(qualification.passed_tests(text), [])


if __name__ == "__main__":
    unittest.main()
