"""Source witnesses must observe the real checkout, without executing Git hooks."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_hepta_implementation_identity as fixtures


class GitObservationIsolationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing real-Git fixture, not its test suite or mock Git.
        self.fixture = fixtures.SourceIdentityTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.bind_objects()
        self.root = self.fixture.root
        self.subject = fixtures.subject
        self.identity = self.subject.current_source_base()

    def observe(self):
        self.assertEqual(self.subject.current_source_base(), self.identity)
        self.assertTrue(self.subject.verify_source_identity(self.fixture.row))

    def reject_changed_source(self):
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            self.subject.verify_source_identity(self.fixture.row)

    def test_ambient_repository_worktree_and_index_redirects_are_ignored(self):
        for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "/missing/git-identity"}):
                self.observe()

    def test_ambient_pathspec_modes_cannot_hide_a_dirty_source(self):
        for key in ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
                    "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "1"}):
                self.observe()
                self.fixture.write("owner/src/lib.rs", "changed\n")
                try:
                    self.reject_changed_source()
                finally:
                    self.fixture.write("owner/src/lib.rs", "pub fn run() {}\n")

    def test_config_environment_cannot_install_a_monitor(self):
        marker = self.root / "unexpected-monitor"
        with patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": f"touch {marker}",
        }):
            self.observe()
        self.assertFalse(marker.exists())

    def test_global_and_system_config_are_not_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "gitconfig"
            config.write_text("this is deliberately not Git config\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_SYSTEM": str(config),
            }):
                self.observe()

    def test_repository_monitor_is_disabled_without_executing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "executed"
            hook = Path(directory) / "monitor"
            hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n', encoding="utf-8")
            hook.chmod(0o700)
            self.fixture.git("config", "core.fsmonitor", str(hook))
            self.observe()
            self.fixture.write("owner/src/lib.rs", "changed\n")
            self.reject_changed_source()
            self.assertFalse(marker.exists())

    def test_replacement_commit_does_not_hide_real_source_drift(self):
        old = self.identity["commit"]
        self.fixture.write("owner/src/lib.rs", "pub fn changed() {}\n")
        current = self.fixture.commit()
        actual_tree = self.fixture.git("rev-parse", "HEAD^{tree}")
        self.fixture.git("replace", current, old)
        # Ordinary Git now sees the replacement; the verifier must not.
        self.assertEqual(self.fixture.git("rev-parse", "HEAD^{tree}"), self.identity["tree"])
        self.assertEqual(self.subject.current_source_base(), {"commit": current, "tree": actual_tree})
        self.reject_changed_source()

    def test_index_shortcuts_cannot_hide_a_dirty_witness(self):
        for flag, reset in (("--assume-unchanged", "--no-assume-unchanged"),
                            ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                self.fixture.git("update-index", flag, "owner/src/lib.rs")
                self.fixture.write("owner/src/lib.rs", "hidden mutation\n")
                self.assertEqual(self.fixture.git("diff", "--name-only"), "")
                try:
                    with self.assertRaisesRegex(ValueError, "opaque Git index flag"):
                        self.subject.verify_source_identity(self.fixture.row)
                finally:
                    self.fixture.git("update-index", reset, "owner/src/lib.rs")
                    self.fixture.write("owner/src/lib.rs", "pub fn run() {}\n")
                self.observe()

    def test_unrelated_index_shortcut_does_not_expand_validation_scope(self):
        self.fixture.write("other.txt", "not a mapped source\n")
        self.fixture.commit()
        self.fixture.git("update-index", "--skip-worktree", "other.txt")
        self.assertTrue(self.subject.verify_source_identity(self.fixture.row))


if __name__ == "__main__":
    unittest.main()
