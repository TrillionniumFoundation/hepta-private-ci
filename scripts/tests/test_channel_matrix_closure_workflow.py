from __future__ import annotations

import base64
import gzip
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/channel-matrix-closure-apply.yml"


class ChannelMatrixClosureWorkflowTests(unittest.TestCase):
    def test_staging_workflow_is_absent_or_exactly_executable(self) -> None:
        # The verified closure commit intentionally deletes this transient
        # workflow. While it exists on the staging candidate, validate the
        # exact checkout boundary and the embedded source payload.
        if not WORKFLOW.exists():
            return

        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("githu.sha", workflow)
        self.assertNotIn("STENGING_SHA", workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            workflow,
        )
        self.assertIn('test "$(git rev-parse HEAD)" = "$STAGING_SHA"', workflow)
        self.assertIn("git rm .github/workflows/channel-matrix-closure-apply.yml", workflow)

        match = re.search(
            r"printf '%s' '([A-Za-z0-9+/=]+)' \| base64 --decode \| gzip -dc",
            workflow,
        )
        self.assertIsNotNone(match)
        source = gzip.decompress(base64.b64decode(match.group(1), validate=True))
        self.assertGreater(len(source), 1_000)
        compile(source, "channel_matrix_apply.py", "exec")

    def test_staging_workflow_preserves_non_skipping_validation(self) -> None:
        if not WORKFLOW.exists():
            return
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s scripts/tests -p 'test_channel_matrix*.py' -v", workflow)
        self.assertIn("cargo check -p codex-hepta-operations --all-targets", workflow)
        self.assertIn("cargo clippy --locked --no-deps", workflow)
        self.assertNotIn("continue-on-error: true", workflow)


if __name__ == "__main__":
    unittest.main()
