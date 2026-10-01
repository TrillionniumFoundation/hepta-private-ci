"""Exercise artifact qualification's candidate binding with real local Git."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-artifact-storage.yml"


class ArtifactWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.directory.name)
        cls.git("init", "-q")
        cls.git("config", "user.name", "qualification-fixture")
        cls.git("config", "user.email", "qualification@invalid")
        (cls.repo / "root").write_text("root\n")
        cls.git("add", ".")
        cls.git("commit", "-qm", "root")
        root = cls.git("rev-parse", "HEAD")
        (cls.repo / "base").write_text("base\n")
        cls.git("add", ".")
        cls.git("commit", "-qm", "base")
        cls.base = cls.git("rev-parse", "HEAD")
        cls.git("checkout", "-q", "--detach", root)
        (cls.repo / "source").write_text("source\n")
        cls.git("add", ".")
        cls.git("commit", "-qm", "source")
        cls.source = cls.git("rev-parse", "HEAD")
        cls.workflow = WORKFLOW.read_text()
        block = cls.workflow.split("      - name: Bind exact Git candidate\n", 1)[1]
        block = block.split("\n      - ", 1)[0]
        cls.shell = textwrap.dedent(block.split("        run: |\n", 1)[1])

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(
            ["git", *args], cwd=cls.repo, text=True, stderr=subprocess.PIPE
        ).strip()

    def setUp(self):
        self.git("checkout", "-q", "--detach", self.source)

    def resolve(self, key, values):
        # These workflow expressions contain only GitHub's string OR fallback.
        expression = re.search(
            rf"^      {key}: \$\{{\{{ (.+) \}}\}}$", self.workflow, re.MULTILINE
        )
        self.assertIsNotNone(expression)
        return next(
            (
                values[item.strip()]
                for item in expression[1].split("||")
                if values.get(item.strip())
            ),
            "",
        )

    def bind(self, source, base, lane="source-head"):
        return subprocess.run(
            ["bash", "-c", self.shell.replace("${{ matrix.lane }}", lane)],
            cwd=self.repo,
            env=dict(os.environ, SOURCE_SHA=source, BASE_SHA=base),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def test_manual_dispatch_uses_selected_source_and_explicit_base(self):
        values = {"github.sha": self.source, "inputs.base_sha": self.base}
        result = self.bind(
            self.resolve("SOURCE_SHA", values), self.resolve("BASE_SHA", values)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)

    def test_reusable_push_uses_source_and_before_context(self):
        values = {"github.sha": self.source, "github.event.before": self.base}
        result = self.bind(
            self.resolve("SOURCE_SHA", values), self.resolve("BASE_SHA", values)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reusable_pr_uses_head_instead_of_event_merge_sha(self):
        values = {
            "github.sha": self.base,
            "github.event.pull_request.head.sha": self.source,
            "github.event.pull_request.base.sha": self.base,
        }
        result = self.bind(
            self.resolve("SOURCE_SHA", values), self.resolve("BASE_SHA", values)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_inputs_build_exact_ordered_parent_merge(self):
        values = {
            "inputs.source_sha": self.source,
            "inputs.base_sha": self.base,
            "github.sha": self.base,
            "github.event.pull_request.head.sha": self.base,
            "github.event.pull_request.base.sha": self.source,
        }
        result = self.bind(
            self.resolve("SOURCE_SHA", values),
            self.resolve("BASE_SHA", values),
            "synthetic-merge",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.git("show", "-s", "--format=%P", "HEAD"), f"{self.base} {self.source}"
        )
        self.assertEqual(
            self.git("ls-tree", "--name-only", "HEAD").splitlines(),
            ["base", "root", "source"],
        )

    def test_invalid_base_rejects_before_candidate_mutation(self):
        blob = self.git("rev-parse", "HEAD:source")
        for base in ["", "0" * 40, "main", "f" * 40, blob]:
            with self.subTest(base=base):
                result = self.bind(self.source, base, "synthetic-merge")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git("rev-parse", "HEAD"), self.source)

    def test_wrong_checkout_or_identical_parents_reject(self):
        for source, base in [(self.base, self.source), (self.source, self.source)]:
            with self.subTest(source=source, base=base):
                result = self.bind(source, base, "synthetic-merge")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git("rev-parse", "HEAD"), self.source)


if __name__ == "__main__":
    unittest.main()
