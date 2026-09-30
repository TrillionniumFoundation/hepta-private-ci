import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-objective-release-gate.py")
SPEC = importlib.util.spec_from_file_location("objective_release_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

PROTECTED_SCRIPT = SCRIPT.with_name("hepta-objective-protected-release-verify.py")
PROTECTED_SPEC = importlib.util.spec_from_file_location(
    "objective_protected_release_verify", PROTECTED_SCRIPT
)
assert PROTECTED_SPEC is not None and PROTECTED_SPEC.loader is not None
protected = importlib.util.module_from_spec(PROTECTED_SPEC)
PROTECTED_SPEC.loader.exec_module(protected)

COMMIT = "1" * 40
TREE = "2" * 40
POLICY = (
    Path(__file__).resolve().parents[1]
    / "docs/modules/objective.compiler/RELEASE_POLICY.json"
)


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.state = {
            "schema": "hepta.objective-compiler-current-state.v2",
            "schemaVersion": 2,
            "module": "objective.compiler",
            "implementationState": {},
            "evidenceProjection": {
                "schema": "hepta.objective-evidence-projection.v2",
                "manualPassFieldsForbidden": True,
            },
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

    def test_fabricated_complete_chain_proves_only_consistency(self):
        # Every issuer, evidence digest, check run and approval below is invented.
        # A fully self-consistent chain must never promote those labels to facts.
        receipts, _ = self.write_receipts()
        result = gate.release_verify(self.state, self.policy, self.root, COMMIT, TREE)
        self.assertTrue(result["receiptChainConsistent"])
        self.assertFalse(result["receiptAuthenticityVerified"])
        self.assertFalse(result["releaseGranted"])
        self.assertEqual(result["externalAuthorityVerification"], "required")
        self.assertEqual(
            result["receiptDigests"]["release_authority"],
            receipts["release_authority"]["receiptDigest"],
        )
        self.assertEqual(
            result["releaseTruth"], self.policy["sourceTruthBeforeRelease"]
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

    def test_current_repository_v2_state_is_accepted_without_promoting_truth(self):
        actual = gate.load_json(gate.STATE_PATH)
        gate.source_verify(actual, self.policy)
        self.assertTrue(all(value is False for value in actual["truth"].values()))

    def test_old_state_or_manual_dynamic_claims_fail_closed(self):
        self.state["schema"] = "hepta.objective-compiler-current-state.v1"
        self.state["schemaVersion"] = 1
        with self.assertRaises(gate.GateError):
            gate.validate_state(self.state, self.policy)
        self.state["schema"] = "hepta.objective-compiler-current-state.v2"
        self.state["schemaVersion"] = 2
        self.state["implementationState"]["checksPassed"] = True
        with self.assertRaises(gate.GateError):
            gate.validate_state(self.state, self.policy)
        self.state["implementationState"] = {}
        self.state["evidenceProjection"]["manualPassFieldsForbidden"] = False
        with self.assertRaises(gate.GateError):
            gate.validate_state(self.state, self.policy)

    def test_missing_receipt_never_grants_release(self):
        _, filenames = self.write_receipts()
        (self.root / filenames["canary"]).unlink()
        with self.assertRaises(gate.GateError):
            gate.validate_receipts(self.policy, self.root, COMMIT, TREE)

    def protected_inputs(self):
        trusted, candidate = self.root / "trusted", self.root / "candidate"
        for root in (trusted, candidate):
            directory = root / "docs/modules/objective.compiler"
            directory.mkdir(parents=True)
            (directory / "RELEASE_POLICY.json").write_text(json.dumps(self.policy))
        (candidate / "docs/modules/objective.compiler/CURRENT_STATE.json").write_text(
            json.dumps(self.state)
        )
        (trusted / "scripts").mkdir()
        (trusted / "scripts/hepta-objective-release-gate.py").write_text(
            SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (candidate / "scripts").mkdir()
        (candidate / "scripts/hepta-objective-release-gate.py").write_text(
            "raise RuntimeError('candidate verifier must never execute')\n"
        )
        return trusted, candidate, self.root / "readiness.json"

    @staticmethod
    def observed_git(_root, *args):
        # Source identity is mocked here; these tests exercise data handling,
        # not hosted execution, signatures, or external authority authentication.
        if args == ("rev-parse", "HEAD"):
            return COMMIT
        if args == ("rev-parse", "HEAD^{tree}"):
            return TREE
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    def test_protected_verifier_accepts_external_data_without_granting_release(self):
        self.write_receipts()
        trusted, candidate, output = self.protected_inputs()
        with mock.patch.object(protected, "git", side_effect=self.observed_git):
            result = protected.verify(trusted, candidate, COMMIT, output, self.root)
        self.assertFalse(result["candidateCodeExecuted"])
        self.assertFalse(result["receiptAuthenticityVerified"])
        self.assertFalse(result["releaseGranted"])
        self.assertTrue(result["releaseReadiness"]["receiptChainConsistent"])
        self.assertEqual(result["receiptDataSource"], "external_directory")
        self.assertEqual(
            result["receiptFilesSha256"],
            {
                row["fileName"]: protected.sha256_file(self.root / row["fileName"])
                for row in self.policy["receiptKinds"]
            },
        )

    def test_protected_verifier_rejects_candidate_owned_receipt_directory(self):
        trusted, candidate, output = self.protected_inputs()
        receipts = candidate / "qualification/objective.compiler/receipts"
        receipts.mkdir(parents=True)
        with mock.patch.object(protected, "git", side_effect=self.observed_git):
            with self.assertRaisesRegex(protected.ProtectedReleaseError, "outside"):
                protected.verify(trusted, candidate, COMMIT, output, receipts)
        self.assertFalse(output.exists())

    def test_protected_verifier_rejects_symlinked_receipt(self):
        _, filenames = self.write_receipts()
        trusted, candidate, output = self.protected_inputs()
        path = self.root / filenames["canary"]
        retained = path.with_suffix(".retained")
        path.rename(retained)
        path.symlink_to(retained.name)
        with mock.patch.object(protected, "git", side_effect=self.observed_git):
            with self.assertRaisesRegex(
                protected.ProtectedReleaseError, "regular file"
            ):
                protected.verify(trusted, candidate, COMMIT, output, self.root)
        self.assertFalse(output.exists())

    def test_protected_verifier_rejects_an_older_granting_verifier_result(self):
        self.write_receipts()
        trusted, candidate, output = self.protected_inputs()
        granting = {
            "releaseGranted": True,
            "releaseTruth": self.policy["releaseTruthAfterAllReceipts"],
            "receiptAuthenticityVerified": False,
        }
        with (
            mock.patch.object(protected, "git", side_effect=self.observed_git),
            mock.patch.object(protected, "load_gate", return_value=gate),
            mock.patch.object(gate, "release_verify", return_value=granting),
        ):
            with self.assertRaisesRegex(
                protected.ProtectedReleaseError, "must not grant"
            ):
                protected.verify(trusted, candidate, COMMIT, output, self.root)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
