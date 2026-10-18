"""Exercise CI identity reads against real Git objects and working-tree changes."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "hepta_ci_exec_identity", Path(__file__).with_name("hepta_ci_exec.py")
)
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-identity-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "identity-test")
        self.git("config", "user.email", "identity-test@example.invalid")
        (self.repo / "input").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.source = self.git("rev-parse", "HEAD")
        self.previous_cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.previous_cwd)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def expected(self, commit, *, dirty=False):
        lines = self.git("cat-file", "-p", commit).split("\n\n", 1)[0].splitlines()
        return {
            "commit": commit,
            "tree": next(line[5:] for line in lines if line.startswith("tree ")),
            "parents": [line[7:] for line in lines if line.startswith("parent ")],
            "dirty": dirty,
        }

    def test_clean_checkout_uses_two_real_git_processes(self):
        with patch.object(executor, "git", wraps=executor.git) as calls:
            actual = executor.identity()
        self.assertEqual(actual, self.expected(self.source))
        self.assertEqual(calls.call_count, 2)

    def test_replacement_ref_does_not_substitute_commit_metadata(self):
        expected = self.expected(self.source)
        replacement = self.git(
            "commit-tree", expected["tree"], "-p", self.source, "-m", "replacement"
        )
        self.git("replace", self.source, replacement)
        self.assertNotEqual(self.expected(self.source), expected)
        self.assertEqual(executor.identity(), expected)

    def test_replaced_source_tree_never_dispatches(self):
        expected = self.expected(self.source, dirty=True)
        (self.repo / "input").write_text("unreviewed\n")
        self.git("add", "input")
        tree = self.git("write-tree")
        replacement = self.git("commit-tree", tree, "-m", "replacement")
        self.git("replace", self.source, replacement)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertNotEqual(tree, expected["tree"])
        marker = self.root / "effect"
        output = self.root / "record.json"
        with (
            patch.dict(
                os.environ,
                {
                    "SOURCE_SHA": self.source,
                    "TESTED_SHA": self.source,
                    "HEPTA_CI_LANE": "source-head",
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = executor.run(
                output,
                [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('effect')"],
            )
        self.assertEqual(result, 2)
        self.assertFalse(marker.exists())
        record = json.loads(output.read_text())
        self.assertEqual(record["before"], expected)
        self.assertEqual(record["status"], "rejected")
        self.assertIsNone(record["command_exit_code"])

    def test_replaced_merge_parents_never_dispatch(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        source = self.git("commit-tree", tree, "-p", self.source, "-m", "source")
        tested = self.git("commit-tree", tree, "-p", source, "-m", "not a merge")
        replacement = self.git(
            "commit-tree", tree, "-p", self.source, "-p", source, "-m", "replacement"
        )
        expected = self.expected(tested)
        self.git("checkout", "-q", "--detach", tested)
        self.git("replace", tested, replacement)
        marker = self.root / "effect"
        output = self.root / "record.json"
        with (
            patch.dict(
                os.environ,
                {
                    "SOURCE_SHA": source,
                    "BASE_SHA": self.source,
                    "TESTED_SHA": tested,
                    "HEPTA_CI_LANE": "base-merge",
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = executor.run(
                output,
                [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('effect')"],
            )
        self.assertEqual(result, 2)
        self.assertFalse(marker.exists())
        record = json.loads(output.read_text())
        self.assertEqual(record["before"], expected)
        self.assertEqual(record["status"], "rejected")
        self.assertIsNone(record["command_exit_code"])

    def test_detached_checkout(self):
        self.git("checkout", "-q", "--detach", self.source)
        self.assertEqual(executor.identity(), self.expected(self.source))

    def test_staged_and_unstaged_changes_remain_dirty(self):
        (self.repo / "input").write_text("changed\n")
        self.assertEqual(executor.identity(), self.expected(self.source, dirty=True))
        self.git("add", "input")
        self.assertEqual(executor.identity(), self.expected(self.source, dirty=True))

    def test_untracked_header_like_filename_remains_dirty(self):
        (self.repo / "# branch.oid ").write_text("untracked")
        self.assertEqual(executor.identity(), self.expected(self.source, dirty=True))

    def test_rename_remains_dirty(self):
        self.git("mv", "input", "renamed input")
        self.assertEqual(executor.identity(), self.expected(self.source, dirty=True))

    def test_merge_parent_order_is_preserved(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        second = self.git("commit-tree", tree, "-p", self.source, "-m", "second")
        merge = self.git(
            "commit-tree", tree, "-p", second, "-p", self.source, "-m", "merge"
        )
        self.git("checkout", "-q", "--detach", merge)
        self.assertEqual(executor.identity(), self.expected(merge))
        self.assertEqual(executor.identity()["parents"], [second, self.source])

    def test_shallow_checkout_retains_raw_parent(self):
        self.git("commit", "--allow-empty", "-qm", "second")
        second = self.git("rev-parse", "HEAD")
        shallow = self.root / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth=1", self.repo.as_uri(), str(shallow)],
            check=True,
        )
        with contextlib.chdir(shallow):
            actual = executor.identity()
        self.assertEqual(actual, self.expected(second))
        self.assertEqual(actual["parents"], [self.source])

    def test_head_movement_cannot_mix_commit_metadata(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        second = self.git("commit-tree", tree, "-p", self.source, "-m", "second")
        original = executor.git

        def advance_after_metadata(*args):
            value = original(*args)
            if args[0] == "cat-file":
                self.git("update-ref", "HEAD", second, self.source)
            return value

        with patch.object(executor, "git", side_effect=advance_after_metadata):
            actual = executor.identity()
        self.assertEqual(self.git("rev-parse", "HEAD"), second)
        self.assertEqual(actual, self.expected(actual["commit"]))

    def test_unborn_checkout_is_rejected(self):
        self.git("checkout", "-q", "--orphan", "unborn")
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            executor.identity()

    def test_dirty_source_never_dispatches(self):
        (self.repo / "input").write_text("unreviewed\n")
        marker = self.root / "effect"
        with (
            patch.dict(
                os.environ,
                {
                    "SOURCE_SHA": self.source,
                    "TESTED_SHA": self.source,
                    "HEPTA_CI_LANE": "source-head",
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = executor.run(
                self.root / "record.json",
                [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('effect')"],
            )
        self.assertEqual(result, 2)
        self.assertFalse(marker.exists())

    def test_command_source_mutation_still_fails(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SOURCE_SHA": self.source,
                    "TESTED_SHA": self.source,
                    "HEPTA_CI_LANE": "source-head",
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = executor.run(
                self.root / "record.json",
                [sys.executable, "-c", "open('input', 'w').write('changed')"],
            )
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
