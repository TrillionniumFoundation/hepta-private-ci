"""Read-only workflow policy tests for channel.matrix."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_workflow_policy as policy


READ_ONLY = """name: fixture
on:
  workflow_dispatch: {}
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
      - run: python3 -m unittest
"""


class WorkflowPolicyTests(unittest.TestCase):
    def test_repository_workflows_are_read_only(self):
        row = policy.validate_directory()
        self.assertEqual(row["result"], "pass")
        self.assertEqual(
            {Path(item["path"]).name for item in row["workflows"]},
            set(policy.EXPECTED_WORKFLOWS),
        )
        self.assertTrue(all(not item["sourceMutationAllowed"] for item in row["workflows"]))

    def test_write_permissions_and_source_mutation_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "fixture.yml"
            path.write_text(READ_ONLY.replace("contents: read", "contents: write"))
            with self.assertRaises(ValueError):
                policy.validate_workflow(path)
            path.write_text(READ_ONLY.replace("python3 -m unittest", "git push origin HEAD"))
            with self.assertRaises(ValueError):
                policy.validate_workflow(path)
            path.write_text(
                READ_ONLY.replace("python3 -m unittest", "cargo clippy --fix --allow-dirty")
            )
            with self.assertRaises(ValueError):
                policy.validate_workflow(path)

    def test_checkout_credentials_and_unpinned_action_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "fixture.yml"
            path.write_text(
                READ_ONLY.replace("persist-credentials: false", "persist-credentials: true")
            )
            with self.assertRaises(ValueError):
                policy.validate_workflow(path)
            path.write_text(
                READ_ONLY.replace(
                    "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
                    "actions/checkout@v4",
                )
            )
            with self.assertRaises(ValueError):
                policy.validate_workflow(path)


if __name__ == "__main__":
    unittest.main()
