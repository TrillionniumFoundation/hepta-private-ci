"""Adversarial fixture tests only; no original model execution is claimed."""
from copy import deepcopy
import unittest

from memory_nine_arm_gate import Refused, canonical, sha
from memory_nine_arm_training_cost import (
    PHASES, SCHEMA, TRAINED, verify_training_receipts,
)
from test_memory_nine_arm_gate import fixture, h


def create_event(phase, units, source_roots):
    record = {
        "phase": phase,
        "source_roots": list(source_roots),
        "optimizer_updates": 20 if phase == "head" else 2,
        "optimizer_examples": 160 if phase == "head" else 16,
        "work_units": units,
        "forward_calls": 35,
        "cpu_ns": 100000,
        "before_sha256": h("before:" + phase),
        "after_sha256": h("after:" + phase),
    }
    record["record_sha256"] = sha(canonical(record))
    return record


def package_for(plan):
    records = []
    for arm in TRAINED:
        bank = plan["arms"][arm]
        phases = PHASES[arm]
        # Physical work must fit the same 500-unit plan across all E-I.
        per_additional = 10
        head_units = bank["total_training_budget_units"] - per_additional * (len(phases) - 1)
        events = [create_event(phase, head_units if phase == "head" else per_additional,
                               plan["common"]["training_roots"]) for phase in phases]
        records.append({
            "arm": arm, "artifact_sha256": bank["artifact_sha256"],
            "encoder_sha256": plan["common"]["encoder_sha256"],
            "source_frontier_sha256": plan["common"]["source_frontier_sha256"],
            "forget_frontier_sha256": plan["common"]["forget_frontier_sha256"],
            "source_ancestor_roots": plan["common"]["training_roots"],
            "replay_source_roots": plan["common"]["training_roots"],
            "trained_head_tensor_digests": [
                h("physical tensor:" + arm + ":" + str(i))
                for i in range(bank["trained_heads"])
            ],
            "weight_inventory_sha256": h("inventory:" + arm),
            "journal_sha256": h("journal:" + arm),
            "observed_encoder_forwards": 20, "artifact_bytes": 1024,
            "peak_rss_bytes": 4096,
            "parent_artifact_sha256": (
                plan["arms"]["H"]["artifact_sha256"] if arm == "I" else None
            ),
            "evolution_operation_receipts": (
                {"split": h("physical split"), "merge": h("physical merge")}
                if arm == "I" else {}
            ),
            "events": events,
        })
    return {"schema": SCHEMA, "plan_sha256": sha(canonical(plan)), "arms": records}


class PhysicalTrainingCostTests(unittest.TestCase):
    def setUp(self):
        self.plan, _, _ = fixture()
        self.package = package_for(self.plan)

    def subject(self, arm):
        return next(x for x in self.package["arms"] if x["arm"] == arm)

    def refuses(self, phrase):
        with self.assertRaisesRegex(Refused, phrase):
            verify_training_receipts(self.plan, self.package)

    def test_nominal_fixture_is_accounted_but_is_not_scientific_evidence(self):
        report = verify_training_receipts(self.plan, self.package)
        self.assertTrue(report["training_budget_reconciled"])
        self.assertEqual(set(report["by_arm"]), set(TRAINED))
        self.assertEqual([report["by_arm"][arm]["operator_work_units"] for arm in TRAINED],
                         [500] * 5)
        self.assertFalse(report["actual_model_origin_independently_authenticated"])
        self.assertFalse(report["prospective_memory_superiority_established"])
        self.assertFalse(report["production_activation_allowed"])
        self.assertEqual(report["authority"], "DENY_ALL")

    def test_missing_arm_rejected(self):
        self.package["arms"].pop()
        self.refuses("complete E-I")

    def test_duplicate_arm_rejected(self):
        self.package["arms"][-1] = deepcopy(self.package["arms"][0])
        self.refuses("duplicate")

    def test_wrong_external_plan_rejected(self):
        self.package["plan_sha256"] = h("wrong")
        self.refuses("not bound")

    def test_encoder_generation_drift_rejected(self):
        self.subject("E")["encoder_sha256"] = h("wrong")
        self.refuses("drift")

    def test_forget_frontier_drift_rejected(self):
        self.subject("F")["forget_frontier_sha256"] = h("old forget")
        self.refuses("drift")

    def test_calibration_source_leak_rejected(self):
        self.subject("F")["source_ancestor_roots"].append("calib:root")
        self.refuses("train/evaluation/calibration")

    def test_future_source_leak_rejected(self):
        self.subject("G")["source_ancestor_roots"].append("root:0")
        self.refuses("train/evaluation/calibration")

    def test_replay_source_must_be_in_ancestors(self):
        self.subject("G")["replay_source_roots"].append("untraced")
        self.refuses("replay source omitted")

    def test_aliased_physical_head_tensor_rejected(self):
        self.subject("H")["trained_head_tensor_digests"][1] = (
            self.subject("H")["trained_head_tensor_digests"][0])
        self.refuses("aliased trained Head")

    def test_unmatched_training_work_budget_rejected(self):
        r = self.subject("I")
        r["events"][0]["work_units"] += 1
        r["events"][0]["record_sha256"] = sha(canonical({
            k: v for k, v in r["events"][0].items() if k != "record_sha256"}))
        self.refuses("not at equal frozen budget")

    def test_forged_phase_digest_rejected(self):
        self.subject("H")["events"][-1]["optimizer_updates"] += 1
        self.refuses("modified after sealing")

    def test_missing_learned_router_is_not_a_valid_G(self):
        self.subject("G")["events"] = self.subject("G")["events"][:1]
        self.refuses("work census")

    def test_graph_phase_cannot_be_smuggled_into_F(self):
        event = create_event("graph", 1, ["train:root"])
        self.subject("F")["events"][-1] = event
        self.refuses("unregistered work phase")

    def test_no_fake_nochange_head_training(self):
        e = self.subject("E")["events"][0]
        e["after_sha256"] = e["before_sha256"]
        e["record_sha256"] = sha(canonical({
            k: v for k, v in e.items() if k != "record_sha256"}))
        self.refuses("without changed tensor")

    def test_head_actual_steps_must_equal_frozen_plan(self):
        e = self.subject("E")["events"][0]
        e["optimizer_updates"] += 1
        e["record_sha256"] = sha(canonical({
            k: v for k, v in e.items() if k != "record_sha256"}))
        self.refuses("Head steps/examples")

    def test_physical_split_merge_both_required(self):
        self.subject("I")["evolution_operation_receipts"].pop("merge")
        self.refuses("both physical split")

    def test_split_from_wrong_parent_rejected(self):
        self.subject("I")["parent_artifact_sha256"] = h("not H")
        self.refuses("frozen H parent")

    def test_reused_split_merge_receipt_rejected(self):
        ops = self.subject("I")["evolution_operation_receipts"]
        ops["merge"] = ops["split"]
        self.refuses("aliased")

    def test_peak_rss_cannot_escape_bank_budget(self):
        self.subject("I")["peak_rss_bytes"] = 8193
        self.refuses("RSS exceeds")

    def test_missing_physical_forward_rejected(self):
        self.subject("E")["observed_encoder_forwards"] = 0
        self.refuses("observed_encoder_forwards")

    def test_per_phase_training_root_scope_rejected(self):
        ev = self.subject("I")["events"][-1]
        ev["source_roots"] = ["root:0"]
        ev["record_sha256"] = sha(canonical({
            k: v for k, v in ev.items() if k != "record_sha256"}))
        self.refuses("unregistered or withdrawn")


if __name__ == "__main__":
    unittest.main()
