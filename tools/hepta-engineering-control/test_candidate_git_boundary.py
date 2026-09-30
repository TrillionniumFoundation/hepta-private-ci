"""Repository identity and streaming extraction resist ambient redirection."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from control_engineering_v2 import EngineeringError
from control_engineering_v2 import candidate
from control_engineering_v2.git_security import run_git, run_git_bytes
import test_candidate_sandbox_hardening as fixtures


class CandidateGitBoundaryTests(unittest.TestCase):
    setUp = fixtures.CandidateSandboxFixture.setUp
    tearDown = fixtures.CandidateSandboxFixture.tearDown
    _git = fixtures.CandidateSandboxFixture._git

    def test_ambient_git_directory_cannot_redirect_repository_reads(self):
        other = fixtures.CandidateSandboxFixture()
        other.setUp()
        try:
            (other.root / "src/base file.txt").write_text("other\n")
            other._git("add", ".")
            other._git("commit", "-q", "-m", "different repository")
            with patch.dict(
                os.environ,
                {"GIT_DIR": str(other.root / ".git"), "GIT_WORK_TREE": str(other.root)},
            ):
                for reader in (candidate._git, run_git):
                    self.assertEqual(reader(self.root, "rev-parse", "HEAD"), self.base_commit)
        finally:
            other.tearDown()

    def test_ambient_config_cannot_rebind_repository_evidence(self):
        self._git("config", "remote.origin.url", "https://github.com/owner/actual.git")
        with patch.dict(
            os.environ,
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "remote.origin.url",
                "GIT_CONFIG_VALUE_0": "https://github.com/attacker/other.git",
            },
        ):
            for reader in (candidate._git, run_git):
                self.assertEqual(
                    reader(self.root, "config", "--get", "remote.origin.url"),
                    "https://github.com/owner/actual.git",
                )

    @unittest.skipUnless(os.name == "posix", "Git fsmonitor fixture uses a shell")
    def test_local_fsmonitor_cannot_execute_during_evidence_reads(self):
        marker = self.root / ".git/monitor-entered"
        helper = self.root / ".git/monitor-helper"
        helper.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        helper.chmod(0o700)
        self._git("config", "core.fsmonitor", str(helper))
        run_git(self.root, "status", "--porcelain")
        self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "Git extraction uses POSIX process groups")
    def test_stalled_cat_file_header_is_bounded_before_wait(self):
        popen = subprocess.Popen
        children = []

        def stalled(*args, **kwargs):
            process = popen(
                [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                **kwargs,
            )
            children.append(process)
            return process

        destination = Path(self.temporary.name) / "stalled"
        started = time.monotonic()
        with (
            patch.object(candidate, "_git_tree_entries", return_value=(("100644", "blob", "a" * 40, "src/a.py"),)),
            patch.object(candidate.subprocess, "Popen", side_effect=stalled),
        ):
            with self.assertRaisesRegex(EngineeringError, "git_operation_failed"):
                candidate._materialize_exact_tree(
                    self.root, self.base_commit, destination, timeout_seconds=0.1
                )
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(all(process.poll() is not None for process in children))

    def test_git_output_limit_is_enforced_while_child_is_still_running(self):
        popen = subprocess.Popen
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                children = []

                def overflow(*args, **kwargs):
                    process = popen(
                        [sys.executable, "-I", "-c", f"import sys,time; sys.{stream}.write('x'*4096); sys.{stream}.flush(); time.sleep(30)"],
                        **kwargs,
                    )
                    children.append(process)
                    return process

                started = time.monotonic()
                with patch.object(candidate.subprocess, "Popen", side_effect=overflow):
                    with self.assertRaisesRegex(EngineeringError, "git_read_failed"):
                        run_git_bytes(self.root, "rev-parse", "HEAD", maximum_output_bytes=1024)
                self.assertLess(time.monotonic() - started, 3)
                self.assertTrue(all(process.poll() is not None for process in children))

    def test_oversized_git_symlink_blob_is_rejected_before_decoding(self):
        oid = subprocess.run(
            ["git", "-C", str(self.root), "hash-object", "-w", "--stdin"],
            input=b"x" * 4097, capture_output=True, check=True,
        ).stdout.decode().strip()
        self._git("update-index", "--add", "--cacheinfo", f"120000,{oid},src/link")
        self._git("commit", "-q", "-m", "oversized symlink blob")
        base = self._git("rev-parse", "HEAD").stdout.strip()
        with self.assertRaisesRegex(EngineeringError, "sandbox_path_escape"):
            candidate._materialize_exact_tree(self.root, base, Path(self.temporary.name) / "large-link")

    def test_existing_mutation_text_is_bounded_before_oracle_and_replacement_reads(self):
        target = self.root / "src/base file.txt"
        target.write_bytes(b"base\n" + b"x" * candidate.MAX_TEXT_DIFF_BYTES)
        mutation = candidate.Mutation("replace_text", "src/base file.txt", "base\n", "next\n")
        for operation in (candidate._reject_inline_oracle_mutation, candidate._apply_mutation):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(EngineeringError, "diff_limit_exceeded"):
                    operation(self.root, mutation)
        # The bounded read also protects growth after the size preflight.
        with patch.object(candidate.Path, "stat", return_value=SimpleNamespace(st_size=0)):
            with self.assertRaisesRegex(EngineeringError, "diff_limit_exceeded"):
                candidate._read_mutation_text(target)

    def test_ordinary_commit_and_split_calls_do_not_block_production_changes(self):
        source = self.root / "src/production.py"
        source.write_text("def commit():\n    return 'base'.split(',')\n")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "ordinary production functions")
        self.base_commit = self._git("rev-parse", "HEAD").stdout.strip()
        envelope = fixtures.CandidateSandboxFixture.envelope(self)
        value = candidate.generate_candidates(
            envelope, (candidate.Mutation("replace_text", "src/production.py", "'base'", "'next'"),)
        )[1]
        tested, receipt = candidate.sandbox_candidate(
            self.root, envelope, value,
            ((sys.executable, "-I", "-c", "from pathlib import Path; assert \"'next'.split\" in Path('src/production.py').read_text()"),),
        )
        self.assertEqual(tested.state, "fixture_tested")
        self.assertTrue(receipt.passed)

    def test_spaced_inline_test_syntax_cannot_weaken_oracle(self):
        for text in ("# [ test ]\nfn check() {}", "#[cfg ( test )]\nmod checks {}", "#[tokio :: test]\nasync fn check() {}", "#[tokio::test(flavor = \"current_thread\")]\nasync fn check() {}", "describe ('behavior', f)", "it ('behavior', f)", "TEST_F (Suite, Check) {}"):
            with self.subTest(text=text):
                (self.root / "src/base file.txt").write_text(text)
                with self.assertRaisesRegex(EngineeringError, "candidate_oracle_path"):
                    candidate._reject_inline_oracle_mutation(
                        self.root, candidate.Mutation("delete_file", "src/base file.txt")
                    )


if __name__ == "__main__":
    unittest.main()
