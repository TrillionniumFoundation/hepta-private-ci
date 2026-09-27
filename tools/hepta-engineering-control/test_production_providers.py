from dataclasses import asdict, replace
import unittest

from control_engineering_v2 import HmacTrustStore, semantic_digest
from control_engineering_v2.production_providers import (
    DeploymentObservationReceipt,
    ExternalProviderDescriptor,
    OperatorAcceptanceReceipt,
    ProductionEvidenceBundle,
    ProductionProviderSet,
    RollbackRehearsalReceipt,
    verify_production_acceptance_bundle,
    verify_production_evidence_bundle,
    verify_production_provider_set,
)


class ProductionProviderTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.commit = "a" * 40
        self.tree = "b" * 40
        self.target = "9" * 64
        self.trust = HmacTrustStore(
            {
                ("deployment_observer", "deploy-key"): b"deploy",
                ("rollback_rehearsal_observer", "deploy-key"): b"deploy",
                ("operator_acceptance_authority", "operator-key"): b"operator",
            }
        )
        descriptor = ExternalProviderDescriptor
        self.providers = ProductionProviderSet(
            descriptor(
                "fence-provider",
                "distributed_fence",
                "https",
                True,
                False,
                "fence-domain",
                "fence-key",
                "1" * 64,
            ),
            descriptor(
                "audit-provider",
                "immutable_audit_log",
                "https",
                True,
                False,
                "audit-domain",
                "audit-key",
                "2" * 64,
            ),
            descriptor(
                "custody-provider",
                "key_custody",
                "pkcs11",
                True,
                False,
                "custody-domain",
                "custody-key",
                "3" * 64,
            ),
            descriptor(
                "completion-provider",
                "completion_observer",
                "https",
                True,
                False,
                "completion-domain",
                "completion-key",
                "4" * 64,
            ),
            descriptor(
                "terminal-provider",
                "terminal_integration_observer",
                "https",
                True,
                False,
                "terminal-domain",
                "terminal-key",
                "5" * 64,
            ),
            descriptor(
                "review-provider",
                "semantic_review",
                "https",
                True,
                False,
                "review-domain",
                "review-key",
                "6" * 64,
            ),
            descriptor(
                "deployment-provider",
                "deployment_controller",
                "https",
                True,
                False,
                "deployment-domain",
                "deploy-key",
                "7" * 64,
            ),
            descriptor(
                "operator-provider",
                "operator_acceptance",
                "https",
                True,
                False,
                "operator-domain",
                "operator-key",
                "8" * 64,
            ),
        )

    def sign(self, value):
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def evidence(self, provider_digest):
        return ProductionEvidenceBundle(
            self.commit,
            self.tree,
            self.target,
            provider_digest,
            "0" * 64,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "4" * 64,
            "5" * 64,
            "6" * 64,
            "7" * 64,
            "8" * 64,
            "9" * 64,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
        )

    def test_non_fixture_bundle_requires_all_evidence_and_operator(self):
        provider_digest = verify_production_provider_set(self.providers)
        evidence = self.evidence(provider_digest)
        evidence_digest = semantic_digest(asdict(evidence))
        deployment = self.sign(
            DeploymentObservationReceipt(
                "deploy-operation",
                self.commit,
                self.tree,
                self.target,
                "e" * 64,
                self.providers.deployment_controller.configuration_digest,
                self.providers.deployment_controller.provider_id,
                "f" * 64,
                "deployment_observer",
                "deploy-key",
                self.now,
                self.now + 1_000_000_000,
                True,
                False,
            )
        )
        rollback = self.sign(
            RollbackRehearsalReceipt(
                "rollback-operation",
                self.commit,
                self.tree,
                self.target,
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                self.providers.deployment_controller.provider_id,
                "e" * 64,
                "rollback_rehearsal_observer",
                "deploy-key",
                self.now,
                self.now + 1_000_000_000,
                True,
                False,
                True,
            )
        )
        deployment_digest = semantic_digest(asdict(deployment))
        rollback_digest = semantic_digest(asdict(rollback))
        acceptance = self.sign(
            OperatorAcceptanceReceipt(
                self.commit,
                self.tree,
                self.target,
                deployment_digest,
                rollback_digest,
                evidence_digest,
                provider_digest,
                "operator-a",
                "operator_acceptance_authority",
                "operator-key",
                self.now,
                self.now + 1_000_000_000,
                True,
            )
        )
        decision = verify_production_acceptance_bundle(
            self.providers,
            evidence,
            deployment,
            rollback,
            acceptance,
            self.trust,
            expected_source_commit=self.commit,
            expected_source_tree=self.tree,
            expected_target_digest=self.target,
            now_ns=self.now,
        )
        self.assertTrue(decision.deployment_accepted)
        self.assertEqual(
            decision.production_evidence_bundle_digest,
            evidence_digest,
        )
        self.assertFalse(decision.production_implementation)
        self.assertFalse(decision.release_authority)

    def test_fixture_role_or_key_custody_collision_is_never_eligible(self):
        bad = replace(
            self.providers,
            key_custody=replace(self.providers.key_custody, fixture=True),
        )
        with self.assertRaisesRegex(ValueError, "external_provider_not_independent"):
            verify_production_provider_set(bad)
        collision = replace(
            self.providers,
            completion_observer=replace(
                self.providers.completion_observer,
                signing_identity=self.providers.key_custody.signing_identity,
            ),
        )
        with self.assertRaisesRegex(
            ValueError,
            "production_provider_signing_identity_collision",
        ):
            verify_production_provider_set(collision)
        provider_digest = verify_production_provider_set(self.providers)
        evidence = replace(
            self.evidence(provider_digest),
            ci_key_custody_digest="5" * 64,
        )
        with self.assertRaisesRegex(
            ValueError,
            "production_evidence_key_custody_collision",
        ):
            verify_production_evidence_bundle(
                evidence,
                expected_source_commit=self.commit,
                expected_source_tree=self.tree,
                expected_target_digest=self.target,
                provider_set_digest=provider_digest,
            )


if __name__ == "__main__":
    unittest.main()
