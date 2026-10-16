"""Read-only V18 source-identity, exact-SHA and cross-host token-boundary checks."""
from pathlib import Path
import os
import re
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = Path(os.environ.get(
    "HEPTA_V18_WORKFLOW_SOURCE",
    str(ROOT / ".github/workflows/hepta-stem-v18-original-physical.yml"),
))
ARTIFACT_SHA = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"


class WorkflowSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()

    def test_immutable_original_artifact_identity(self):
        self.assertIn("/actions/artifacts/11890616195/zip", self.source)
        self.assertIn(ARTIFACT_SHA, self.source)
        self.assertIn("| sha256sum -c -", self.source)

    def test_authenticated_redirect_does_not_follow(self):
        source = self.source.split("status=\"$(curl", 1)[1].split(')"', 1)[0]
        self.assertIn("--max-redirs 0", source)
        self.assertNotIn("--location", source)
        self.assertIn("Authorization: Bearer $GH_TOKEN", source)
        self.assertIn("--dump-header", source)

    def test_second_request_has_no_github_token(self):
        source = self.source.split("# This second request deliberately has NO Authorization header.", 1)[1]
        source = source.split("unset location", 1)[0]
        self.assertIn("curl --fail --location", source)
        self.assertIn("--proto-redir '=https'", source)
        self.assertNotIn("Authorization:", source)
        self.assertNotIn("GH_TOKEN", source)

    def test_redirect_scheme_checked(self):
        self.assertIn('if [ "$status" != \'302\' ]', self.source)
        self.assertIn('https://*) ;;', self.source)
        self.assertIn('unset location', self.source)

    def test_exact_readonly_permissions(self):
        self.assertIn("permissions:\n  contents: read\n  actions: read", self.source)
        self.assertIn("persist-credentials: false", self.source)
        self.assertNotIn("set -x", self.source)
        self.assertNotIn("upload-artifact@", self.source)

    def test_pr_and_branch_entrypoints(self):
        self.assertIn("  pull_request:", self.source)
        self.assertIn("  workflow_dispatch:", self.source)
        self.assertIn("research/stem-learning-investment-v18-20261016", self.source)

    def test_true_physical_and_independent_review(self):
        for filename in ("v18_original_feature_paired.py", "v18_original_independent_review.py",
                         "v18_paired_damage.py", "test_v18_original_independent_review"):
            self.assertIn(filename, self.source)
        self.assertIn("DENY_ALL_HISTORICAL_CALIBRATION_ONLY", self.source)
        self.assertIn("NO_INVEST_FROM_EXPOSED_HISTORICAL_CALIBRATION", self.source)

    def test_bash_blocks_parse(self):
        blocks = re.findall(r"(?m)^        run: \|\n((?:^          .*\n|^\n)*)", self.source)
        # Use source text, not an artificial shell fixture.
        self.assertGreaterEqual(len(blocks), 3)
        for block in blocks:
            proc = subprocess.run(["bash", "-n"], input=textwrap.dedent(block),
                                  text=True, capture_output=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
