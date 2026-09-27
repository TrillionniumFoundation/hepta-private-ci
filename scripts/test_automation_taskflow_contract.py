from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "automation_taskflow_contract.py"
SPEC = importlib.util.spec_from_file_location("automation_taskflow_contract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AutomationTaskFlowContractTests(unittest.TestCase):
    def test_repository_contract(self) -> None:
        result = MODULE.verify(ROOT)
        self.assertEqual(result["storeSchemaVersion"], 19)
        self.assertEqual(result["migrationVersions"], [17, 18, 19])
        self.assertTrue(result["repositoryControlledClosure"])
        self.assertTrue(result["boundedRecoveryFairnessVerified"])
        self.assertTrue(result["canonicalCircuitIngressVerified"])
        self.assertTrue(result["runtimeProfileReceiptBindingVerified"])
        self.assertTrue(result["crossHostOwnerBindingVerified"])
        self.assertTrue(result["externalReleaseGatesRemainFalse"])

    def test_failure_is_explicit(self) -> None:
        with self.assertRaises(MODULE.ContractError):
            MODULE.need(False, "expected failure")


if __name__ == "__main__":
    unittest.main()
