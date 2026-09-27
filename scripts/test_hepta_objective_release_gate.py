import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta-objective-release-gate.py")
SPEC = importlib.util.spec_from_file_location("objective_release_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

COMMIT = "1" * 40
TREE = "2" * 40
POLICY = Path(__file__).resolve().parents[1] / "docs/modules/objective.compiler/RELEASE_POLICY.json"


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.state = {
            "schema": "hepta.objective-compiler-current-state.v1",
            "schemaVersion": 1,
            "module": "objective.compiler",
            "implementationState": {},
            "truth": dict(self.policy["sourceTruthBeforeRelease"]),
            "requiredChecks": ["x"],
            "externalGates": ["y"],
        }
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, kind, receipts):
        if kind == "exact_head_qualification":
            return {
                "checkRuns": [
                    {"name": "objective", "runId": 11, "conclusion": "success"}
                ],
                "sourceMapDigest": "3" * 64,
                "currentStateDigest": "4" * 64,
            }
        if kind == "synthetic_merge_qualification":
            return {
                "baseCommit": "5" * 40,
                "mergeCommit": "6" * 40,
                "mergeTree": "7" * 40,
                "checkRunId": 12,
                "allChecksPassed": True,
            }
        if kind == "target_host_qualification":
            return {
                "hostProfileId": "objective.prod.x86_64.v1",
                "measurementDigest": "8" * 64,
                "storageQualificationDigest": "9" * 64,
                "worstCase257OracleCallsMeasured": True,
                "resourceBudgetsAccepted": True,
                "storageDurabilityAccepted": True,
            }
        if kind == "independent_review":
            return {
                "reviewerRole": "independent-security-reviewer",
                "reviewScopeDigest": "b" * 64,
                "independent": True,
                "noUnresolvedBlockingFindings": True,
            }
        if kind == "canary":
            return {
                "environment": "production-canary",
                "windowStartedAt": "2026-09-26T00:00:00Z",
                "windowEndedAt": "2026-09-26T01:00:00Z",
                "observedRequests": 1000,
                "hardConstraintViolations": 0,
                "rollbackDrillDigest": "c" * 64,
                "latencyBudgetsSatisfied": True,
                "errorBudgetsSatisfied": True,
            }
        if kind == "rollback_authority":
            return {
                "authorityRole": "objective-rollback-owner",
                "rollbackTargetCommit": "d" * 40,
                "procedureDigest": "d" * 64,
                "drillReceiptDigest": "e" * 64,
                "ready": True,
            }
        if kind == "promotion":
            return {
                "fromEnvironment": "production-canary",
                "toEnvironment": "production",
                "approvedByRole": "objective-promotion-owner",
                "canaryReceiptDigest": receipts["canary"]["receiptDigest"],
                "approved": True,
            }
        if kind == "release_authority":
            return {
                "authorityRole": "objective-release-owner",
                "targetEnvironment": "production",
                "approvalId": "approval.objective.20260926",
                "promotionReceiptDigest": receipts["promotion"]["receiptDigest"],
                "rollbackAuthorityReceiptDigest": receipts["rollback_authority"][
                    "receiptDigest"
                ],
                "approved": True,
            }
        raise AssertionError(kind)

    def write_receipts(self, issuer_override=None):
        issuer_override = issuer_override or {}
        policy_digest = gate.sha256_value(self.policy)
        receipts = {}
        filenames = {}
        for index, row in enumerate(self.policy["receiptKinds"], start=1):
            kind = row["kind"]
            receipt = {
                "schema": gate.RECEIPT_SCHEMA,
                "schemaVersion": 1,
                "module": "objective.compiler",
                "kind": kind,
                "candidateCommit": COMMIT,
                "candidateTree": TREE,
                "releasePolicyDigest": policy_digest,
                "issuer": issuer_override.get(kind, f"issuer-{index}-{kind}"),
                "issuedAt": f"2026-09-26T00:{index:02d}:00Z",
                "evidenceDigest": f"{index:x}" * 64,
                "accepted": True,
                "dependencies": {
                    dependency: receipts[dependency]["receiptDigest"]
                    for dependency in row["dependsOn"]
                },
                "payload": self.payload(kind, receipts),
            }
            receipt["receiptDigest"] = gate.sha256_value(receipt)
            receipts[kind] = receipt
            filenames[kind] = row["fileName"]
            (self.root / row["fileName"]).write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        return receipts, filenames

    def test_complete_chain_grants_release_readiness(self):
        receipts, _ = self.write_receipts()
        result = gate.release_verify(self.state, self.policy, self.root, COMMIT, TREE)
        self.assertTrue(result["releaseGranted"])
        self.assertEqual(
            result["receiptDigests"]["release_authority"],
            receipts["release_authority"]["receiptDigest"],
        )
        self.assertEqual(
            result["releaseTruth"], self.policy["releaseTruthAfterAllReceipts"]
        )

    def test_tampered_receipt_fails_closed(self):
        _, filenames = self.write_receipts()
        path = self.root / filenames["target_host_qualification"]
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["payload"]["resourceBudgetsAccepted"] = False
        path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(gate.GateError):
            gate.validate_receipts(self.policy, self.root, COMMIT, TREE)

    def test_independent_and_release_issuers_must_differ(self):
        shared = "same-authority"
        self.write_receipts(
            {
                "independent_review": shared,
                "release_authority": shared,
            }
        )
        with self.assertRaises(gate.GateError):
            gate.validate_receipts(self.policy, self.root, COMMIT, TREE)

    def test_source_ci_rejects_released_truth(self):
        self.state["truth"] = dict(self.policy["releaseTruthAfterAllReceipts"])
        with self.assertRaises(gate.GateError):
            gate.source_verify(self.state, self.policy)

    def test_missing_receipt_never_grants_release(self):
        _, filenames = self.write_receipts()
        (self.root / filenames["canary"]).unlink()
        with self.assertRaises(gate.GateError):
            gate.validate_receipts(self.policy, self.root, COMMIT, TREE)


if __name__ == "__main__":
    unittest.main()
