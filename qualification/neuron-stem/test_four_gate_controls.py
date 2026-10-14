"""Adversarial controls/cost fixtures, not scientific gain observations."""
from copy import deepcopy
import unittest

from four_gate_common import PHASES, digest
from four_gate_controls import (DEPTHS, V2, arms_for, depth_distribution,
                                generation_overhead, validate_selection)
from four_gate_outcomes import REASON_ARMS, causal_depth, paired_evidence, review_reasoning
from four_gate_controls import capture_exact_reachability
from test_four_gate_fixtures import (cost_fixture, lifecycle_fixture, nodes_fixture,
                                     outcomes_fixture, plan_fixture)


def validation_fixture(plan):
    return {"schema": "hepta.fixed-depth.validation.v1", "job_id": "fixed-grid-search", "rows": [
        {"case_id": f"validation-{g}", "depth": d, "source_cluster": f"old-{g}",
         "input_sha256": digest(["validation input", g]),
         "observed_at": plan["selection_cutoff"], "objective_sha256": plan["objective_sha256"],
         "producer_id": "fixture model", "observer_id": "fixture observer",
         "outcome_receipt_sha256": digest(["validation outcome", g, d]),
         "score": 1.0 if d == 12 else .5, "cost": cost_fixture(d, d)}
        for g in range(2) for d in DEPTHS]}


def strong_fixture():
    plan = plan_fixture()
    plan["schema"] = V2
    ev = outcomes_fixture(plan)
    val = validation_fixture(plan)
    plan["reasoning"].update(validation_sha256=digest(val), validation_depths=list(DEPTHS),
                              selection_cost_weights={}, exact_algorithm_applicable=True)
    ev["fixed_depth_validation"] = val
    originals = list(ev["episodes"])
    for arm in arms_for(plan, "reasoning", REASON_ARMS)[3:]:
        meta = deepcopy(ev["arms"]["equal_compute_control"])
        meta["policy_sha256"] = digest(["policy", arm])
        meta["lifecycle"] = lifecycle_fixture(arm, 10 * len(ev["cases"]), 20 * len(ev["cases"]))
        ev["arms"][arm] = meta
        for old in originals:
            if old["arm"] != "equal_compute_control":
                continue
            row = deepcopy(old)
            row["arm"] = arm
            depth = 12 if arm in ("fixed_12", "best_fixed") else 1
            row["trace"] = nodes_fixture(row["input_sha256"], depth, row["case_id"] + arm)
            if arm == "exact_algorithm":
                row["trace"][0]["kind"] = "guard"
            row["prediction_sha256"] = row["trace"][-1]["output_sha256"]
            row["external_outcome"]["score"] = 1.0
            row["external_outcome"]["receipt_sha256"] = digest([row["case_id"], arm, "observed"])
            ev["episodes"].append(row)
    ev["arms"]["best_fixed"]["lifecycle"]["search"]["job_id"] = val["job_id"]
    ev["arms"]["best_fixed"]["lifecycle"]["search"]["cost"] = cost_fixture(2 * sum(DEPTHS), 2 * sum(DEPTHS))
    for row in ev["episodes"]:
        row["stop_reason"] = "exact_algorithm_complete" if row["arm"] == "exact_algorithm" else "fixed_limit"
    return plan, ev


class StrongControlsTests(unittest.TestCase):
    def test_constant_12_does_not_establish_adaptive_benefit(self):
        plan, ev = strong_fixture()
        report = review_reasoning(plan, ev)
        self.assertEqual(report["status"], "not_passed")
        self.assertEqual(report["metrics"]["fixed_depth_selection"]["selected_best_fixed_depth"], 12)
        self.assertTrue(report["metrics"]["depth_distribution"]["best_fixed"]["constant_depth"])
        self.assertFalse(report["metrics"]["depth_distribution"]["best_fixed"]["input_adaptive_benefit_inferred"])
        self.assertIn("future_1:new_relations:exact_algorithm", report["metrics"]["paired_comparisons"])

    def test_posthoc_selection_digest_rejected(self):
        plan, ev = strong_fixture()
        ev["fixed_depth_validation"]["rows"][0]["score"] = .99
        with self.assertRaisesRegex(ValueError, "changed after"):
            review_reasoning(plan, ev)

    def test_rehashed_future_validation_still_rejected(self):
        plan, ev = strong_fixture()
        ev["fixed_depth_validation"]["rows"][0]["observed_at"] = plan["windows"]["future_1"][0]
        plan["reasoning"]["validation_sha256"] = digest(ev["fixed_depth_validation"])
        with self.assertRaisesRegex(ValueError, "future outcome"):
            review_reasoning(plan, ev)

    def test_preparation_cost_cannot_be_hidden(self):
        plan, ev = strong_fixture()
        ev["arms"]["best_fixed"]["lifecycle"]["search"]["cost"] = cost_fixture(0, 0)
        with self.assertRaisesRegex(ValueError, "unpaid fixed-depth"):
            review_reasoning(plan, ev)

    def test_inapplicable_algorithm_requires_a_preregistered_assessment(self):
        plan, ev = strong_fixture()
        plan["reasoning"]["exact_algorithm_applicable"] = False
        with self.assertRaises(KeyError):
            review_reasoning(plan, ev)
        plan["reasoning"].update(exact_algorithm_assessment_sha256=digest("fixture prior assessment"),
            exact_algorithm_inapplicability_reason="fixture task without an exact algorithm")
        del ev["arms"]["exact_algorithm"]
        ev["episodes"] = [r for r in ev["episodes"] if r["arm"] != "exact_algorithm"]
        self.assertEqual(review_reasoning(plan, ev)["status"], "not_passed")

    def test_missing_fixed_12_comparator_rejected(self):
        plan, ev = strong_fixture()
        del ev["arms"]["fixed_12"]
        with self.assertRaisesRegex(ValueError, "comparator"):
            review_reasoning(plan, ev)

    def test_relabelled_best_fixed_depth_rejected(self):
        plan, ev = strong_fixture()
        for row in ev["episodes"]:
            if row["arm"] == "best_fixed":
                row["trace"] = nodes_fixture(row["input_sha256"], 8, row["case_id"] + "bad")
                row["prediction_sha256"] = row["trace"][-1]["output_sha256"]
        with self.assertRaisesRegex(ValueError, "differs from historical"):
            review_reasoning(plan, ev)


