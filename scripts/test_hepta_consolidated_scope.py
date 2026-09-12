"""Execute the consolidated workflow's change-scope decision in real Git repos."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConsolidatedScopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-ci-scope-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        workflow = (ROOT / ".github/workflows/hepta-consolidated-source.yml").read_text()
        # Execute the actual run block, not a reimplementation of its decision.
        block = workflow.split("        id: scope\n", 1)[1].split("        run: |\n", 1)[1]
        lines = []
        for line in block.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        self.script = "\n".join(lines)
        self.git("init", "-q")
        self.git("config", "user.name", "scope-test")
        self.git("config", "user.email", "scope-test@example.invalid")
        (self.root / "readme").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def scope(self, base, source):
        # Keep GITHUB_OUTPUT outside the fixture repository and start it empty.
        with tempfile.TemporaryDirectory(prefix="hepta-ci-output-") as directory:
            output = Path(directory) / "output"
            result = subprocess.run(
                ["bash", "-c", self.script],
                cwd=self.root,
                env={
                    **os.environ,
                    "BASE_SHA": base,
                    "SOURCE_SHA": source,
                    "GITHUB_OUTPUT": str(output),
                },
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, output.read_text() if output.exists() else ""

    def test_only_unchanged_shared_core_can_skip_full_regression(self):
        (self.root / "readme").write_text("documentation change\n")
        self.git("commit", "-qam", "docs")
        source = self.git("rev-parse", "HEAD")
        result, output = self.scope(self.base, source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "required=false\n")
        for path in ("codex-rs/core/x", "codex-rs/common/x", "codex-rs/protocol/x"):
            with self.subTest(path=path):
                before = self.git("rev-parse", "HEAD")
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("shared change\n")
                self.git("add", ".")
                self.git("commit", "-qm", "shared change")
                result, output = self.scope(before, self.git("rev-parse", "HEAD"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "required=true\n")

    def test_missing_base_runs_full_regression_instead_of_skipping(self):
        for base in ("", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                result, output = self.scope(base, self.base)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "required=true\n")

    def test_wrong_checkout_cannot_publish_a_scope_decision(self):
        (self.root / "readme").write_text("new source\n")
        self.git("commit", "-qam", "new source")
        source = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.base)
        result, output = self.scope(self.base, source)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
