"""Actual Git counterexamples at both preflight and command entry.

The child marker proves whether a command ran. No mocked passing native receipt
or execution of a repository-provided fsmonitor is accepted as qualification.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import unittest

import test_hepta_ci_exec as fixtures

SPEC = importlib.util.spec_from_file_location(
    "candidate_isolation_subject", Path(__file__).with_name("hepta_ci_candidate.py")
)
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class SourceIsolationTests(fixtures.GitExecutionFixture):
    def plan(self, **environment):
        old = Path.cwd()
        try:
            os.chdir(self.repo)
            with patch.dict(os.environ, environment):
                return candidate.candidate_plan(source=self.source, tested=self.source,
                                                lane="source-head")
        finally:
            os.chdir(old)

    def rejected(self, **environment):
        self.result.unlink(missing_ok=True)
        result = self.execute(**environment)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.receipt()["status"], "rejected")
        with self.assertRaises((ValueError, subprocess.SubprocessError)):
            self.plan(**environment)

    def test_index_shortcuts_cannot_hide_mutated_bytes(self):
        for enable, disable in (("--assume-unchanged", "--no-assume-unchanged"),
                                ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(enable=enable):
                self.git("update-index", enable, "input")
                (self.repo / "input").write_text("hidden mutation\n")
                self.assertEqual(self.git("status", "--porcelain"), "")
                try:
                    self.rejected()
                    self.assertNotEqual(self.git("ls-files", "-v", "input")[:1], "H")
                finally:
                    self.git("update-index", disable, "input")
                    (self.repo / "input").write_text("base\n")

    def test_index_shortcuts_are_not_authorized_even_when_bytes_match(self):
        self.git("update-index", "--skip-worktree", "input")
        self.rejected()

    def test_replaced_commit_cannot_change_the_recorded_tree(self):
        (self.repo / "input").write_text("replacement contents\n")
        self.git("commit", "-qam", "different bytes")
        actual = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("replace", actual, self.source)
        self.source = actual
        self.assertNotEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
        self.rejected()
        self.assertEqual(candidate.git("-C", str(self.repo), "rev-parse", "HEAD^{tree}"), tree)

    def test_repository_redirection_is_rejected_before_dispatch(self):
        # A clean index from elsewhere must not describe bytes compiled here.
        for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            with self.subTest(key=key):
                self.rejected(**{key: str(self.repo / ".git")})

    def test_repository_fsmonitor_is_not_executed_by_an_observer(self):
        monitor = self.root / "monitor"
        monitor.write_text(f'#!/bin/sh\ntouch "{self.marker}"\nprintf "ignored\\0"\n')
        monitor.chmod(0o700)
        self.git("config", "core.fsmonitor", str(monitor))
        result = self.execute("pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.marker.exists())
        self.plan()
        self.assertFalse(self.marker.exists())

    def test_hidden_index_cannot_appear_during_a_successful_command(self):
        # The actual command exits zero; the final identity must still reject it.
        result = self.execute("import subprocess; from pathlib import Path; "
                              "subprocess.run(['git','update-index','--assume-unchanged','input'],check=True); "
                              "Path('input').write_text('hidden after execution')")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.receipt()["status"], "failed")
        self.assertEqual(self.receipt()["command_exit_code"], 0)

    def test_monitor_environment_never_enters_the_test_command(self):
        self.rejected(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.fsmonitor",
                      GIT_CONFIG_VALUE_0=f"touch {self.marker}")


if __name__ == "__main__":
    unittest.main()
