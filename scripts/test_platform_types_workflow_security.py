#!/usr/bin/env python3
"""Reject free-form executable checkout refs in platform.types workflows."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEEP = ROOT / ".github/workflows/platform-types-deep-qualification.yml"
LEGACY = ROOT / ".github/workflows/platform-types-convergence-repair.yml"


class PlatformTypesWorkflowSecurityTests(unittest.TestCase):
    def test_deep_qualification_uses_event_bound_source_and_base(self) -> None:
        text = DEEP.read_text(encoding="utf-8")
        for forbidden in (
            "inputs.candidate_ref",
            "inputs.base_ref",
            "ref: ${{ inputs.",
            "REQUESTED_SOURCE_REF: ${{ inputs.",
            "REQUESTED_BASE_REF: ${{ inputs.",
            "inputs.pr_number",
            "workflow_dispatch",
            "ref: ${{ needs.resolve.outputs.source_sha }}",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}", text
        )
        self.assertIn(
            "REQUESTED_SOURCE_REF: ${{ github.event.pull_request.head.sha || github.sha }}",
            text,
        )
        self.assertIn(
            "REQUESTED_BASE_REF: ${{ github.event.pull_request.base.sha || github.event.before || 'origin/main' }}",
            text,
        )
        self.assertGreaterEqual(
            text.count("ref: ${{ github.event.pull_request.head.sha || github.sha }}"),
            3,
        )
        self.assertIn("if: github.event_name == 'pull_request'", text)
        self.assertGreaterEqual(text.count("persist-credentials: false"), 3)
        self.assertIn("permissions:\n  contents: read", text)

    def test_legacy_verifier_uses_event_bound_sha_only(self) -> None:
        text = LEGACY.read_text(encoding="utf-8")
        for forbidden in (
            "candidate_ref:",
            "inputs.candidate_ref",
            "ref: ${{ inputs.",
            "workflow_dispatch",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"', text)
        self.assertIn(
            '--expected-sha "${{ github.event.pull_request.head.sha || github.sha }}"',
            text,
        )
        self.assertIn("persist-credentials: false", text)
        self.assertIn("permissions:\n  contents: read", text)


if __name__ == "__main__":
    unittest.main()
