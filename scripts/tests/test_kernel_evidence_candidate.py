"""Real Git-object regressions for exact-source and non-PR merge planning."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "kernel_evidence_candidate.py"
SPEC = importlib.util.spec_from_file_location("evidence_candidate_under_test", SCRIPT)
CANDIDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANDIDATE)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Evidence test")
        self.git("config", "user.email", "evidence@example.invalid")
        self.initial = self.commit("initial.txt", "initial")
        self.base = self.commit("base.txt", "base")
        self.source = self.commit("source.txt", "source")

    def git(self, *args, env=None):
        return subprocess.check_output(
            ["git", *args],
            cwd=self.root,
            text=True,
            stderr=subprocess.PIPE,
            env=env,
        ).strip()

    def commit(self, filename, data):
        (self.root / filename).write_text(data)
        self.git("add", filename)
        self.git("commit", "-qm", data)
        return self.git("rev-parse", "HEAD")

    def plan(self, base="", source=None):
        return CANDIDATE.resolve_candidate(self.root, source or self.source, base)

    def test_non_pr_uses_exact_first_parent(self):
        plan = self.plan()
        self.assertEqual(plan["baseCommit"], self.base)
        self.assertEqual(plan["baseSelection"], "source-first-parent")
        self.assertFalse(plan["qualificationGranted"])

    def test_explicit_base_is_retained(self):
        plan = self.plan(self.initial)
        self.assertEqual(plan["baseCommit"], self.initial)
        self.assertEqual(plan["baseSelection"], "explicit-base")

    def test_source_tree_and_parent_order_are_exact(self):
        plan = self.plan()
        self.assertEqual(plan["sourceTree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(plan["expectedMergeParents"], [self.base, self.source])

    def test_rejects_short_source(self):
        with self.assertRaises(ValueError):
            self.plan(source=self.source[:12])

    def test_rejects_branch_name_base(self):
        with self.assertRaises(ValueError):
            self.plan("HEAD~1")

    def test_rejects_injected_base(self):
        with self.assertRaises(ValueError):
            self.plan(self.base + "\nTESTED_SHA=forged")

    def test_rejects_duplicate_parent(self):
        with self.assertRaises(ValueError):
            self.plan(self.source)

    def test_rejects_wrong_source_checkout(self):
        with self.assertRaises(ValueError):
            self.plan(source=self.base)

    def test_rejects_missing_base_object(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.plan("f" * 40)

    def test_rejects_tree_instead_of_base_commit(self):
        with self.assertRaises(ValueError):
            self.plan(self.git("rev-parse", "HEAD^{tree}"))

    def test_rejects_mixed_object_formats(self):
        with self.assertRaises(ValueError):
            self.plan("a" * 64)

    def test_rejects_dirty_tracked_source(self):
        (self.root / "source.txt").write_text("drift")
        with self.assertRaises(ValueError):
            self.plan()

    def test_rejects_untracked_source(self):
        (self.root / "untracked.txt").write_text("drift")
        with self.assertRaises(ValueError):
            self.plan()

    def test_root_source_needs_explicit_base(self):
        self.git("checkout", "-q", "--detach", self.initial)
        with self.assertRaises(ValueError):
            self.plan(source=self.initial)

    def test_detached_source_is_supported(self):
        self.git("checkout", "-q", "--detach", self.source)
        self.assertEqual(self.plan()["sourceCommit"], self.source)

    def test_deterministic_merge_has_both_distinct_parents(self):
        plan = self.plan()
        tree = self.git("merge-tree", "--write-tree", plan["baseCommit"], self.source)
        env = dict(
            os.environ,
            GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
        )
        command = (
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            "-m",
            "Evidence merge",
        )
        first, second = self.git(*command, env=env), self.git(*command, env=env)
        self.assertEqual(first, second)
        self.assertEqual(
            self.git("rev-list", "--parents", "-n", "1", first).split(),
            [first, self.base, self.source],
        )
        self.assertEqual(tree, plan["sourceTree"])

    def test_divergent_base_tree_is_recomputed(self):
        self.git("checkout", "-q", "--detach", self.base)
        other = self.commit("other.txt", "other")
        self.git("checkout", "-q", "--detach", self.source)
        plan = self.plan(other)
        tree = self.git("merge-tree", "--write-tree", other, self.source)
        self.assertNotEqual(tree, plan["sourceTree"])
        self.assertEqual(plan["expectedMergeParents"], [other, self.source])

    def cli(self, *extra):
        diagnostic = Path(self.temp.name) / "candidate.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                "--source",
                self.source,
                "--diagnostic",
                str(diagnostic),
                *extra,
            ],
            text=True,
            capture_output=True,
        )
        return result, diagnostic

    def test_cli_exports_same_base_to_runner_and_diagnostic(self):
        envfile, outfile = Path(self.temp.name) / "env", Path(self.temp.name) / "out"
        result, diagnostic = self.cli(
            "--github-env", str(envfile), "--github-output", str(outfile)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(diagnostic.read_text())["baseCommit"], self.base)
        self.assertEqual(envfile.read_text(), f"BASE_SHA={self.base}\n")
        self.assertIn(f"base-sha={self.base}\n", outfile.read_text())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_failure_retains_negative_diagnostic(self):
        result, diagnostic = self.cli("--base", self.source)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(diagnostic.read_text())["resolved"])
        self.assertFalse(json.loads(diagnostic.read_text())["qualificationGranted"])

    def test_runner_output_must_not_dirty_source(self):
        result, diagnostic = self.cli("--github-env", str(self.root / "bad-env"))
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / "bad-env").exists())
        self.assertFalse(json.loads(diagnostic.read_text())["resolved"])


if __name__ == "__main__":
    unittest.main()
