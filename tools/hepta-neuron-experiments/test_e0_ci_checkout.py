"""Static regression for exact PR-head E0 evidence execution.

GitHub pull_request github.sha is a synthetic merge SHA, not the PR head.
These tests never execute models or grant production authorization.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows/hepta-neuron-experiments.yml"


class ExactHeadWorkflowTests(unittest.TestCase):
    def test_pr_candidate_checkout_is_not_synthetic_merge(self):
        source = WF.read_text(encoding="utf-8")
        self.assertNotIn("ref: ${{ github.sha }}", source)
        self.assertEqual(source.count(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}"
        ), 1)
        self.assertEqual(source.count(
            "ref: ${{ github.event.pull_request.head.sha }}"
        ), 1)

    def test_verified_sha_matches_both_checkout_identities(self):
        source = WF.read_text(encoding="utf-8")
        self.assertNotIn("EXPECTED_SHA: ${{ github.sha }}", source)
        self.assertEqual(source.count(
            "EXPECTED_SHA: ${{ github.event.pull_request.head.sha || github.sha }}"
        ), 1)
        self.assertEqual(source.count(
            "EXPECTED_SHA: ${{ github.event.pull_request.head.sha }}"
        ), 1)
        self.assertEqual(source.count(
            'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"'
        ), 2)

    def test_heavy_public_job_stays_same_repo_pr_only(self):
        source = WF.read_text(encoding="utf-8")
        self.assertIn(
            "github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository",
            source,
        )
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("cancel-in-progress: true", source)


if __name__ == "__main__":
    unittest.main()
