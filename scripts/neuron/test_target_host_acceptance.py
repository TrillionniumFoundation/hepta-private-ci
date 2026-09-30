import copy
import unittest

import target_host_acceptance as acceptance


SOURCE = "1" * 40
BASE = "2" * 40
SHA256 = "a" * 64


def outcome():
    return {
        "status": "passed",
        "freshProcessRestart": True,
        "exactOperationKeyStable": True,
        "physicalEffectCount": 1,
        "logSha256": SHA256,
    }


def valid_receipt():
    return {
        "schema": acceptance.SCHEMA,
        "sourceSha": SOURCE,
        "baseSha": BASE,
        "testedTreeSha256": SHA256,
        "binarySha256": SHA256,
        "workflowRunId": "1234",
        "workflowRunAttempt": 1,
        "sourceMutation": False,
        "productionActivation": False,
        "release": False,
        "environment": {
            "runnerName": "target-host-01",
            "runnerImage": "hepta-target-v1",
            "kernel": "Linux 6.x",
            "targetTriple": "x86_64-unknown-linux-gnu",
            "deviceIdentity": "gpu-device-attestation-01",
        },
        "authenticatedArtifacts": {
            key: SHA256 for key in acceptance.REQUIRED_ARTIFACT_DIGESTS
        }
        | {
            "selectionAuthority": "independent-selection-receipt-01",
            "revocationChecked": True,
        },
        "operation": {
            "tickId": "tick-01",
            "inputDigest": "input-digest-01",
            "generation": 2,
            "providerOperationId": "provider-op-01",
        },
        "provider": {
            "backend": "native-provider",
            "receiptSha256": SHA256,
            "queryOnlyRecovery": True,
            "physicalEffectCount": 1,
            "duplicateEffectCount": 0,
        },
        "durableCuts": {
            cut: outcome() for cut in acceptance.REQUIRED_DURABLE_CUTS
        },
        "lifecycle": {
            step: True for step in acceptance.REQUIRED_LIFECYCLE
        },
        "faultMatrix": {
            fault: {"status": "passed", "logSha256": SHA256}
            for fault in acceptance.REQUIRED_FAULTS
        },
        "retention": {
            "successHistoryRetained": True,
            "failureTombstonesRetained": True,
            "dispatchHistoryRetained": True,
            "witnessLineageRetained": True,
            "historicalQueriesPassed": True,
            "deletionNonResurrectionPassed": True,
        },
        "rollbackBoundary": {
            "gapId": "NR-SEC-ROLLBACK-001",
            "disposition": "closed_by_independent_anchor",
            "evidenceReference": "independent-frontier-receipt-01",
        },
        "independentReview": {
            "reviewerIdentity": "independent-reviewer-01",
            "accepted": True,
            "reviewSha256": SHA256,
        },
    }


class TargetHostAcceptanceTests(unittest.TestCase):
    def test_complete_receipt_proves_product_execution_without_activation(self):
        manifest = acceptance.validate_receipt(valid_receipt(), SOURCE, BASE)
        self.assertTrue(manifest["productExecutionProved"])
        self.assertTrue(manifest["independentAcceptance"])
        self.assertFalse(manifest["productionActivation"])
        self.assertFalse(manifest["release"])
        self.assertEqual(set(manifest["durableCutsPassed"]), set(acceptance.REQUIRED_DURABLE_CUTS))
        self.assertEqual(set(manifest["faultsPassed"]), set(acceptance.REQUIRED_FAULTS))

    def test_missing_durable_cut_is_rejected(self):
        receipt = valid_receipt()
        del receipt["durableCuts"]["dispatchFence"]
        with self.assertRaisesRegex(acceptance.EvidenceError, "durable cut set mismatch"):
            acceptance.validate_receipt(receipt, SOURCE, BASE)

    def test_duplicate_provider_effect_is_rejected(self):
        receipt = valid_receipt()
        receipt["provider"]["physicalEffectCount"] = 2
        receipt["provider"]["duplicateEffectCount"] = 1
        with self.assertRaisesRegex(acceptance.EvidenceError, "effect count"):
            acceptance.validate_receipt(receipt, SOURCE, BASE)

    def test_open_joint_rollback_gap_is_rejected(self):
        receipt = valid_receipt()
        receipt["rollbackBoundary"]["disposition"] = "open_security_gap"
        with self.assertRaisesRegex(acceptance.EvidenceError, "rollback gap remains open"):
            acceptance.validate_receipt(receipt, SOURCE, BASE)

    def test_source_identity_mismatch_is_rejected(self):
        with self.assertRaisesRegex(acceptance.EvidenceError, "source SHA mismatch"):
            acceptance.validate_receipt(valid_receipt(), "3" * 40, BASE)

    def test_fixture_is_not_mutated_by_validation(self):
        receipt = valid_receipt()
        before = copy.deepcopy(receipt)
        acceptance.validate_receipt(receipt, SOURCE, BASE)
        self.assertEqual(receipt, before)


if __name__ == "__main__":
    unittest.main()
