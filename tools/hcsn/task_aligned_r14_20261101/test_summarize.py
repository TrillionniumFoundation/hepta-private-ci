"""Evidence completeness, paired-unit inference and nonduplicated cost checks."""

import copy
import json
from pathlib import Path
import unittest

from .summarize import summarize


def fixture():
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    protocol["confirmation_episodes_per_domain"] = 4

    def execution(utility, cpu):
        values = dict(utility=[utility] * 4, reward=[utility + .1] * 4,
                      fee=[.1] * 4, reads=[1.] * 4, resets=[0.] * 4)
        return dict(count=4, mean={**{k: v[0] for k, v in values.items()}, "elapsed": .4},
                    episode_values=values, tape_hash="paired-tape", planner_identity="common-planner",
                    world_identity="common-world", costs=dict(cpu_seconds=cpu, inference_cpu_seconds=cpu * .2,
                    control_cpu_seconds=cpu * .5, planner_construction_cpu_seconds=cpu * .1,
                    owner_cpu_seconds=cpu * .1))

    rows = []
    for seed in protocol["fit_seeds"]:
        training = dict(seed=seed, status="completed", selected_ordinary="gru",
                        common_planner_identity="common-planner", world_identity="common-world",
                        preparation_cpu_seconds=2., common_calibration_cpu_seconds=3.,
                        ordinary_candidate_and_selection_cpu_seconds=40.,
                        hx_candidate_and_validation_cpu_seconds=10.,
                        ce_counterfactual_additional_actual_cpu_seconds=5., total_process_cpu_seconds=61.)
        for domain in ("iid", "ood"):
            arms = {a: execution(u, c) for a, u, c in (("A", .5, 1.), ("B", .7, 2.),
                                                       ("C", .4, .5), ("D", .72, 1.))}
            rows.append(dict(seed=seed, domain=domain, selected_ordinary="gru", training=copy.deepcopy(training),
                             source_commit="a" * 40, freeze_commit="b" * 40, freeze_sha256="c" * 64,
                             owner_setup_cpu_seconds=.2, total_process_cpu_seconds=10.,
                             arms=arms, references={"generic_hmm_common": execution(.69, 1.),
                                                   "generic_hmm_final": copy.deepcopy(arms["D"])},
                             objective_controls={"D_ce": execution(.71, 1.), "B_ce": execution(.68, 1.)},
                             ablations={"D_no_reset": execution(.6, 1.)},
                             final_hmm_equivalence=dict(actions_equal=True, utility_equal=True)))
    return rows, protocol


class SummaryTests(unittest.TestCase):
    def test_complete_cohort_effects_and_costs_preserve_fit_unit(self):
        rows, protocol = fixture()
        result = summarize(rows, protocol)
        iid = result["domains"]["iid"]
        self.assertEqual(iid["contrasts"]["D-B"]["n"], 8)
        self.assertEqual(len(iid["contrasts"]["D-B"]["per_seed"]), 8)
        self.assertAlmostEqual(iid["contrasts"]["interaction"]["mean"], .12)
        self.assertTrue(result["acceptance"]["quality_gain"])
        self.assertTrue(result["acceptance"]["quality_guarded_research_cpu_saving"])
        self.assertAlmostEqual(iid["costs"]["full_arm_means_by_reuse"]["1000"]["D"], 15.2 / 1000 + 1 / 4)
        self.assertEqual(result["training_cost_ledger"]["total_process_cpu_seconds"], 8 * 61)
        self.assertEqual(result["training_cost_ledger"]["ce_counterfactual_additional_actual_cpu_seconds"], 8 * 5)
        self.assertEqual(result["training_cost_ledger"]["unallocated_measured_overhead_cpu_seconds"], 8.)
        self.assertEqual(result["measured_training_plus_confirmation_cpu_seconds"], 8 * 61 + 16 * 10)
        self.assertFalse(result["HX_exclusive_efficiency_claim_supported"])
        self.assertTrue(result["identical_final_matrix_hmm"])

    def test_incomplete_mismatched_or_double_charged_evidence_is_rejected(self):
        rows, protocol = fixture()
        bad = []
        bad.append(rows[:-1])
        duplicate = copy.deepcopy(rows)
        duplicate[-1] = copy.deepcopy(duplicate[0])
        bad.append(duplicate)
        changed_tape = copy.deepcopy(rows)
        changed_tape[0]["arms"]["D"]["tape_hash"] = "different"
        bad.append(changed_tape)
        changed_training = copy.deepcopy(rows)
        changed_training[0]["training"]["common_calibration_cpu_seconds"] += 1
        bad.append(changed_training)
        changed_freeze = copy.deepcopy(rows)
        changed_freeze[0]["freeze_commit"] = "d" * 40
        bad.append(changed_freeze)
        double_charged = copy.deepcopy(rows)
        for row in double_charged:
            row["training"]["ce_counterfactual_additional_actual_cpu_seconds"] = 100
        bad.append(double_charged)
        for payload in bad:
            with self.assertRaises(ValueError):
                summarize(payload, protocol)

    def test_control_gain_does_not_replace_primary_gain_or_quality_guard(self):
        rows, protocol = fixture()
        for row in rows:
            row["arms"]["D"] = copy.deepcopy(row["arms"]["C"])
            row["references"]["generic_hmm_final"] = copy.deepcopy(row["arms"]["D"])
        result = summarize(rows, protocol)
        self.assertGreater(result["domains"]["iid"]["contrasts"]["B-A"]["mean"], 0)
        self.assertFalse(result["acceptance"]["quality_gain"])
        self.assertFalse(result["acceptance"]["quality_guarded_research_cpu_saving"])


if __name__ == "__main__":
    unittest.main()
