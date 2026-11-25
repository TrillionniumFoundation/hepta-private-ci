"""Real Git identity attacks against the existing CI command/receipt owner.

These are quiescent local checkout controls, not a sandbox, concurrent build
attestation, cryptographic work qualification, or an external acceptance claim.
"""

import os
import shlex
import subprocess
import sys
from unittest.mock import patch

from hepta_ci_exec import worktree_blobs_match
from test_hepta_ci_exec import GitExecutionFixture


class HiddenSourceIdentityTests(GitExecutionFixture):
    def test_raw_source_check_from_nested_directory_still_covers_whole_tree(self):
        nested = self.repo / "nested"
        nested.mkdir()
        (nested / "source").write_text("nested source")
        self.git("add", "nested")
        self.git("commit", "-qm", "nested source")
        self.assertTrue(worktree_blobs_match(repository=nested))
        (self.repo / "input").write_text("evil\n")
        self.assertFalse(worktree_blobs_match(repository=nested))

    def test_raw_blobs_reject_filter_masked_edits_without_executing_filter(self):
        (self.repo / ".gitattributes").write_text("input filter=mask\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-qm", "declare filter")
        self.source = self.git("rev-parse", "HEAD")
        marker = self.root / "filter-effect"
        program = self.root / "filter.py"
        program.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\nprint('base')\n"
        )
        self.git(
            "config", "filter.mask.clean", shlex.join([sys.executable, str(program)])
        )
        (self.repo / "input").write_text("evil\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertTrue(marker.exists())
        marker.unlink()
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(self.marker.exists())

    def test_raw_symlink_blob_binds_link_text(self):
        link = self.repo / "link"
        link.symlink_to("input")
        self.git("add", "link")
        self.git("commit", "-qm", "source symlink")
        self.source = self.git("rev-parse", "HEAD")
        self.assertEqual(self.execute().returncode, 0)
        self.result.unlink()
        self.marker.unlink()
        link.unlink()
        link.symlink_to("other")
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())

    def test_raw_file_hash_reads_bounded_chunks_and_rejects_shorter_file(self):
        large = self.repo / "large"
        large.write_bytes(b"z" * 200_000)
        self.git("add", "large")
        self.git("commit", "-qm", "streamed source")
        original = os.fdopen
        sizes = []

        class Reader:
            def __init__(self, descriptor, mode):
                self.stream = original(descriptor, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def fileno(self):
                return self.stream.fileno()

            def read(self, size):
                sizes.append(size)
                return self.stream.read(size)

        with patch("hepta_ci_exec.os.fdopen", Reader):
            self.assertTrue(worktree_blobs_match(repository=self.repo))
        self.assertGreaterEqual(sizes.count(65536), 3)
        self.assertTrue(all(0 < size <= 65536 for size in sizes))
        large.write_bytes(b"z")
        self.assertFalse(worktree_blobs_match(repository=self.repo))

    def test_local_stat_policy_cannot_hide_same_size_restored_mtime_change(self):
        source = self.repo / "input"
        # Make the original stat record older than the index, avoiding Git's
        # racy-clean fallback so the weak local policy really hides this edit.
        os.utime(source, (1_600_000_000, 1_600_000_000))
        self.git("add", "input")
        before = source.stat()
        self.git("config", "core.trustctime", "false")
        self.git("config", "core.checkstat", "minimal")
        source.write_text("evil\n")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("ls-files", "-v"), "H input")
        index = (self.repo / ".git/index").read_bytes()
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.receipt()["status"], "rejected")
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual(self.git("config", "core.trustctime"), "false")
        self.assertEqual(self.git("config", "core.checkstat"), "minimal")

    def hidden_before(self, flag):
        self.git("update-index", flag, "input")
        (self.repo / "input").write_text("unreviewed replacement\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        index = (self.repo / ".git/index").read_bytes()
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "rejected")
        self.assertTrue(receipt["before"]["dirty"])
        self.assertIsNone(receipt["command_exit_code"])
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)

    def test_assume_unchanged_cannot_dispatch_changed_source(self):
        self.hidden_before("--assume-unchanged")

    def test_skip_worktree_cannot_dispatch_changed_source(self):
        self.hidden_before("--skip-worktree")

    def test_hidden_unchanged_paths_are_refused_without_clearing_user_flags(self):
        for flag, undo in (
            ("--assume-unchanged", "--no-assume-unchanged"),
            ("--skip-worktree", "--no-skip-worktree"),
        ):
            with self.subTest(flag=flag):
                self.git("update-index", flag, "input")
                before = (self.repo / ".git/index").read_bytes()
                result = self.execute()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.marker.exists())
                self.assertEqual((self.repo / ".git/index").read_bytes(), before)
                self.assertTrue(self.receipt()["before"]["dirty"])
                self.git("update-index", undo, "input")
                self.result.unlink()

    def hidden_after(self, flag, code):
        command = (
            "import subprocess\nfrom pathlib import Path\n"
            f"subprocess.run(['git','update-index',{flag!r},'input'],check=True)\n"
            "Path('input').write_text('hidden after execution\\n')\n"
            f"raise SystemExit({code})\n"
        )
        result = self.execute(command)
        self.assertEqual(result.returncode, code or 1, result.stdout + result.stderr)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["command_exit_code"], code)
        self.assertFalse(receipt["before"]["dirty"])
        self.assertTrue(receipt["after"]["dirty"])
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_success_cannot_hide_post_command_drift_with_assume_unchanged(self):
        self.hidden_after("--assume-unchanged", 0)

    def test_success_cannot_hide_post_command_drift_with_skip_worktree(self):
        self.hidden_after("--skip-worktree", 0)

    def test_hidden_drift_retains_original_nonzero_command_exit(self):
        self.hidden_after("--assume-unchanged", 23)

    def test_nul_index_records_keep_newline_and_tab_paths_unambiguous(self):
        path = "odd\n\tname"
        (self.repo / path).write_text("base\n")
        self.git("add", "--", path)
        self.git("commit", "-qm", "odd path")
        self.source = self.git("rev-parse", "HEAD")
        self.git("update-index", "--skip-worktree", "--", path)
        (self.repo / path).write_text("hidden\n")
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.receipt()["before"]["dirty"])

    def test_operator_clearing_flags_allows_a_fresh_clean_receipt(self):
        self.git("update-index", "--assume-unchanged", "input")
        self.assertEqual(self.execute().returncode, 2)
        self.assertEqual(self.receipt()["status"], "rejected")
        self.git("update-index", "--no-assume-unchanged", "input")
        self.result.unlink()
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.receipt()["status"], "passed")
        self.assertTrue(self.marker.exists())

    def test_ambient_git_dir_cannot_attest_a_different_checkout(self):
        foreign = self.root / "foreign"
        foreign.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(foreign), *args], text=True, stderr=subprocess.PIPE
            ).strip()

        git("init", "-q")
        git("config", "user.name", "foreign-test")
        git("config", "user.email", "foreign@example.invalid")
        (foreign / "input").write_text("base\n")
        git("add", ".")
        git("commit", "-qm", "foreign")
        claimed = git("rev-parse", "HEAD")
        self.assertNotEqual(claimed, self.source)
        result = self.execute(
            GIT_DIR=str(foreign / ".git"),
            GIT_WORK_TREE=str(foreign),
            SOURCE_SHA=claimed,
            TESTED_SHA=claimed,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.receipt()["before"]["commit"], self.source)
        self.assertEqual(self.receipt()["status"], "rejected")

    def test_replacement_commit_cannot_make_changed_tree_pass(self):
        original_tree = self.git("rev-parse", "HEAD^{tree}")
        (self.repo / "input").write_text("replacement tree\n")
        self.git("add", "input")
        replacement_tree = self.git("write-tree")
        replacement = self.git("commit-tree", replacement_tree, "-m", "replacement")
        self.git("reset", "-q", "--mixed", self.source)
        self.git("replace", self.source, replacement)
        self.git("read-tree", replacement_tree)
        self.assertEqual(self.git("status", "--porcelain"), "")
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.receipt()["before"]["tree"], original_tree)
        self.assertTrue(self.receipt()["before"]["dirty"])

    def test_ambient_alternate_index_cannot_hide_actual_source(self):
        alternate = self.root / "alternate-index"
        alternate.write_bytes((self.repo / ".git/index").read_bytes())
        self.git("update-index", "--assume-unchanged", "input")
        hidden = (self.repo / ".git/index").read_bytes()
        (self.repo / ".git/index").write_bytes(alternate.read_bytes())
        alternate.write_bytes(hidden)
        (self.repo / "input").write_text("unreviewed\n")
        result = self.execute(GIT_INDEX_FILE=str(alternate))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.receipt()["before"]["dirty"])

    def test_metadata_reads_do_not_execute_a_configured_fsmonitor(self):
        hook = self.root / "monitor"
        observed = self.root / "monitor-called"
        hook.write_text(
            "#!/bin/sh\nprintf called > "
            + shlex.quote(str(observed))
            + "\nprintf 'token\\000'\n"
        )
        hook.chmod(0o700)
        self.git("config", "core.fsmonitor", str(hook))
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(observed.exists(), "metadata verification executed a hook")
        self.assertEqual(self.receipt()["status"], "passed")
        self.assertTrue(self.marker.exists())
