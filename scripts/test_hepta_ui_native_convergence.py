from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_hepta_ui_native_convergence.py"
SPEC = importlib.util.spec_from_file_location("check_hepta_ui_native_convergence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UiNativeConvergenceTests(unittest.TestCase):
    def test_exact_source_contract_is_fail_closed(self) -> None:
        evidence = MODULE.check_repository()
        self.assertEqual(evidence["status"], "structural-pass")
        self.assertRegex(evidence["implementationSourceSha"], r"^[0-9a-f]{40}$")
        self.assertEqual(evidence["workflow"], "ui-native-qualification.yml")
        self.assertGreaterEqual(evidence["retiredWorkflowCount"], 16)

    def test_release_claims_remain_independently_gated(self) -> None:
        evidence = MODULE.check_repository()
        self.assertIn(
            "release flags remain false pending independent review",
            evidence["limitations"],
        )


if __name__ == "__main__":
    unittest.main()