def generation_fixture():
    plan = plan_fixture()
    plan["schema"] = V2
    cases = {f"case-{i}": {"scope": "scope-a"} for i in range(2)}
    entries, episodes = [], {}
    for i, cid in enumerate(cases):
        binding = {"model_sha256": digest("model"), "critic_sha256": digest("critic"),
                   "objective_sha256": plan["objective_sha256"], "scope": "scope-a", "generation": i + 1}
        phases = lifecycle_fixture(f"generation-{i}", 10, 10)
        phases["training"]["cost"] = cost_fixture(90 if i == 0 else 0, 90 if i == 0 else 0)
        entries.append({"binding": binding, "case_ids": [cid], "lifecycle": phases})
        episodes[(cid, "ndu")] = {"row": {"cache_binding_sha256": digest(binding), "cost": cost_fixture(10, 10)}}
    total = lifecycle_fixture("summary", 20, 20)
    total["training"]["cost"] = cost_fixture(90, 90)
    evidence = {"arms": {"ndu": {"stem_sha256": digest("model"), "lifecycle": total, "lifecycle_generations": entries}}}
    return plan, evidence, cases, episodes


class GenerationCostTests(unittest.TestCase):
    def test_refresh_overhead_charged_only_to_actual_compatible_uses(self):
        plan, ev, cases, episodes = generation_fixture()
        charges = generation_overhead(plan, ev, cases, episodes)
        self.assertAlmostEqual(charges[("case-0", "ndu")], .9)
        self.assertEqual(charges[("case-1", "ndu")], 0)

    def test_imaginary_future_uses_rejected(self):
        plan, ev, cases, episodes = generation_fixture()
        ev["arms"]["ndu"]["lifecycle_generations"][0]["planned_uses"] = 10000
        with self.assertRaisesRegex(ValueError, "imaginary uses"):
            generation_overhead(plan, ev, cases, episodes)

    def test_stale_critic_cache_rejected(self):
        plan, ev, cases, episodes = generation_fixture()
        ev["arms"]["ndu"]["lifecycle_generations"][0]["binding"]["critic_sha256"] = digest("new critic")
        with self.assertRaisesRegex(ValueError, "stale model"):
            generation_overhead(plan, ev, cases, episodes)

    def test_rehashed_wrong_model_cannot_reuse_generation(self):
        plan, ev, cases, episodes = generation_fixture()
        binding = ev["arms"]["ndu"]["lifecycle_generations"][0]["binding"]
        binding["model_sha256"] = digest("another model")
        episodes[("case-0", "ndu")]["row"]["cache_binding_sha256"] = digest(binding)
        with self.assertRaisesRegex(ValueError, "loaded Stem"):
            generation_overhead(plan, ev, cases, episodes)

    def test_unreconciled_refresh_cost_rejected(self):
        plan, ev, cases, episodes = generation_fixture()
        ev["arms"]["ndu"]["lifecycle"]["training"]["cost"] = cost_fixture(0, 0)
        with self.assertRaisesRegex(ValueError, "summary mismatch"):
            generation_overhead(plan, ev, cases, episodes)

    def test_cross_generation_duplicate_job_rejected(self):
        plan, ev, cases, episodes = generation_fixture()
        entries = ev["arms"]["ndu"]["lifecycle_generations"]
        entries[1]["lifecycle"]["load"]["job_id"] = entries[0]["lifecycle"]["load"]["job_id"]
        with self.assertRaisesRegex(ValueError, "double charged"):
            generation_overhead(plan, ev, cases, episodes)


class ExactGraphControlTests(unittest.TestCase):
    def test_real_bfs_keeps_guard_depth_zero(self):
        observed = capture_exact_reachability(4, [[0, 1], [1, 2], [2, 3]], 0, 3,
                                              edge_inventory_complete=True)
        self.assertTrue(observed["prediction"])
        self.assertGreater(observed["cost"]["cpu_ns"], 0)
        self.assertEqual(causal_depth(observed["trace"], observed["input_sha256"])["learned_depth"], 0)
        self.assertFalse(observed["external_outcome_observed"])

    def test_missing_edge_inventory_does_not_invent_negative_label(self):
        unknown = capture_exact_reachability(3, [[0, 1]], 0, 2, edge_inventory_complete=False)
        negative = capture_exact_reachability(3, [[0, 1]], 0, 2, edge_inventory_complete=True)
        self.assertIsNone(unknown["prediction"])
        self.assertFalse(negative["prediction"])
        self.assertNotEqual(unknown["input_sha256"], negative["input_sha256"])

    def test_duplicate_edges_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate edge"):
            capture_exact_reachability(2, [[0, 1], [0, 1]], 0, 1, edge_inventory_complete=True)


if __name__ == "__main__":
    unittest.main()
