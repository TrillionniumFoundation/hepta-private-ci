"""Exercise ledger cancellation identity from the actual workflow expression.

This bounded evaluator models only the context fallback used by concurrency;
it is not a substitute for hosted GitHub Actions execution.
"""

from pathlib import Path
import re
import os
import subprocess
import tempfile
import unittest

from scripts.hepta_workflow_commands import load_workflow

ROOT = Path(__file__).resolve().parents[1]


def concurrency_key(group, *, pull_request_number=None, ref):
    context = {
        "github.event.pull_request.number": pull_request_number,
        "github.ref": ref,
    }

    def resolve(match):
        names = [name.strip() for name in match[1].split("||")]
        if any(name not in context for name in names):
            raise ValueError("unsupported concurrency context expression")
        return str(next((context[name] for name in names if context[name]), ""))

    return re.sub(r"\$\{\{([^{}]+)\}\}", resolve, group).casefold()


class LedgerWorkflowConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.document = load_workflow(
            (ROOT / ".github/workflows/hepta-learning-ledger-durable.yml").read_text()
        )
        self.group = self.document["concurrency"]["group"]

    def test_non_pr_branches_do_not_cancel_each_other(self):
        first = concurrency_key(self.group, ref="refs/heads/audit/ledger-a")
        second = concurrency_key(self.group, ref="refs/heads/audit/ledger-b")
        self.assertNotEqual(first, second)
        self.assertEqual(
            first, concurrency_key(self.group, ref="refs/heads/audit/ledger-a")
        )

    def test_branch_and_tag_with_same_name_remain_distinct(self):
        self.assertNotEqual(
            concurrency_key(self.group, ref="refs/heads/ledger-candidate"),
            concurrency_key(self.group, ref="refs/tags/ledger-candidate"),
        )

    def test_pr_revisions_share_their_pr_group_only(self):
        first = concurrency_key(
            self.group, pull_request_number=738, ref="refs/pull/738/merge"
        )
        self.assertEqual(
            first,
            concurrency_key(
                self.group, pull_request_number=738, ref="refs/heads/ledger-a"
            ),
        )
        self.assertNotEqual(
            first,
            concurrency_key(
                self.group, pull_request_number=869, ref="refs/pull/869/merge"
            ),
        )
        self.assertNotEqual(first, concurrency_key(self.group, ref="refs/heads/738"))


class LedgerIntegrationWorkflowTests(unittest.TestCase):
    def test_desktop_target_directory_is_bound_at_step_runtime(self):
        workflow = load_workflow(
            (ROOT / ".github/workflows/blocking-ci.yml").read_text()
        )
        desktop = workflow["jobs"]["native-desktop"]
        # Job-level env is evaluated before a runner context exists.
        self.assertFalse(
            any("runner." in str(value) for value in desktop.get("env", {}).values())
        )
        steps = desktop["steps"]
        bindings = [
            (index, step)
            for index, step in enumerate(steps)
            if "CARGO_TARGET_DIR=" in step.get("run", "")
        ]
        self.assertEqual(len(bindings), 1)
        index, step = bindings[0]
        first_build = next(
            i for i, value in enumerate(steps) if "cargo " in value.get("run", "")
        )
        self.assertLess(index, first_build)
        with tempfile.TemporaryDirectory(prefix="ledger runtime ") as root:
            target = Path(root) / "github env"
            target.write_text("EXISTING=retained\n")
            result = subprocess.run(
                ["bash", "-e", "-c", step["run"]],
                env=os.environ | {"RUNNER_TEMP": root, "GITHUB_ENV": str(target)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                target.read_text(),
                f"EXISTING=retained\nCARGO_TARGET_DIR={root}/hepta-desktop-target\n",
            )


if __name__ == "__main__":
    unittest.main()
