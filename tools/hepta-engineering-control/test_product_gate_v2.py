from pathlib import Path
import unittest
from unittest import mock

from control_engineering_v2 import product_gate


class ProductGateTests(unittest.TestCase):
    def identity(self):
        return {
            "repository_full_name": product_gate.EXPECTED_REPOSITORY,
            "repository_id": product_gate.EXPECTED_REPOSITORY_ID,
            "workflow_ref": product_gate.EXPECTED_WORKFLOW_PREFIX + "refs/pull/1/merge",
            "job_name": product_gate.EXPECTED_JOB,
            "run_id": 1,
            "run_attempt": 1,
            "event_name": "pull_request",
            "pull_request_number": 1,
        }

    def test_named_product_caller_uses_v2_orchestration_without_authority(self):
        source = "a" * 40
        tree = "b" * 40
        calls = {
            ("rev-parse", "HEAD"): source,
            ("rev-parse", "HEAD^{tree}"): tree,
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _repository, *args: calls[args],
        ):
            receipt = product_gate.build_product_receipt(
                Path("."),
                source_sha=source,
                **self.identity(),
            )
        self.assertEqual(
            receipt["namedProductCaller"], "control_engineering_v2.product_gate"
        )
        self.assertEqual(
            receipt["plan"]["integration_order"],
            ("product-probe:ECP-1-ENGINEERING-CONTROL-PLANE",),
        )
        self.assertGreaterEqual(
            receipt["canonicalWorkPackageInventory"]["packageCount"],
            1,
        )
        self.assertIn(
            "ECP-1-ENGINEERING-CONTROL-PLANE",
            receipt["canonicalWorkPackageInventory"]["engineeringPackageIds"],
        )
        self.assertEqual(
            receipt["canonicalPackageBinding"]["id"],
            "ECP-1-ENGINEERING-CONTROL-PLANE",
        )
        self.assertEqual(
            receipt["canonicalPackageBinding"]["developmentAfter"],
            ("DOC-2-DEFAULT-BRANCH-SELECTION",),
        )
        self.assertFalse(receipt["canonicalPackageBinding"]["authenticatedPredecessorCompletionSupplied"])
        self.assertFalse(receipt["authenticatedExternalSourceAdmission"])
        self.assertFalse(receipt["mergeAuthority"])
        self.assertFalse(receipt["releaseAuthority"])

    def test_ci_identity_mismatch_fails_closed(self):
        identity = self.identity()
        identity["repository_id"] = 0
        with self.assertRaisesRegex(ValueError, "repository_id_mismatch"):
            product_gate.build_product_receipt(
                Path("."),
                source_sha="a" * 40,
                **identity,
            )


if __name__ == "__main__":
    unittest.main()
