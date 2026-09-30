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
        protected = next(
            item
            for item in row["workflows"]
            if Path(item["path"]).name == policy.PROTECTED_WORKFLOW
        )
        self.assertTrue(protected["protectedEnvironment"])
        self.assertTrue(protected["trustedVerifierOnly"])
        self.assertFalse(protected["candidateCodeExecuted"])

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

    def test_protected_runner_never_checks_out_or_executes_candidate_code(self):
        source = (
            ROOT / ".github/workflows" / policy.PROTECTED_WORKFLOW
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / policy.PROTECTED_WORKFLOW
            path.write_text(
                source.replace(
                    "ref: ${{ env.VERIFIER_SHA }}",
                    "ref: ${{ env.CANDIDATE_SHA }}",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                policy.validate_protected_workflow(path)
            path.write_text(
                source.replace(
                    'git merge-base --is-ancestor "$CANDIDATE_SHA" "$VERIFIER_SHA"',
                    'git checkout "$CANDIDATE_SHA"',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                policy.validate_protected_workflow(path)

    def test_protected_candidate_sha_uses_are_closed(self):
        source = (
            ROOT / ".github/workflows" / policy.PROTECTED_WORKFLOW
        ).read_text(encoding="utf-8")
        marker = 'git merge-base --is-ancestor "$CANDIDATE_SHA" "$VERIFIER_SHA"'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / policy.PROTECTED_WORKFLOW
            path.write_text(
                source.replace(
                    marker,
                    marker + '\n          git archive "$CANDIDATE_SHA" > candidate.tar',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                policy.validate_protected_workflow(path)

    def test_protected_runner_is_main_only(self):
        source = (
            ROOT / ".github/workflows" / policy.PROTECTED_WORKFLOW
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / policy.PROTECTED_WORKFLOW
            path.write_text(
                source.replace(
                    " && github.ref == 'refs/heads/main'",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                policy.validate_protected_workflow(path)


if __name__ == "__main__":
    unittest.main()
