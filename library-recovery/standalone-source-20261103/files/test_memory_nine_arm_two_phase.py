"""Synthetic/adversarial TWO-PHASE freeze tests: never a nine-arm model run."""

from copy import deepcopy
import unittest

from memory_nine_arm_gate import Refused, canonical, sha
from memory_nine_arm_two_phase import (
    AFTER_TRAINING_FIELDS, PHASE1_SCHEMA, PHASE2_SCHEMA,
    _phase_one_projection, audit_with_two_phase, verify_two_phase,
)
from test_memory_nine_arm_gate import fixture, h
from test_memory_nine_arm_training_cost import package_for


class TwoPhaseFreezeTests(unittest.TestCase):
    def setUp(self):
        # Stage 1 contains no E-I tensor or training-output digests.
        self.plan, self.obs, self.judges = fixture()
        self.phase1 = {
            "schema": PHASE1_SCHEMA,
            "design": _phase_one_projection(self.plan),
            "producer_identities": {
                arm: {
                    "source_sha256": h("code:" + arm),
                    "configuration_sha256": h("config:" + arm),
                    "training_recipe_sha256": h("recipe:" + arm),
                } for arm in "ABCDEFGHI"
            },
            "withheld_gold_commitment_sha256": h("independent withheld gold"),
            "label_separation_policy": "gold_unavailable_to_producers",
        }
        self.phase1_pin = sha(canonical(self.phase1))
        # Synthetic 'training' merely assembles structurally valid receipts.
        # None of the reported numerical work is actual model training here.
        self.package = package_for(self.plan)
        self.phase2 = {
            "schema": PHASE2_SCHEMA,
            "phase1_sha256": self.phase1_pin,
            "materialized_plan": self.plan,
            "materialized_plan_sha256": sha(canonical(self.plan)),
            "training_package": self.package,
            "training_package_sha256": sha(canonical(self.package)),
            "evaluation_start_cut_sha256": h("future-window admission cut"),
            "model_custody_receipt_sha256": h("untrusted fixture custody receipt"),
            "executed_producer_identities": deepcopy(self.phase1["producer_identities"]),
        }
        self.phase2_pin = sha(canonical(self.phase2))

    def check(self):
        return verify_two_phase(
            self.phase1, self.phase2,
            trusted_phase1_sha256=self.phase1_pin,
            trusted_phase2_sha256=self.phase2_pin,
        )

    def reseal_second_phase(self):
        # An adversary can recompute its OWN phase-2 hash, but must still be
        # unable to rewrite the externally frozen phase-1 experiment design.
        self.phase2["materialized_plan_sha256"] = sha(canonical(self.plan))
        self.phase2["training_package_sha256"] = sha(canonical(self.package))
        self.phase2_pin = sha(canonical(self.phase2))

    def refused(self, phrase):
        with self.assertRaisesRegex(Refused, phrase):
            self.check()

    def test_nominal_two_stage_receipt_is_still_deny_all(self):
        outcome = self.check()
        self.assertTrue(outcome["source_first_design_immutable"])
        self.assertTrue(outcome["physical_training_receipt_arithmetic_reconciled"])
        self.assertFalse(outcome["independent_freeze_chronology_authenticated"])
        self.assertFalse(outcome["independent_model_origin_authenticated"])
        self.assertFalse(outcome["scientific_superiority_established"])
        self.assertFalse(outcome["production_activation_allowed"])
        self.assertEqual(outcome["status"], "HOLD_NO_GO")
        self.assertEqual(outcome["authority"], "DENY_ALL")

    def test_design_excludes_all_trained_hashes(self):
        self.check()
        for arm in "EFGHI":
            for field in AFTER_TRAINING_FIELDS:
                self.assertIsNone(self.phase1["design"]["arms"][arm][field])
                self.assertIsInstance(self.plan["arms"][arm][field], str)

    def test_existing_gate_full_audit_is_connected_and_remains_hold(self):
        result = audit_with_two_phase(
            self.phase1, self.phase2, self.obs, self.judges,
            trusted_phase1_sha256=self.phase1_pin,
            trusted_phase2_sha256=self.phase2_pin,
        )
        self.assertEqual(result["original_Reader_attempts"], 36)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["superiority_established"])
        self.assertFalse(result["two_phase_freeze_audit"]
                         ["independent_future_evaluation_authenticated"])
        self.assertTrue(any("chronological" in b for b in result["blockers"]))

    def test_stage_one_pin_cannot_be_rewritten(self):
        self.phase1["withheld_gold_commitment_sha256"] = h("different labels")
        self.refused("original preregistration changed")

    def test_missing_external_phase_one_pin_rejected(self):
        self.phase1_pin = ""
        self.refused("externally pinned")

    def test_stage_two_pin_cannot_be_rewritten(self):
        self.phase2["evaluation_start_cut_sha256"] = h("changed admission")
        self.refused("trained material changed")

    def test_phase_two_parent_pin_cannot_drift(self):
        self.phase2["phase1_sha256"] = h("unknown parent")
        self.reseal_second_phase()
        self.refused("does not descend")

    def test_stage_one_must_not_claim_preknown_trained_weights(self):
        self.phase1["design"]["arms"]["E"]["artifact_sha256"] = h("future weights")
        self.phase1_pin = sha(canonical(self.phase1))
        self.phase2["phase1_sha256"] = self.phase1_pin
        self.reseal_second_phase()
        self.refused("improperly predeclared")

    def test_malformed_stage_one_gold_leak_rejected(self):
        self.phase1["design"]["cases"][0]["answer"] = "secret gold"
        self.phase1_pin = sha(canonical(self.phase1))
        self.phase2["phase1_sha256"] = self.phase1_pin
        self.reseal_second_phase()
        self.refused("source-first case has missing/extra labels")

    def test_stage_one_requires_complete_producer_source_pins(self):
        del self.phase1["producer_identities"]["C"]
        self.phase1_pin = sha(canonical(self.phase1))
        self.phase2["phase1_sha256"] = self.phase1_pin
        self.reseal_second_phase()
        self.refused("all nine")

    def test_stage_one_producer_code_is_pinned(self):
        self.phase1["producer_identities"]["H"]["source_sha256"] = h("rewritten graph code")
        self.refused("original preregistration changed")

    def test_future_case_replacement_after_training_fails_even_if_resealed(self):
        self.plan["cases"][0]["question_sha256"] = h("changed query")
        self.reseal_second_phase()
        self.refused("training changed protocol")

    def test_source_frontier_change_after_training_rejected(self):
        self.plan["common"]["source_frontier_sha256"] = h("different ledger")
        self.reseal_second_phase()
        self.refused("training changed protocol")

    def test_reader_upgrade_after_training_rejected(self):
        self.plan["common"]["reader_sha256"] = h("different reader")
        self.reseal_second_phase()
        self.refused("training changed protocol")

    def test_numeric_type_drift_is_not_equal_to_frozen_source_bytes(self):
        # Python considers 2 == 2.0, but canonical experimental plans do NOT.
        self.plan["policy"]["max_candidate_cpu_ratio"] = 2
        self.reseal_second_phase()
        self.refused("training changed protocol")

    def test_executed_producer_code_cannot_be_swapped(self):
        self.phase2["executed_producer_identities"]["C"]["source_sha256"] = (
            h("different graph retrieval worker"))
        self.reseal_second_phase()
        self.refused("executed producer source/config")

    def test_unequal_budgets_after_training_refused(self):
        self.plan["arms"]["H"]["total_training_budget_units"] += 1
        self.reseal_second_phase()
        self.refused("unmatched")

    def test_training_artifacts_cannot_be_aliased_across_arms(self):
        self.plan["arms"]["I"]["artifact_sha256"] = self.plan["arms"]["H"]["artifact_sha256"]
        self.reseal_second_phase()
        self.refused("identical physical material")

    def test_training_receipts_cannot_be_aliased_across_arms(self):
        self.plan["arms"]["I"]["training_receipt_sha256"] = (
            self.plan["arms"]["G"]["training_receipt_sha256"])
        self.reseal_second_phase()
        self.refused("identical physical material")

    def test_missing_e_i_training_package_fails(self):
        self.package["arms"].pop()
        self.reseal_second_phase()
        self.refused("complete E-I")

    def test_training_event_forgery_refused_after_second_phase_reseal(self):
        self.package["arms"][0]["events"][0]["work_units"] += 1
        self.reseal_second_phase()
        self.refused("modified after sealing")

    def test_missing_model_custody_reference_refused(self):
        self.phase2["model_custody_receipt_sha256"] = "0" * 64
        self.reseal_second_phase()
        self.refused("model_custody")

    def test_missing_final_training_digest_refused(self):
        self.plan["arms"]["E"]["training_receipt_sha256"] = None
        self.reseal_second_phase()
        self.refused("training receipt identity")

    def test_future_source_ancestor_training_leak_refused(self):
        self.package["arms"][0]["source_ancestor_roots"].append("root:0")
        self.reseal_second_phase()
        self.refused("train/evaluation/calibration")

    def test_no_unexpected_phase_two_fields(self):
        self.phase2["external_superiority_approved"] = True
        self.reseal_second_phase()
        self.refused("phase-2 material seal")

    def test_absent_external_future_window_witness_does_not_promote(self):
        report = self.check()
        self.assertFalse(report["independent_future_evaluation_authenticated"])
        self.assertEqual(report["status"], "HOLD_NO_GO")


if __name__ == "__main__":
    unittest.main()
