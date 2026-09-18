from dataclasses import replace
import unittest

from control_engineering_v2 import (
    ProductionReadinessFacts,
    evaluate_production_readiness,
)


class ProductionReadinessTests(unittest.TestCase):
    def facts(self) -> ProductionReadinessFacts:
        return ProductionReadinessFacts(
            repository_full_name="TrillionniumFoundation/hepta-private-ci",
            expected_repository_full_name="TrillionniumFoundation/hepta-private-ci",
            source_commit="a" * 40,
            source_tree="b" * 40,
            source_receipt_digest="1" * 64,
            candidate_evidence_verified=True,
            native_symbol_mapping_verified=True,
            native_symbol_mapping_digest="2" * 64,
            product_caller="hepta-production-engineering-host",
            product_test_receipt_digest="3" * 64,
            exact_source_ci_passed=True,
            synthetic_merge_ci_passed=True,
            product_tests_passed=True,
            generator_identity="engineering-generator",
            reviewer_identity="independent-reviewer",
            independent_review_accepted=True,
            review_receipt_digest="4" * 64,
            authorized_handoff=True,
            handoff_receipt_digest="5" * 64,
            external_key_custody=True,
            key_custody_receipt_digest="6" * 64,
            strong_sandbox_observed=True,
            strong_sandbox_receipt_digest="7" * 64,
            deployment_target_digest="8" * 64,
            deployment_observed=True,
            deployment_receipt_digest="9" * 64,
            rollback_rehearsed=True,
            rollback_receipt_digest="a" * 64,
            source_receipt_verified=True,
            completion_receipts_verified=True,
            multidimensional_orchestration_verified=True,
            external_audit_anchor_observed=True,
            audit_anchor_receipt_digest="b" * 64,
            multi_host_execution=True,
            distributed_coordination_bound=True,
            distributed_frontier_persisted=True,
            audit_anchor_store_bound=True,
            key_custody_identity_bound=True,
        )

    def test_complete_verified_fact_set_closes_both_readiness_dimensions(self) -> None:
        decision = evaluate_production_readiness(self.facts())
        self.assertTrue(decision.production_implementation_ready)
        self.assertTrue(decision.deployment_readiness_ready)
        self.assertEqual(decision.implementation_blockers, ())
        self.assertEqual(decision.deployment_blockers, ())
        self.assertFalse(
            any(
                (
                    decision.runtime_authority,
                    decision.merge_authority,
                    decision.activation_authority,
                    decision.promotion_authority,
                    decision.release_authority,
                )
            )
        )

    def test_product_caller_and_tests_gate_production_implementation(self) -> None:
        facts = replace(
            self.facts(),
            product_caller="",
            product_tests_passed=False,
            product_test_receipt_digest="not-a-digest",
        )
        decision = evaluate_production_readiness(facts)
        self.assertFalse(decision.production_implementation_ready)
        self.assertFalse(decision.deployment_readiness_ready)
        self.assertIn("product_caller_missing", decision.implementation_blockers)
        self.assertIn("product_tests_not_passed", decision.implementation_blockers)
        self.assertIn("product_test_receipt_invalid", decision.implementation_blockers)

    def test_independent_identity_and_live_delivery_gate_deployment(self) -> None:
        facts = replace(
            self.facts(),
            reviewer_identity="engineering-generator",
            independent_review_accepted=False,
            authorized_handoff=False,
            external_key_custody=False,
            strong_sandbox_observed=False,
            deployment_observed=False,
            rollback_rehearsed=False,
            external_audit_anchor_observed=False,
            distributed_coordination_bound=False,
            distributed_frontier_persisted=False,
            audit_anchor_store_bound=False,
            key_custody_identity_bound=False,
        )
        decision = evaluate_production_readiness(facts)
        self.assertTrue(decision.production_implementation_ready)
        self.assertFalse(decision.deployment_readiness_ready)
        self.assertIn("reviewer_identity_collision", decision.deployment_blockers)
        self.assertIn("independent_review_not_accepted", decision.deployment_blockers)
        self.assertIn("authorized_handoff_missing", decision.deployment_blockers)
        self.assertIn("external_key_custody_missing", decision.deployment_blockers)
        self.assertIn("strong_sandbox_not_observed", decision.deployment_blockers)
        self.assertIn("deployment_not_observed", decision.deployment_blockers)
        self.assertIn("rollback_not_rehearsed", decision.deployment_blockers)
        self.assertIn("external_audit_anchor_missing", decision.deployment_blockers)
        self.assertIn("distributed_coordination_missing", decision.deployment_blockers)
        self.assertIn("audit_anchor_store_unbound", decision.deployment_blockers)
        self.assertIn("key_custody_identity_unbound", decision.deployment_blockers)
        self.assertIn("distributed_frontier_not_persisted", decision.deployment_blockers)

    def test_non_boolean_claims_and_authority_delta_fail_closed(self) -> None:
        facts = replace(
            self.facts(),
            candidate_evidence_verified=1,
            exact_source_ci_passed="true",
            product_tests_passed=1,
            authority_delta=True,
        )
        decision = evaluate_production_readiness(facts)
        self.assertFalse(decision.production_implementation_ready)
        self.assertIn("candidate_evidence_not_verified", decision.implementation_blockers)
        self.assertIn("exact_source_ci_not_passed", decision.implementation_blockers)
        self.assertIn("product_tests_not_passed", decision.implementation_blockers)
        self.assertIn("authority_delta", decision.implementation_blockers)

    def test_zero_or_malformed_identities_and_receipts_fail_closed(self) -> None:
        facts = replace(
            self.facts(),
            source_commit="0" * 40,
            source_tree="xyz",
            source_receipt_digest="0" * 64,
            native_symbol_mapping_digest="g" * 64,
            deployment_target_digest="0" * 64,
        )
        decision = evaluate_production_readiness(facts)
        self.assertFalse(decision.production_implementation_ready)
        self.assertFalse(decision.deployment_readiness_ready)
        self.assertIn("source_commit_invalid", decision.implementation_blockers)
        self.assertIn("source_tree_invalid", decision.implementation_blockers)
        self.assertIn("source_receipt_invalid", decision.implementation_blockers)
        self.assertIn(
            "native_symbol_mapping_receipt_invalid",
            decision.implementation_blockers,
        )
        self.assertIn("deployment_target_invalid", decision.deployment_blockers)


if __name__ == "__main__":
    unittest.main()
