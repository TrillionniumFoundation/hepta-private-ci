from dataclasses import replace
import unittest

from control_engineering_v2 import (
    ProductionReadinessFacts,
    evaluate_production_readiness,
    semantic_digest,
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
            source_product_receipt_digest="b" * 64,
            merge_product_receipt_digest="c" * 64,
            orchestration_product_receipt_digest=semantic_digest(
                {"sourceHead": "b" * 64, "baseMerge": "c" * 64}
            ),
            sandbox_controller_verified=True,
            sandbox_controller_receipt_digest="c" * 64,
            generated_test_mutation_gate_verified=True,
            generated_test_mutation_receipt_digest="d" * 64,
            distributed_fencing_verified=True,
            distributed_fencing_receipt_digest="e" * 64,
            external_audit_anchor_verified=True,
            external_audit_anchor_receipt_digest="f" * 64,
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

    def test_distributed_fence_and_external_audit_anchor_gate_deployment(self) -> None:
        facts = replace(
            self.facts(),
            distributed_fencing_verified=False,
            distributed_fencing_receipt_digest="",
            external_audit_anchor_verified=False,
            external_audit_anchor_receipt_digest="",
        )
        decision = evaluate_production_readiness(facts)
        self.assertTrue(decision.production_implementation_ready)
        self.assertFalse(decision.deployment_readiness_ready)
        self.assertIn("distributed_fencing_not_verified", decision.deployment_blockers)
        self.assertIn("external_audit_anchor_not_verified", decision.deployment_blockers)

    def test_orchestration_sandbox_and_mutation_testing_gate_implementation(self) -> None:
        facts = replace(
            self.facts(),
            source_product_receipt_digest="",
            merge_product_receipt_digest="",
            orchestration_product_receipt_digest="",
            sandbox_controller_verified=False,
            generated_test_mutation_gate_verified=False,
        )
        decision = evaluate_production_readiness(facts)
        self.assertFalse(decision.production_implementation_ready)
        self.assertIn("source_product_receipt_invalid", decision.implementation_blockers)
        self.assertIn("merge_product_receipt_invalid", decision.implementation_blockers)
        self.assertIn(
            "orchestration_product_receipt_invalid", decision.implementation_blockers
        )
        self.assertIn(
            "sandbox_controller_not_verified", decision.implementation_blockers
        )
        self.assertIn(
            "generated_test_mutation_gate_not_verified",
            decision.implementation_blockers,
        )

    def test_product_receipt_set_requires_both_exact_lanes(self) -> None:
        facts = replace(
            self.facts(),
            merge_product_receipt_digest="",
        )
        decision = evaluate_production_readiness(facts)
        self.assertFalse(decision.production_implementation_ready)
        self.assertIn("merge_product_receipt_invalid", decision.implementation_blockers)

        mismatched = replace(
            self.facts(),
            orchestration_product_receipt_digest="f" * 64,
        )
        decision = evaluate_production_readiness(mismatched)
        self.assertFalse(decision.production_implementation_ready)
        self.assertIn(
            "orchestration_product_receipt_set_mismatch",
            decision.implementation_blockers,
        )

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

    def test_each_implementation_fact_loss_blocks_deployment_without_authority(self) -> None:
        for field, value, blocker in (
            ("repository_full_name", "other/repository", "repository_mismatch"),
            ("expected_repository_full_name", "", "repository_identity_invalid"),
            ("native_symbol_mapping_verified", 1, "native_symbol_mapping_not_verified"),
            ("synthetic_merge_ci_passed", "true", "synthetic_merge_ci_not_passed"),
            ("product_test_receipt_digest", "0" * 64, "product_test_receipt_invalid"),
            ("source_product_receipt_digest", "0" * 64, "source_product_receipt_invalid"),
            ("sandbox_controller_receipt_digest", "0" * 64, "sandbox_controller_receipt_invalid"),
            ("generated_test_mutation_receipt_digest", "0" * 64, "generated_test_mutation_receipt_invalid"),
            ("authority_delta", 0, "authority_delta"),
        ):
            with self.subTest(field=field):
                decision = evaluate_production_readiness(replace(self.facts(), **{field: value}))
                self.assertFalse(decision.production_implementation_ready)
                self.assertFalse(decision.deployment_readiness_ready)
                self.assertIn(blocker, decision.implementation_blockers)
                self.assertIn(blocker, decision.deployment_blockers)
                self.assertFalse(any((
                    decision.runtime_authority, decision.merge_authority,
                    decision.activation_authority, decision.promotion_authority,
                    decision.release_authority,
                )))

    def test_invalid_rollout_receipts_only_block_deployment_and_bind_new_decision(self) -> None:
        original = evaluate_production_readiness(self.facts())
        for field, value, blocker in (
            ("generator_identity", "", "generator_identity_missing"),
            ("reviewer_identity", "\x00reviewer", "reviewer_identity_missing"),
            ("review_receipt_digest", "0" * 64, "review_receipt_invalid"),
            ("handoff_receipt_digest", "0" * 64, "handoff_receipt_invalid"),
            ("key_custody_receipt_digest", "0" * 64, "key_custody_receipt_invalid"),
            ("strong_sandbox_receipt_digest", "0" * 64, "strong_sandbox_receipt_invalid"),
            ("deployment_receipt_digest", "0" * 64, "deployment_receipt_invalid"),
            ("rollback_receipt_digest", "0" * 64, "rollback_receipt_invalid"),
            ("distributed_fencing_receipt_digest", "0" * 64, "distributed_fencing_receipt_invalid"),
            ("external_audit_anchor_receipt_digest", "0" * 64, "external_audit_anchor_receipt_invalid"),
        ):
            with self.subTest(field=field):
                decision = evaluate_production_readiness(replace(self.facts(), **{field: value}))
                self.assertTrue(decision.production_implementation_ready)
                self.assertFalse(decision.deployment_readiness_ready)
                self.assertIn(blocker, decision.deployment_blockers)
                self.assertNotEqual(decision.evidence_digest, original.evidence_digest)
                self.assertFalse(decision.release_authority)

    def test_numeric_or_text_rollout_claims_cannot_stand_in_for_verified_true(self) -> None:
        for field, blocker in (
            ("independent_review_accepted", "independent_review_not_accepted"),
            ("authorized_handoff", "authorized_handoff_missing"),
            ("external_key_custody", "external_key_custody_missing"),
            ("strong_sandbox_observed", "strong_sandbox_not_observed"),
            ("deployment_observed", "deployment_not_observed"),
            ("rollback_rehearsed", "rollback_not_rehearsed"),
            ("distributed_fencing_verified", "distributed_fencing_not_verified"),
            ("external_audit_anchor_verified", "external_audit_anchor_not_verified"),
        ):
            for value in (1, "true"):
                with self.subTest(field=field, value=value):
                    decision = evaluate_production_readiness(replace(self.facts(), **{field: value}))
                    self.assertTrue(decision.production_implementation_ready)
                    self.assertFalse(decision.deployment_readiness_ready)
                    self.assertIn(blocker, decision.deployment_blockers)

    def test_untyped_facts_cannot_be_projected_as_production_readiness(self) -> None:
        with self.assertRaisesRegex(TypeError, "ProductionReadinessFacts required"):
            evaluate_production_readiness({})


if __name__ == "__main__":
    unittest.main()
