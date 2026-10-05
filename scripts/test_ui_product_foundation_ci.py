"""Exercise the actual synthetic-merge action with its caller's history depth."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "Ubuntu workflow shell integration")
class ProductUiMergeCheckoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin"
        self.git(self.root, "init", "-q", "-b", "main", str(self.origin))
        (self.origin / "base.txt").write_text("base\n")
        self.git(self.origin, "add", "base.txt")
        self.git(self.origin, "commit", "-qm", "base")
        self.base = self.git(self.origin, "rev-parse", "HEAD").strip()
        self.git(self.origin, "switch", "-qc", "source")
        (self.origin / "ui.txt").write_text("source\n")
        self.git(self.origin, "add", "ui.txt")
        self.git(self.origin, "commit", "-qm", "source")
        self.source = self.git(self.origin, "rev-parse", "HEAD").strip()
        action = (ROOT / ".github/actions/hepta-synthetic-merge/action.yml").read_text()
        self.script = textwrap.dedent(action.split("run: |\n", 1)[1])

    @staticmethod
    def git(cwd, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=fixture",
                "-c",
                "user.email=fixture@invalid",
                *args,
            ],
            cwd=cwd,
            text=True,
            stderr=subprocess.PIPE,
        )

    def merge_with_depth(self, depth, name):
        checkout = self.root / name
        depth_args = ["--depth", str(depth)] if depth else []
        self.git(
            self.root,
            "clone",
            "--quiet",
            *depth_args,
            "--branch",
            "source",
            self.origin.as_uri(),
            str(checkout),
        )
        env = dict(
            os.environ,
            BASE_SHA=self.base,
            SOURCE_SHA=self.source,
            PR_NUMBER="1",
            AUTHOR_NAME="fixture",
            AUTHOR_EMAIL="fixture@invalid",
            MESSAGE="fixture merge",
            GITHUB_OUTPUT=str(self.root / f"{name}-outputs"),
        )
        return checkout, subprocess.run(
            ["bash", "-c", self.script],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_shallow_checkout_cannot_supply_the_immutable_base(self):
        _, result = self.merge_with_depth(1, "shallow")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.base, result.stderr)

    def test_product_caller_history_constructs_exact_two_parent_source_tree(self):
        workflow = (ROOT / ".github/workflows/ui-product-foundation.yml").read_text()
        checkout = workflow.split("- uses: actions/checkout@", 1)[1].split(
            "      - ", 1
        )[0]
        depth = re.search(r"fetch-depth:\s*(\d+)", checkout)
        directory, result = self.merge_with_depth(
            int(depth.group(1)) if depth else 1, "caller"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = self.git(directory, "rev-parse", "HEAD").strip()
        self.assertEqual(
            self.git(directory, "rev-list", "--parents", "-n", "1", "HEAD").strip(),
            f"{merged} {self.base} {self.source}",
        )
        self.assertEqual(
            self.git(directory, "rev-parse", "HEAD^{tree}"),
            self.git(self.origin, "rev-parse", "source^{tree}"),
        )


if __name__ == "__main__":
    unittest.main()
