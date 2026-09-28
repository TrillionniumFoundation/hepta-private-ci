from dataclasses import asdict, replace
import json
import unittest

from control_engineering_v2.capacity_policy import EngineeringCapacityDecision
from control_engineering_v2.control_plane import semantic_digest
from control_engineering_v2.evidence import HmacTrustStore
from control_engineering_v2.external_runtime import (
    ExternalProviderEndpoint,
    ExternalReceiptClient,
    ProductionProviderSet,
)
from control_engineering_v2.quality_gate import QualityGateReceipt, verify_quality_gate
from control_engineering_v2.release_qualification import (
    DeploymentObservationReceipt,
    IndependentReviewAcceptanceReceipt,
    OperatorAcceptanceReceipt,
    PostMergeMainReceipt,
    ReleaseQualificationFacts,
    RollbackRehearsalReceipt,
    evaluate_release_qualification,
    verify_release_receipts,
)
from control_engineering_v2.status import build_status, verify_status_digest


class ExternalAndReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 2_000_000_000
        self.source = "1" * 40
        self.tree = "2" * 40
        self.repository = "TrillionniumFoundation/hepta-private-ci"
        self.trust = HmacTrustStore(
            {
                ("ci_executor", "ci-key"): b"ci",
                ("independent_evaluator", "review-key"): b"review",
                ("deployment_observer", "deploy-key"): b"deploy",
                ("rollback_observer", "rollback-key"): b"rollback",
                ("operator_acceptance_authority", "operator-key"): b"operator",
            }
        )

    def sign(self, value):
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_external_provider_response_is_nonce_source_and_digest_bound(self):
        class Transport:
            def post(inner_self, endpoint, body):
                request = json.loads(body)
                payload = {"result": "ok", "source": request["sourceCommit"]}
                return json.dumps(
                    {
                        "schema": "hepta.control-engineering-provider-response.v1",
                        "service": request["service"],
                        "operation": request["operation"],
                        "nonce": request["nonce"],
                        "requestDigest": request["requestDigest"],
                        "providerObservationId": "observation-a",
                        "providerObservedUnixNs": self.now,
                        "providerExpiresUnixNs": self.now + 1_000_000_000,
                        "payload": payload,
                        "payloadDigest": semantic_digest(payload),
                    }
                ).encode()

        endpoint = ExternalProviderEndpoint(
            "distributed-lease-provider",
            "https://provider.example/v1/receipt",
            "a" * 64,
        )
        observed = ExternalReceiptClient(endpoint, transport=Transport()).invoke(
            "acquire-fence",
            {"leaseId": "lease-a"},
            source_commit=self.source,
            source_tree=self.tree,
            now_ns=self.now,
            nonce="nonce-a",
        )
        self.assertEqual(observed.payload["result"], "ok")
        self.assertFalse(observed.runtime_authority)

    def test_provider_roles_must_be_distinct(self):
        def endpoint(name):
            return ExternalProviderEndpoint(
                name, "https://provider.example/v1", "a" * 64
            )

        values = [endpoint(f"provider-{index}") for index in range(7)]
        self.assertNotEqual(ProductionProviderSet(*values).configuration_digest, "0" * 64)
        with self.assertRaisesRegex(ValueError, "production_provider_role_collision"):
            ProductionProviderSet(values[0], values[0], *values[2:])

    def test_quality_gate_enforces_real_report_thresholds(self):
        receipt = self.sign(
            QualityGateReceipt(
                self.repository,
                self.source,
                self.tree,
                300,
                65_536,
                65_536,
                65_536,
                50,
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "1" * 64,
                "ci_executor",
                "ci-key",
                self.now,
                self.now + 1_000_000_000,
            )
        )
        decision = verify_quality_gate(
            receipt,
            self.trust,
            expected_repository=self.repository,
            expected_source_commit=self.source,
            expected_source_tree=self.tree,
            now_ns=self.now,
        )
        self.assertTrue(decision.qualified)
        low = self.sign(replace(receipt, line_coverage_q16=0, signature=""))
        low_decision = verify_quality_gate(
            low,
            self.trust,
            expected_repository=self.repository,
            expected_source_commit=self.source,
            expected_source_tree=self.tree,
            now_ns=self.now,
        )
        self.assertIn("line_coverage_below_threshold", low_decision.blockers)

    def test_release_receipts_require_independent_review_and_exact_main(self):
        quality_digest = "a" * 64
        provider_digest = "b" * 64
        post = self.sign(
            PostMergeMainReceipt(
                self.repository,
                self.source,
                self.tree,
                "main",
                123,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                quality_digest,
                "ci_executor",
                "ci-key",
                self.now,
                self.now + 1_000_000_000,
            )
        )
        review = self.sign(
            IndependentReviewAcceptanceReceipt(
                self.repository,
                self.source,
                self.tree,
                "generator-a",
                "reviewer-b",
                "f" * 64,
                "independent_evaluator",
                "review-key",
                self.now,
                self.now + 1_000_000_000,
                True,
            )
        )
        deployment = self.sign(
            DeploymentObservationReceipt(
                self.repository,
                self.source,
                self.tree,
                "1" * 64,
                provider_digest,
                "2" * 64,
                "3" * 64,
                "deployment_observer",
                "deploy-key",
                self.now,
                self.now + 1_000_000_000,
                True,
            )
        )
        deployment_receipt_digest = semantic_digest(asdict(deployment))
        rollback = self.sign(
            RollbackRehearsalReceipt(
                self.repository,
                self.source,
                self.tree,
                "1" * 64,
                "4" * 64,
                "5" * 64,
                "6" * 64,
                30,
                "rollback_observer",
                "rollback-key",
                self.now,
                self.now + 1_000_000_000,
                True,
            )
        )
        rollback_receipt_digest = semantic_digest(asdict(rollback))
        operator = self.sign(
            OperatorAcceptanceReceipt(
                self.repository,
                self.source,
                self.tree,
                "1" * 64,
                deployment_receipt_digest,
                rollback_receipt_digest,
                "operator-c",
                "7" * 64,
                "operator_acceptance_authority",
                "operator-key",
                self.now,
                self.now + 1_000_000_000,
                True,
            )
        )
        verified = verify_release_receipts(
            post_merge=post,
            review=review,
            deployment=deployment,
            rollback=rollback,
            operator=operator,
            trust_store=self.trust,
            expected_repository=self.repository,
            expected_source_commit=self.source,
            expected_source_tree=self.tree,
            expected_quality_gate_digest=quality_digest,
            expected_provider_configuration_digest=provider_digest,
            now_ns=self.now,
        )
        self.assertEqual(verified.deployment_digest, deployment_receipt_digest)

    def test_status_remains_false_while_external_evidence_is_absent(self):
        release = evaluate_release_qualification(
            ReleaseQualificationFacts(
                repository=self.repository,
                source_commit=self.source,
                source_tree=self.tree,
                pull_request_source_product_digest="",
                pull_request_merge_product_digest="",
                pull_request_pair_digest="",
                post_merge_main_digest="",
                quality_gate_digest="",
                distributed_fence_digest="",
                external_audit_anchor_digest="",
                key_custody_digest="",
                independent_completion_digest="",
                terminal_observation_digest="",
                independent_review_digest="",
                deployment_digest="",
                rollback_digest="",
                operator_acceptance_digest="",
            )
        )
        capacity = EngineeringCapacityDecision("nominal", False, (), (), "8" * 64)
        status = build_status(release, capacity)
        self.assertFalse(status.production_implementation)
        self.assertFalse(status.deployment_ready)
        verify_status_digest(status)


if __name__ == "__main__":
    unittest.main()
