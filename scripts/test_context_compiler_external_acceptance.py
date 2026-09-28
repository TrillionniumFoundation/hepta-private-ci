#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

import context_compiler_external_acceptance as acceptance


OID = "1" * 40
TREE = "2" * 40
BASE = "3" * 40
MERGE = "4" * 40
MERGE_TREE = "5" * 40
DIGEST = "a" * 64
NOW = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
ISSUED = "2029-12-31T00:00:00Z"
EXPIRES = "2030-12-31T00:00:00Z"


def evidence_record():
    return {
        "status": "passed",
        "artifactSha256": DIGEST,
        "issuer": "independent-owner:v1",
        "issuedAt": ISSUED,
        "expiresAt": EXPIRES,
        "sourceCommit": OID,
        "sourceTree": TREE,
        "mergeCommit": MERGE,
        "mergeTree": MERGE_TREE,
    }


def approval(identifier):
    return {
        "status": "approved",
        "approverId": identifier,
        "approvalSha256": DIGEST,
        "issuedAt": ISSUED,
        "sourceCommit": OID,
        "sourceTree": TREE,
        "baseCommit": BASE,
        "mergeCommit": MERGE,
        "mergeTree": MERGE_TREE,
    }


def receipt(mode="release"):
    required = acceptance.EVIDENCE_BY_MODE[mode]
    value = {
        "schema": "hepta.context-compiler.external-acceptance.v1",
        "mode": mode,
        "identities": {
            "sourceCommit": OID,
            "sourceTree": TREE,
            "baseCommit": BASE,
            "mergeCommit": MERGE,
            "mergeTree": MERGE_TREE,
        },
        "environment": {
            "environmentId": "context-compiler-acceptance:v1",
            "runnerIdentity": "self-hosted:context-acceptance-01",
            "runnerImageDigest": DIGEST,
            "hostImaeDigest": DIGEST,
            "kernelIdentity": "linux:acceptance-kernel-v1",
            "filesystemIdentity": "ext4:acceptance-volume-v1",
            "providerTenant": "provider:non-production-context-v1",
            "createdAt": ISSUED,
            "expiresAt": EXPIRES,
        },
        "evidence": {name: evidence_record() for name in required},
        "failpoints": {
            point_id: {
                "status": "passed",
                "observedState": sorted(states)[0],
                "artifactSha256": DIGEST,
            }
            for point_id, states in acceptance.load_matrix().items()
        },
        "approvals": {
            "security": approval("security-reviewer:v1"),
            "operator": approval("operator:v1") if mode in {"activation", "release"} else None,
            "release": approval("release-manager:v1") if mode == "release" else None,
        },
        "independentAcceptance": True,
        "activationApproved": mode in {"activation", "release"},
        "releaseApproved": mode == "release",
        "receiptSha256": "0" * 64,
    }
    value["receiptSha256"] = acceptance.canonical_sha256(value)
    return value


def validate(value, mode="release"):
    return acceptance.validate_receipt(
        value,
        mode=mode,
        expected_source=OID,
        expected_source_tree=TREE,
        expected_base=BASE,
        expected_merge=MERGE,
        expected_merge_tree=MERGE_TREE,
        now=NOW,
    )


class ExternalAcceptanceTests(unittest.TestCase):
    def test_release_receipt_binds_all_evidence_and_failpoints(self):
        report = validate(receipt())
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["activationApproved"])
        self.assertTrue(report["releaseApproved"])
        self.assertFalse(report["sourceStateMutationAuthorized"])
        self.assertEqual(report["failpointCount"], len(acceptance.load_matrix()))

    def test_each_mode_has_exact_approval_semantics(self):
        for mode in ("independent", "activation", "release"):
            report = validate(receipt(mode), mode)
            self.assertEqual(report["activationApproved"], mode != "independent")
            self.assertEqual(report["releaseApproved"], mode == "release")

    def test_digest_tampering_is_rejected(self):
        value = receipt()
        value["environment"]["providerTenant"] = "provider:other"
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)

    def test_identity_drift_is_rejected_even_with_recomputed_digest(self):
        value = receipt()
        value["evidence"]["providerE2E"]["sourceCommit"] = "9" * 40
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)

    def test_missing_or_wrong_failpoint_is_rejected(self):
        value = receipt()
        value["failpoints"].pop(next(iter(value["failpoints"])))
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)
        value = receipt()
        value["failpoints"]["transport.commit.before"]["observedState"] = "lease_settled"
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)

    def test_expired_evidence_is_rejected(self):
        value = receipt()
        value["evidence"]["tokenizerCustody"]["expiresAt"] = "2029-12-31T12:00:00Z"
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)

    def test_activation_cannot_be_claimed_without_operator_approval(self):
        value = receipt("activation")
        value["approvals"]["operator"] = None
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value, "activation")

    def test_future_approval_is_rejected(self):
        value = receipt()
        value["approvals"]["security"]["issuedAt"] = "2030-01-02T00:00:00Z"
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)

    def test_approval_roles_must_be_independent(self):
        value = receipt()
        value["approvals"]["operator"]["approverId"] = value["approvals"]["security"]["approverId"]
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)

    def test_unexpected_approval_is_rejected_for_independent_mode(self):
        value = receipt("independent")
        value["approvals"]["operator"] = approval("operator:v1")
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value, "independent")

    def test_failpoint_matrix_is_fail_closed(self):
        matrix = acceptance.load_matrix()
        self.assertIn(
            "may_have_dispatched_unresolved",
            matrix["provider.ack.after"],
        )
        self.assertNotIn("lease_settled", matrix["provider.ack.after"])
        source = json.loads(acceptance.MATRIX_PATH.read_text())
        source["rules"]["blindReplayForbidden"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(json.dumps(source))
            with self.assertRaises(acceptance.AcceptanceError):
                acceptance.load_matrix(path)

    def test_nonstandard_json_constants_are_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text('{"value": NaN}')
            with self.assertRaises(acceptance.AcceptanceError):
                acceptance.load_receipt(path)

    def test_sensitive_or_unknown_fields_are_rejected(self):
        value = receipt()
        value["api_key"] = "not-allowed"
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)
        value = receipt()
        value["evidence"]["providerE2E"]["credential"] = "not-allowed"
        value["receiptSha256"] = acceptance.canonical_sha256(value)
        with self.assertRaises(acceptance.AcceptanceError):
            validate(value)


if __name__ == "__main__":
    unittest.main()
