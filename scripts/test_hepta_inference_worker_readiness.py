"""Tests for inference.worker exact-candidate readiness receipt."""

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


class InferenceWorkerReadinessTests(unittest.TestCase):
    def test_repository_receipt_is_fail_closed_and_exact(self):
        receipt = MODULE.build_receipt()
        self.assertEqual(receipt["schema"], "hepta.inference-worker-candidate-receipt.v1")
        self.assertEqual(receipt["module"], "inference.worker")
        self.assertEqual(len(receipt["candidate"]["commit"]), 40)
        self.assertEqual(len(receipt["candidate"]["tree"]), 40)
        self.assertEqual(len(receipt["candidate"]["workerTree"]), 40)
        self.assertTrue(receipt["repositoryControlledGaps"])
        self.assertTrue(receipt["externalEvidenceGates"])
        self.assertTrue(all(value is False for value in receipt["claimBoundary"].values()))
        self.assertIn(
            "receipt is not hardware qualification",
            receipt["limitations"],
        )

    def test_wrong_expected_sha_rejects(self):
        with self.assertRaisesRegex(ValueError, "does not match expected candidate"):
            MODULE.build_receipt("0" * 40)


if __name__ == "__main__":
    unittest.main()
