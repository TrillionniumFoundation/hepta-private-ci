from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUST_TEST = ROOT / "codex-rs/hepta-infer-core/src/semantic_control_tests.rs"
WORKFLOWS = (
    ROOT / ".github/workflows/hepta-inference-maintenance.yml",
    ROOT / ".github/workflows/hepta-architecture-convergence.yml",
)


class InferenceMaintenanceWorkflowTests(unittest.TestCase):
    def test_retained_history_filter_selects_the_actual_ignored_test(self) -> None:
        rust_source = RUST_TEST.read_text(encoding="utf-8")
        symbol = "semantic_journal_retained_history_curve"
        self.assertRegex(rust_source, rf"fn\s+{re.escape(symbol)}\s*\(")

        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn(symbol, source)
                self.assertNotIn("post_compaction_multi_generation_curve", source)
                self.assertIn("--minimum-tests 1", source)
                self.assertIn("-- --ignored", source)


if __name__ == "__main__":
    unittest.main()
