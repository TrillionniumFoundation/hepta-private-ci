from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/channel-matrix-preserve-unknown.yml"


class QualificationTrustBoundaryTests(unittest.TestCase):
    def text(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_candidate_workflow_has_no_privileged_manual_trigger(self) -> None:
        text = self.text()
        self.assertIn("pull_request:", text)
        self.assertIn("push:", text)
        self.assertNotIn("workflow_dispatch:", text)
        self.assertNotIn("pull_request_target:", text)

    def test_candidate_workflow_has_no_mutable_cache_channel(self) -> None:
        text = self.text()
        for forbidden in (
            "actions/cache",
            "actions/cache/restore",
            "actions/cache/save",
            "cache-dependency-path",
            "save-always",
            "cache-mode:",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_synthetic_merge_is_event_bound_and_fail_closed(self) -> None:
        text = self.text()
        self.assertIn("EVENT_PR_NUMBER: ${{ github.event.pull_request.number }}", text)
        self.assertIn("+refs/pull/$EVENT_PR_NUMBER/merge:", text)
        self.assertIn('test "$observed" = "$GITHUB_MERGE_SHA"', text)
        self.assertNotIn("|| true", text)

    def test_all_checkouts_are_read_only(self) -> None:
        text = self.text()
        self.assertIn("permissions:\n  contents: read", text)
        checkout_count = text.count("uses: actions/checkout@")
        self.assertGreaterEqual(checkout_count, 2)
        self.assertEqual(checkout_count, text.count("persist-credentials: false"))
        self.assertNotRegex(text, re.compile(r"(?m)^\s*contents:\s*write\s*$"))

    def test_two_exact_lanes_share_one_frozen_matrix_definition(self) -> None:
        text = self.text()
        self.assertIn("strategy:\n      fail-fast: false\n      matrix:", text)
        self.assertIn("lane: source-head", text)
        self.assertIn("lane: base-merge", text)
        self.assertEqual(text.count("python3 -m unittest scripts.tests.test_channel_matrix_source_provenance -v"), 2)
        self.assertEqual(text.count("channel_matrix_source_provenance.py"), 2)

    def test_one_run_produces_atomic_status_projection(self) -> None:
        text = self.text()
        self.assertIn("channel_matrix_pair_acceptance_v2.py", text)
        self.assertIn("channel_matrix_readiness.py", text)
        self.assertIn("channel_matrix_readiness_projection.py", text)
        self.assertIn("status-bundle", text)
        self.assertIn(
            "channel-matrix-readiness-${{ github.run_id }}-${{ github.run_attempt }}",
            text,
        )


if __name__ == "__main__":
    unittest.main()
