"""Exercise merge refusal and retained observations with real local Git objects.

Only the GitHub API is replaced by a fixture. These tests do not qualify a
hosted merge ref or turn today's observation into evidence for a historical run.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/hepta-architecture-convergence.yml"
)


def merge_command():
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"^      - name: Verify GitHub prospective merge ref matches this exact candidate\n"
        r"(?P<step>.*?)(?=^      - |\Z)",
        text,
        re.M | re.S,
    )
    if match is None:
        raise AssertionError("missing exact-candidate merge check")
    step = match.group("step")
    if "        shell: bash\n" not in step:
        raise AssertionError("merge check must use Bash semantics")
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


class MergeIdentityRecordTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Merge identity test")
        self.git("config", "user.email", "merge-identity@example.invalid")
        (self.repository / "shared").write_text("common\n", encoding="utf-8")
        self.common = self.commit("common")
        (self.repository / "base").write_text("base\n", encoding="utf-8")
        self.base = self.commit("base")
        self.git("checkout", "--detach", self.common)
        (self.repository / "source").write_text("source\n", encoding="utf-8")
        self.source = self.commit("source")
        self.tree = self.git("merge-tree", "--write-tree", self.base, self.source)
        self.actual = self.git(
            "commit-tree", self.tree, "-p", self.base, "-p", self.source, "-m", "merge"
        )
        self.api = self.root / "api"
        self.api.mkdir()
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        gh = self.bindir / "gh"
        gh.write_text(
            "#!/bin/bash\nset -eu\n"
            'case "$2" in\n'
            "  */git/ref/pull/*/merge) kind=ref ;;\n"
            "  */git/commits/*) kind=commit ;;\n"
            "  *) exit 90 ;;\n"
            "esac\n"
            'cat "$API_FIXTURE/$kind.json"\n'
            'cat "$API_FIXTURE/$kind.stderr" >&2\n'
            'exit "$(cat "$API_FIXTURE/$kind.status")"\n',
            encoding="utf-8",
        )
        gh.chmod(0o700)
        self.env_file = self.root / "github-env"
        self.records = self.root / "hepta-command-records/merge-identity"

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repository, text=True, stderr=subprocess.PIPE
        ).strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def run_check(self, *, parents=None, tree=None, ref_status=0, commit_status=0):
        ref = {"object": {"sha": self.actual}}
        commit = {
            "parents": [{"sha": sha} for sha in (parents or [self.base, self.source])],
            "tree": {"sha": tree or self.tree},
        }
        for kind, payload, status in (
            ("ref", ref, ref_status),
            ("commit", commit, commit_status),
        ):
            (self.api / f"{kind}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            (self.api / f"{kind}.status").write_text(str(status), encoding="utf-8")
            (self.api / f"{kind}.stderr").write_text(
                f"{kind} unavailable\n" if status else "", encoding="utf-8"
            )
        return subprocess.run(
            ["bash", "-c", merge_command()],
            cwd=self.repository,
            env={
                **os.environ,
                "PATH": f"{self.bindir}{os.pathsep}{os.environ['PATH']}",
                "API_FIXTURE": str(self.api),
                "RUNNER_TEMP": str(self.root),
                "GITHUB_ENV": str(self.env_file),
                "SOURCE_SHA": self.source,
                "BASE_SHA": self.base,
                "PR_NUMBER": "1",
                "REPO": "example/merge-records",
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def read_record(self, name):
        return json.loads((self.records / name).read_text(encoding="utf-8"))

    def assert_refused(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.env_file.exists(), result.stdout + result.stderr)

    def test_exact_parents_and_tree_succeed_with_observations(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = self.read_record("expected.json")
        self.assertEqual(expected["expected_source"], self.source)
        self.assertEqual(expected["expected_base"], self.base)
        self.assertTrue(expected["current_ref_is_not_historical_run_evidence"])
        self.assertEqual(self.read_record("ref.json")["object"]["sha"], self.actual)
        self.assertTrue(self.read_record("parents.json")["source_matches"])
        self.assertTrue(self.read_record("tree.json")["matches"])
        self.assertEqual(
            self.env_file.read_text(encoding="utf-8"),
            f"GITHUB_PROSPECTIVE_MERGE_SHA={self.actual}\n"
            f"GITHUB_PROSPECTIVE_MERGE_TREE={self.tree}\n",
        )

    def test_stale_source_is_refused_and_observed(self):
        result = self.run_check(parents=[self.base, self.common])
        self.assert_refused(result)
        self.assertFalse(self.read_record("parents.json")["source_matches"])
        self.assertFalse((self.records / "tree.json").exists())

    def test_stale_base_is_refused_and_observed(self):
        result = self.run_check(parents=[self.common, self.source])
        self.assert_refused(result)
        self.assertFalse(self.read_record("parents.json")["base_matches"])

    def test_single_parent_is_refused_and_observed(self):
        result = self.run_check(parents=[self.base])
        self.assert_refused(result)
        self.assertFalse(self.read_record("parents.json")["two_parents"])

    def test_different_tree_is_refused_and_observed(self):
        result = self.run_check(tree=self.git("rev-parse", f"{self.base}^{{tree}}"))
        self.assert_refused(result)
        tree = self.read_record("tree.json")
        self.assertFalse(tree["matches"])
        self.assertEqual(tree["merge_tree_exit"], 0)
        self.assertEqual(tree["expected_tree"], self.tree)

    def test_merge_conflict_is_refused_and_git_output_is_retained(self):
        self.git("checkout", "--detach", self.base)
        (self.repository / "shared").write_text("base changed\n", encoding="utf-8")
        self.base = self.commit("base conflict")
        self.git("checkout", "--detach", self.source)
        (self.repository / "shared").write_text("source changed\n", encoding="utf-8")
        self.source = self.commit("source conflict")
        result = self.run_check()
        self.assert_refused(result)
        tree = self.read_record("tree.json")
        self.assertNotEqual(tree["merge_tree_exit"], 0)
        self.assertFalse(tree["matches"])
        self.assertIn(
            "CONFLICT", (self.records / "merge-tree.stdout").read_text(encoding="utf-8")
        )
        self.assertTrue((self.records / "merge-tree.stderr").is_file())

    def test_ref_api_failure_retains_expected_identity_and_failure(self):
        result = self.run_check(ref_status=7)
        self.assert_refused(result)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(
            self.read_record("expected.json")["expected_source"], self.source
        )
        self.assertEqual(
            (self.records / "ref.stderr").read_text(encoding="utf-8"),
            "ref unavailable\n",
        )
        self.assertFalse((self.records / "commit.json").exists())

    def test_commit_api_failure_retains_ref_and_failure(self):
        result = self.run_check(commit_status=9)
        self.assert_refused(result)
        self.assertEqual(result.returncode, 9)
        self.assertEqual(self.read_record("ref.json")["object"]["sha"], self.actual)
        self.assertEqual(
            (self.records / "commit.stderr").read_text(encoding="utf-8"),
            "commit unavailable\n",
        )
        self.assertFalse((self.records / "parents.json").exists())


if __name__ == "__main__":
    unittest.main()
