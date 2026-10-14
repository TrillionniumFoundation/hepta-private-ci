"""Strict negative-capability gate tests on real scoring mechanics."""
import unittest
from copy import deepcopy

from amcn_core import Refused, digest
from amcn_typed_gate import typed_evidence_gate


def fixture():
    rows = []
    for split in ("select", "future_a", "future_b", "retention"):
        for arm in ("frozen", "single_shared", "untyped_equal_budget",
                    "typed_equal_budget", "typed_swapped_negative"):
            rows.append({"split": split, "arm": arm, "n": 100,
                         "accuracy": 1.0 if arm == "typed_equal_budget" else 0.0,
                         "brier": 0.0})
    return {"production_accepted": False, "metrics": {
        "profile": "hepta.amcn.typed-equal-budget.shadow.v1.heldout-score",
        "features_sha256": digest("features"),
        "type_inventory_sha256": digest("types"),
        "original_predictions_sha256": digest("predictions"),
        "descriptive_scores": rows, "complete_case_count": 400}}


class ConservativeGateTest(unittest.TestCase):
    def test_perfect_typed_scores_never_promote(self):
        outcome = typed_evidence_gate(fixture())
        self.assertFalse(outcome["production_accepted"])
        self.assertFalse(outcome["metrics"]["all_required_gates_pass"])
        self.assertIsNone(outcome["metrics"]["qualifying_reader_success_delta"])
        self.assertEqual(outcome["metrics"]["prospective_accuracy_delta_descriptive"],
                         {"future_a": 1.0, "future_b": 1.0})

    def test_claimed_external_success_does_not_mint_authority(self):
        evidence = {"source_family_count": 10000, "calendar_window_count": 20,
                    "reader_evaluated": True, "strong_rag_evaluated": True}
        outcome = typed_evidence_gate(fixture(), external_evidence=evidence)
        self.assertFalse(outcome["metrics"]["all_required_gates_pass"])
        self.assertIn("external inventory is unauthenticated commentary",
                      outcome["metrics"]["blocking_reasons"])

    def test_missing_future_control_refused(self):
        source = fixture()
        source["metrics"]["descriptive_scores"] = [
            x for x in source["metrics"]["descriptive_scores"]
            if not (x["split"] == "future_b" and x["arm"] == "single_shared")]
        with self.assertRaises(Refused):
            typed_evidence_gate(source)

    def test_unpaired_arm_refused(self):
        source = fixture()
        source["metrics"]["descriptive_scores"][7]["n"] = 99
        with self.assertRaises(Refused):
            typed_evidence_gate(source)

    def test_forged_authority_refused(self):
        source = fixture()
        source["production_accepted"] = True
        with self.assertRaises(Refused):
            typed_evidence_gate(source)

    def test_unbound_original_prediction_refused(self):
        source = fixture()
        source["metrics"]["original_predictions_sha256"] = "invalid"
        with self.assertRaises(Refused):
            typed_evidence_gate(source)

    def test_duplicate_arms_and_invalid_values_refused(self):
        source = fixture()
        source["metrics"]["descriptive_scores"].append(
            deepcopy(source["metrics"]["descriptive_scores"][0]))
        with self.assertRaises(Refused):
            typed_evidence_gate(source)
        source = fixture()
        source["metrics"]["descriptive_scores"][0]["accuracy"] = 2.0
        with self.assertRaises(Refused):
            typed_evidence_gate(source)

    def test_unregistered_external_claims_refused(self):
        with self.assertRaises(Refused):
            typed_evidence_gate(fixture(), external_evidence={
                "source_family_count": 200,
                "calendar_window_count": 2,
                "reader_evaluated": True,
                "strong_rag_evaluated": True,
                "signed_approved": True})


if __name__ == "__main__":
    unittest.main()
