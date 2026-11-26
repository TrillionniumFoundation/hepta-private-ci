#!/usr/bin/env python3
"""Keep platform-specific Bazel workflow options scoped to their jobs."""

from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "bazel.yml"


class BazelWorkflowTest(unittest.TestCase):
    def test_windows_clippy_skips_only_declared_incompatible_targets(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        clippy = workflow.split("  clippy:\n", 1)[1].split(
            "  verify-release-build:\n", 1
        )[0]
        windows_block = re.search(
            r'if \[\[ "\$\{RUNNER_OS\}" == "Windows" \]\]; then(.*?)\n          fi',
            clippy,
            re.DOTALL,
        )
        self.assertIsNotNone(windows_block)
        assert windows_block is not None
        self.assertIn("--platforms=//:windows_x86_64_msvc", windows_block.group(1))
        self.assertIn("--skip_incompatible_explicit_targets", windows_block.group(1))
        self.assertEqual(clippy.count("--skip_incompatible_explicit_targets"), 1)


if __name__ == "__main__":
    unittest.main()
