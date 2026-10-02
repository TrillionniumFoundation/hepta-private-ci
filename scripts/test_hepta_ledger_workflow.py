"""Exercise ledger cancellation identity from the actual workflow expression.

This bounded evaluator models only the context fallback used by concurrency;
it is not a substitute for hosted GitHub Actions execution.
"""

from pathlib import Path
import re
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


if __name__ == "__main__":
    unittest.main()
