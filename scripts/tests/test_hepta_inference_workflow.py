from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUST_TEST = ROOT / "codex-rs/hepta-infer-core/src/semantic_control_tests.rs"
MAINTENANCE_WORKFLOW = ROOT / ".github/workflows/hepta-inference-maintenance.yml"
ARCHITECTURE_WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"
LEGACY_COMPAT_TEST = ROOT / "codex-rs/hepta-infer-core/tests/retained_history_maintenance.rs"


class InferenceMaintenanceWorkflowTests(unittest.TestCase):
    def test_retained_history_filters_select_real_ignored_tests(self) -> None:
        current_symbol = "semantic_journal_retained_history_curve"
        rust_source = RUST_TEST.read_text(encoding="utf-8")
        self.assertRegex(rust_source, rf"fn\s+{re.escape(current_symbol)}\s*\(")

        maintenance = MAINTENANCE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(current_symbol, maintenance)
        self.assertNotIn("post_compaction_multi_generation_curve", maintenance)
        self.assertIn("--minimum-tests 1", maintenance)
        self.assertIn("-- --ignored", maintenance)

        compatibility_symbol = "post_compaction_multi_generation_curve"
        architecture = ARCHITECTURE_WORKFLOW.read_text(encoding="utf-8")
        compatibility = LEGACY_COMPAT_TEST.read_text(encoding="utf-8")
        if current_symbol not in architecture:
            self.assertIn(compatibility_symbol, architecture)
            self.assertRegex(
                compatibility,
                rf"fn\s+{re.escape(compatibility_symbol)}\s*\(",
            )
            self.assertIn("compaction_performed\": false", compatibility)
            self.assertIn("legacy_filter_compatibility\": true", compatibility)
        self.assertIn("--minimum-tests 1", architecture)
        self.assertIn("-- --ignored", architecture)


if __name__ == "__main__":
    unittest.main()
