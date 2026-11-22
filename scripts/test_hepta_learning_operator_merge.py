"""Execute the qualification workflow's real merge and post-test guards."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "Ubuntu qualification shell integration")
class LearningOperatorMergeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "common.txt").write_text("common\n")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.git("switch", "-qc", "source")
        (self.repo / "source.txt").write_text("source\n")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.git("switch", "main")
        (self.repo / "base.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.source)
        self.invocations = 0
        workflow = (
            ROOT / ".github/workflows/learning-operator-required.yml"
        ).read_text()

        def script(name):
            step = workflow.split(f"      - name: {name}\n", 1)[1]
            step = step.split("      - name:", 1)[0]
            return textwrap.dedent(step.split("        run: |\n", 1)[1])

        self.merge_script = script("Materialize deterministic ordered-parent merge")
        compile_script = script("Compile and test deterministic merge candidate")
        self.guard_script = (
            "set -euo pipefail\n"
            + compile_script.split(
                "} 2>&1 | tee .hepta-evidence/learning-operator/synthetic-merge-tests.log\n",
                1,
            )[1]
        )

    def git(self, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=fixture",
                "-c",
                "user.email=fixture@example.invalid",
                *args,
            ],
            cwd=self.repo,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def materialize(self, **extra_env):
        self.invocations += 1
        output = self.root / f"environment-{self.invocations}"
        result = subprocess.run(
            ["bash", "-c", self.merge_script],
            cwd=self.repo,
            env={
                **os.environ,
                **extra_env,
                "SOURCE_SHA": self.source,
                "BASE_SHA": self.base,
                "GITHUB_ENV": str(output),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        values = (
            dict(line.split("=", 1) for line in output.read_text().splitlines())
            if output.exists()
            else {}
        )
        return result, values

    def guard(self, values):
        return subprocess.run(
            ["bash", "-c", self.guard_script],
            cwd=self.repo,
            env={**os.environ, "SOURCE_SHA": self.source, **values},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_materializes_ordered_commit_and_clean_tracked_tree(self):
        expected_tree = self.git("merge-tree", "--write-tree", self.base, self.source)
        result, values = self.materialize()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        candidate = values["MERGE_COMMIT"]
        self.assertEqual(self.git("rev-parse", "HEAD"), candidate)
        self.assertEqual(
            self.git("rev-list", "--parents", "-n", "1", "HEAD"),
            f"{candidate} {self.base} {self.source}",
        )
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), expected_tree)
        self.assertEqual(self.git("write-tree"), expected_tree)
        self.assertEqual(values["MERGE_TREE"], expected_tree)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=no"), "")
        self.assertEqual((self.repo / "source.txt").read_text(), "source\n")
        self.assertEqual((self.repo / "base.txt").read_text(), "base\n")
        self.assertEqual(self.guard(values).returncode, 0)

    def test_same_parents_and_tree_are_independent_of_runner_date(self):
        candidates = []
        for date in ("2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"):
            self.git("reset", "--hard", self.source)
            result, values = self.materialize(
                GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            candidates.append(values)
        self.assertEqual(candidates[0], candidates[1])

    def test_wrong_checked_out_source_is_rejected(self):
        self.git("checkout", "--detach", self.base)
        result, values = self.materialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values, {})

    def test_conflicting_parent_content_does_not_emit_a_candidate(self):
        (self.repo / "common.txt").write_text("source version\n")
        self.git("commit", "-qam", "source conflict")
        self.source = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.base)
        (self.repo / "common.txt").write_text("base version\n")
        self.git("commit", "-qam", "base conflict")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.source)
        result, values = self.materialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values, {})
        self.assertNotEqual(self.git("ls-files", "-u"), "")

    def test_source_trailing_whitespace_is_still_rejected(self):
        (self.repo / "new-source.rs").write_text("fn sample() {} \n")
        self.git("add", "new-source.rs")
        self.git("commit", "-qm", "source with whitespace error")
        self.source = self.git("rev-parse", "HEAD")
        result, values = self.materialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("new-source.rs:1: trailing whitespace", result.stdout)
        self.assertEqual(values, {})

    def test_post_test_guard_rejects_same_tree_under_a_different_head(self):
        result, values = self.materialize()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        other = self.git(
            "commit-tree", values["MERGE_TREE"], "-p", self.source, "-m", "other"
        )
        self.git("checkout", "--detach", other)
        self.assertNotEqual(self.guard(values).returncode, 0)

    def test_post_test_guard_rejects_tracked_worktree_mutation(self):
        result, values = self.materialize()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.repo / "source.txt").write_text("changed during qualification\n")
        self.assertNotEqual(self.guard(values).returncode, 0)


if __name__ == "__main__":
    unittest.main()
