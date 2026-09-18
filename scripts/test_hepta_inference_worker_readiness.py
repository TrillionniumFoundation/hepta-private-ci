"Tests for inference.worker exact-candidate readiness and hardware evidence contracts."

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/hepta-inference-worker-readiness.py"
SPEC = importlib.util.spec_from_file_location("hepta_inference_worker_readiness", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_hardware_fixture():
    value = MODULE.hardware_evidence_template()
    value["candidate"]["readinessReceiptDigest"] = "a" * 64
    value["host"] = {
        "hostClass": "fixture-target-host",
        "runnerId": "fixture-runner",
        "os": "fixture-os",
        "arch": "fixture-arch",
        "attestationDigest": "b" * 64,
    }
    for index, key in enumerate(MODULE.MODEL_DIGESTS, start=1):
        value["model"][key] = f"{index:x}" * 64
    for index, key in enumerate(MODULE.ISOLATION_CONTROLS, start=1):
        value["isolation"][key] = {
            "status": "proved",
            "owner": f"fixture-owner-{index}",
            "evidenceDigest": f"{index + 7:x}" * 64,
        }
    for index, row in enumerate(value["scenarios"], start=1):
        row["status"] = "passed"
        row["evidenceDigest"] = f"{(index % 6) + 9:x}" * 64
        row["measurements"] = {"fixture": index}
    value["observer"] = {
        "identity": "fixture-independent-observer",
        "independent": True,
        "evidenceDigest": "e" * 64,
    }
    value["result"] = {
        "qualified": True,
        "qualifiedAt": "2026-09-18T00:00:00Z",
    }
    return value


class InferenceWorkerReadinessTests(unittest.TestCase):
    def test_repository_receipt_is_fail_closed_and_exact(self):
        receipt = MODULE.build_receipt()
        self.assertEqual(
            receipt["schema"], "hepta.inference-worker-candidate-receipt.v2"
        )
        self.assertEqual(receipt["module"], "inference.worker")
        self.assertEqual(len(receipt["candidate"]["commit"]), 40)
        self.assertEqual(len(receipt["candidate"]["tree"]), 40)
        self.assertEqual(len(receipt["candidate"]["workerTree"]), 40)
        self.assertEqual(
            receipt["sourceBinding"]["candidateWorkerTree"],
            receipt["candidate"]["workerTree"],
        )
        self.assertTrue(receipt["repositoryControlledGaps"])
        self.assertTrue(receipt["externalEvidenceGates"])
        self.assertTrue(
            all(value is False for value in receipt["claimBoundary"].values())
        )
        self.assertIn(
            "receipt is not hardware qualification",
            receipt["limitations"],
        )

    def test_wrong_expected_sha_rejects(self):
        with self.assertRaisesRegex(ValueError, "does not match expected candidate"):
            MODULE.build_receipt("0" * 40)

    def test_tested_receipt_requires_named_library_checks(self):
        with self.assertRaisesRegex(ValueError, "missing required checks"):
            MODULE.build_receipt(evidence_class="source-head-tested")
        receipt = MODULE.build_receipt(
            evidence_class="source-head-tested",
            passed_checks=list(MODULE.REQUIRED_TEST_CHECKS),
        )
        self.assertEqual(
            receipt["qualificationEvidence"]["class"], "source-head-tested"
        )
        self.assertEqual(
            set(receipt["qualificationEvidence"]["passedChecks"]),
            set(MODULE.REQUIRED_TEST_CHECKS),
        )

    def test_hardware_template_is_fail_closed(self):
        template = MODULE.hardware_evidence_template()
        self.assertFalse(template["result"]["qualified"])
        self.assertTrue(
            all(row["status"] == "pending" for row in template["scenarios"])
        )
        with self.assertRaises(ValueError):
            MODULE.validate_hardware_evidence(template)

    def test_complete_hardware_fixture_validates_structurally(self):
        result = MODULE.validate_hardware_evidence(valid_hardware_fixture())
        self.assertEqual(
            result["status"], "PASS_INFERENCE_WORKER_HARDWARE_EVIDENCE_STRUCTURE"
        )
        self.assertEqual(result["scenarios"], len(MODULE.HARDWARE_SCENARIOS))
        self.assertEqual(
            result["isolationControls"], len(MODULE.ISOLATION_CONTROLS)
        )

    def test_missing_hardware_scenario_rejects(self):
        value = valid_hardware_fixture()
        value["scenarios"].pop()
        with self.assertRaisesRegex(ValueError, "scenario set mismatch"):
            MODULE.validate_hardware_evidence(value)


if __name__ == "__main__":
    unittest.main()
