"""Closed-world fault tests using explicitly SYNTHETIC, untrusted observations.

These tests evaluate validation and paired arithmetic, never actual model efficacy.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import six_track_v1 as target


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def make_fixture():
    cases = []
    for t, split in enumerate(target.SPLITS, start=1):
        for m, modality in enumerate(target.MODALITY):
            task = f"task-{split}-{modality}"
            for j, condition in enumerate(target.READER):
                cid = f"case-{split}-{modality}-{j}"
                cases.append({
                    "case_id": cid, "task_id": task, "split": split,
                    "source_group": f"family-{split}-{modality}",
                    "modality": modality, "reader_condition": condition,
                    "label": (t + m) % 2,
                    "input_sha256": sha("input/" + cid),
                    "expected_effect_sha256": sha("effect/" + task),
                    "observed_at": t * 100 + 4 * m + j,
                })
    doc = {"schema": target.SCHEMA, "authority": "DENY_ALL",
           "production_promotion_permitted": False, "cases": cases,
           **{key: sha(key) for key in target.SHA_KEYS}, "tracks": {}}
    for stage, arms in target.ARMS.items():
        doc["tracks"][stage] = {}
        for name in arms:
            if stage == "P0":
                family = name.split("_")[0]
                frozen = name.endswith("_frozen")
                initial = sha(stage + family + "-initial")
            elif stage == "P1":
                family = name.split("_")[0]
                frozen = name.endswith("_frozen")
                initial = sha(stage + "-common-initial")
            else:
                family, frozen = stage, False
                initial = sha(stage + "-initial-" + name)
            arm = {
                "name": name, "authority": "DENY_ALL",
                "production_promotion_permitted": False,
                "model_sha256": sha("one-base-" + (family if stage == "P0" else stage)),
                "initial_head_sha256": initial,
                "final_head_sha256": initial if frozen else sha(stage + name + "-final"),
                "train_data_sha256": sha(stage + "-more-data") if stage == "P2" and name == "parent_more_data" else sha(stage + "-same-data"),
                "optimizer_sha256": sha(stage + "-same-optimizer"),
                "train_cases": 128 if stage == "P2" and name == "parent_more_data" else 64,
                "train_steps": 0 if frozen else 24,
                "trainable_parameters": 9744,
                "physical_forward_claimed": False,
                "one_time_in_e2e": {k: False for k in target.ONE_TIME},
                "costs": {k: (40000000 if k == "peak_rss_bytes" else 2.0)
                          for k in target.COSTS},
                "results": [],
            }
            if stage == "P4":
                arm["compute_budget_ms"] = 100
                if name in ("no_search", "bellman"):
                    arm["train_steps"] = 0
                    arm["train_cases"] = 0
                    arm["trainable_parameters"] = 0
                    arm["costs"]["training_ms"] = 0.0
                if name == "ndu_solver":
                    arm["costs"]["ndu_ms"] = 3.0 * len(cases)
                else:
                    arm["costs"]["ndu_ms"] = 0.0
            for c in cases:
                utility = 0.5
                if stage == "P0" and not frozen:
                    utility = 0.6
                if stage == "P1" and name == "shared_learned":
                    utility = 0.65
                if stage == "P2" and name == "split_children":
                    utility = 0.55
                if stage == "P4" and name == "bellman":
                    utility = 0.75
                if stage == "P4" and name == "ndu_solver":
                    utility = 0.6
                if stage == "P5" and name == "typed":
                    utility = 0.7
                row = {
                    "case_id": c["case_id"], "input_sha256": c["input_sha256"],
                    "prelabel_sealed": True, "trace_sha256": sha(stage + name + c["case_id"]),
                    "positive_probability": 0.75 if c["label"] else 0.25,
                    "observed_utility": utility, "end_to_end_ms": 10.0,
                    "completed": True,
                }
                if stage == "P4":
                    row["measured_solver_ms"] = 0.0 if name == "no_search" else 3.0
                if stage == "P3":
                    row["generated_artifact_sha256"] = sha("generated-" + c["case_id"] + name)
                if stage == "P5":
                    row["observed_effect_sha256"] = c["expected_effect_sha256"]
                    row["recovery_status"] = "not_needed"
                arm["results"].append(row)
            doc["tracks"][stage][name] = arm
    return doc


class SixTrackValidation(unittest.TestCase):
    def setUp(self):
        self.doc = make_fixture()

    def rejected(self, change, msg=None):
        doc = copy.deepcopy(self.doc)
        change(doc)
        with self.assertRaises(target.Invalid) as error:
            target.audit(doc)
        if msg:
            self.assertIn(msg, str(error.exception))

    def test_complete_corpus_still_denies_authority(self):
        result = target.audit(self.doc)
        self.assertEqual(result["track_count"], 6)
        self.assertEqual(result["cases"], 112)
        self.assertEqual(result["authority"], "DENY_ALL")
        for field in ("production_promotion_permitted", "statistical_model_winner_selected",
                      "physical_host_cost_authenticated", "future_ndu_superiority_established",
                      "jit_mcp_end_to_end_superiority_established", "true_generation_quality_verified"):
            self.assertIs(result[field], False, field)
        self.assertAlmostEqual(result["tracks"]["P4"]["paired_family_differences"]
                               ["ndu_solver__vs__bellman"]["future1"]
                               ["mean_paired_utility_difference"], -0.15)
        self.assertTrue(result["tracks"]["P4"]["paired_family_differences"]
                        ["ndu_solver__vs__bellman"]["future1"]
                        ["insufficient_independent_families_for_efficacy"])

    def test_e2e_nearest_rank_and_amortized_once(self):
        out = target.audit(self.doc)["tracks"]["P5"]["arms"]["typed"]
        self.assertEqual(out["future1"]["p50_ms"], 10.0)
        self.assertIsNone(out["future1"]["p95_ms"])
        self.assertIsNone(out["future1"]["p99_ms"])
        self.assertEqual(out["future1"]["distinct_task_count"], 4)
        # 5 one-time columns at 2ms, over 112 requests, not summed twice.
        self.assertEqual(out["lifecycle"]["observed_evaluation_requests"], 80)
        self.assertEqual(out["lifecycle"]["excluded_training_calibration_requests"], 32)
        self.assertAlmostEqual(out["lifecycle"]["mean_e2e_plus_amortized_ms"], 10 + 10 / 80)

    def test_frozen_head_cannot_claim_optimizer_steps(self):
        self.rejected(lambda d: d["tracks"]["P0"]["granite_frozen"].update(
            train_steps=12), "frozen Head")

    def test_other_frozen_head_cannot_mutate_even_if_unpaired(self):
        self.rejected(lambda d: d["tracks"]["P1"]["replicated_frozen"].update(
            final_head_sha256=sha("changed-without-train")), "frozen Head changed weights")

    def test_other_learned_head_cannot_fake_training_with_unchanged_bytes(self):
        def unchanged(d):
            a = d["tracks"]["P1"]["replicated_learned"]
            a["final_head_sha256"] = a["initial_head_sha256"]
        self.rejected(unchanged, "learned Head weights did not change")

    def test_learned_head_requires_real_update_steps(self):
        self.rejected(lambda d: d["tracks"]["P1"]["shared_learned"].update(
            train_steps=0), "learned Head has no optimizer")

    def test_learned_head_requires_nonzero_trainable_parameters(self):
        self.rejected(lambda d: d["tracks"]["P1"]["shared_learned"].update(
            trainable_parameters=0), "zero trainable")

    def test_p0_four_names_cannot_alias_one_model(self):
        self.rejected(lambda d: d["tracks"]["P0"]["laya_frozen"].update(
            model_sha256=d["tracks"]["P0"]["granite_frozen"]["model_sha256"]), "model")
        def make_alias(d):
            for role in ("frozen", "learned"):
                d["tracks"]["P0"]["laya_" + role]["model_sha256"] = (
                    d["tracks"]["P0"]["granite_" + role]["model_sha256"]
                )
        self.rejected(make_alias, "alias")

    def test_p0_model_comparison_same_training_schedule(self):
        self.rejected(lambda d: d["tracks"]["P0"]["laya_learned"].update(
            train_steps=48), "common training budget")
        self.rejected(lambda d: d["tracks"]["P0"]["mmbert_learned"].update(
            optimizer_sha256=sha("other-optimizer")), "common training budget")

    def test_p1_shared_vs_replicated_head_same_initialization(self):
        def alter(d):
            for name in ("replicated_frozen", "replicated_learned"):
                d["tracks"]["P1"][name]["initial_head_sha256"] = sha("different-initial")
            d["tracks"]["P1"]["replicated_frozen"]["final_head_sha256"] = sha("different-initial")
        self.rejected(alter, "initialization differs")

    def test_p1_frozen_zero_steps_and_learned_positive_steps_is_valid(self):
        study = self.doc["tracks"]["P1"]
        self.assertEqual(study["shared_frozen"]["train_steps"], 0)
        self.assertGreater(study["shared_learned"]["train_steps"], 0)
        result = target.audit(self.doc)
        self.assertEqual(result["authority"], "DENY_ALL")
        self.assertFalse(result["statistical_model_winner_selected"])
        self.assertIn("shared_learned__vs__shared_frozen",
                      result["tracks"]["P1"]["paired_family_differences"])

    def test_p1_learned_vs_learned_still_requires_matching_steps(self):
        self.rejected(lambda d: d["tracks"]["P1"]["replicated_learned"].update(
            train_steps=25), "unmatched learning effort")

    def test_p1_frozen_head_cannot_fake_training_steps(self):
        self.rejected(lambda d: d["tracks"]["P1"]["shared_frozen"].update(
            train_steps=1), "frozen Head cannot report optimizer steps")

    def test_p2_step_parity_and_p4_train_work_consistency(self):
        self.rejected(lambda d: d["tracks"]["P2"]["matched_unsplit"].update(
            train_steps=25), "unmatched learning effort")
        self.rejected(lambda d: d["tracks"]["P4"]["tree_search"].update(
            train_steps=0), "P4 zero-step control claims training exposure or cost")

    def test_p1_shared_vs_replicated_head_capacity(self):
        self.rejected(lambda d: d["tracks"]["P1"]["replicated_learned"].update(
            trainable_parameters=9750), "parameter budget differs")

    def test_p2_more_data_cannot_reuse_smaller_dataset_sha(self):
        self.rejected(lambda d: d["tracks"]["P2"]["parent_more_data"].update(
            train_data_sha256=d["tracks"]["P2"]["split_children"]["train_data_sha256"]), "identical training dataset")

    def test_ood_before_training_freeze_rejected(self):
        self.rejected(lambda d: [c.update(observed_at=99) for c in d["cases"]
                                 if c["split"] == "ood"], "OOD examples")

    def test_p5_blocked_effect_cannot_be_success(self):
        self.rejected(lambda d: d["tracks"]["P5"]["native_cpu"]["results"][0].update(
            recovery_status="blocked"), "blocked effect")

    def test_minimum_percentile_request_census(self):
        self.assertIsNone(target.supported_nearest_rank([1, 2], .5, 3))
        self.assertEqual(target.supported_nearest_rank([5, 1, 3], .5, 3), 3)
        self.assertIsNone(target.supported_nearest_rank(list(range(19)), .95, 20))
        self.assertEqual(target.supported_nearest_rank(list(range(20)), .95, 20), 19)
        self.assertIsNone(target.supported_nearest_rank(list(range(99)), .99, 100))
        self.assertEqual(target.supported_nearest_rank(list(range(100)), .99, 100), 98)

    def test_wrong_authority(self):
        self.rejected(lambda d: d.update(authority="GRANT"), "non-authorizing")

    def test_missing_P5_strong_control(self):
        self.rejected(lambda d: d["tracks"]["P5"].pop("mcp_batch"), "strong baseline")

    def test_duplicate_case(self):
        self.rejected(lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])), "duplicate case")

    def test_cross_split_source(self):
        self.rejected(lambda d: d["cases"][16].update(source_group=d["cases"][0]["source_group"]), "leakage")

    def test_same_task_instance_cannot_cross_train_future_even_with_new_bytes(self):
        # Same task instance dressed as a new source family and input is not
        # an independent future evaluation question.
        self.rejected(lambda d: d["cases"][48].update(
            task_id=d["cases"][0]["task_id"]),
            "task instance identity reused across temporal cohorts")

    def test_same_task_instance_cannot_cross_future_ood(self):
        self.rejected(lambda d: d["cases"][96].update(
            task_id=d["cases"][64]["task_id"]),
            "task instance identity reused across temporal cohorts")

    def test_four_reader_views_of_one_task_still_valid(self):
        doc = copy.deepcopy(self.doc)
        views = [row for row in doc["cases"]
                 if row["task_id"] == doc["cases"][48]["task_id"]]
        self.assertEqual({row["reader_condition"] for row in views},
                         set(target.READER))
        result = target.audit(doc)
        self.assertTrue(result["task_instance_ids_cross_split_rejected"])
        self.assertIs(result["task_identity_provenance_independently_verified"], False)
        self.assertIs(result["production_promotion_permitted"], False)

    def test_v2_observations_are_not_silently_upgraded_to_v3(self):
        self.rejected(lambda d: d.update(
            schema="hepta.six-track-paired-observation.v2"), "non-authorizing")

    def test_chronology_violation(self):
        self.rejected(lambda d: d["cases"][32].update(observed_at=2), "time boundary")

    def test_exact_input_cannot_create_second_independent_source_group(self):
        # Same split, two apparently distinct provenance groups, identical bytes.
        # Without this check the family-count estimate can be inflated.
        self.rejected(lambda d: d["cases"][4].update(
            input_sha256=d["cases"][0]["input_sha256"]),
            "identical input reused across distinct source families")

    def test_reader_sufficient_vs_removed_premise_must_change_input(self):
        # A label saying "premise_removed" is not a causal intervention when
        # the bytes seen by the model are identical to the sufficient condition.
        self.rejected(lambda d: d["cases"][35].update(
            input_sha256=d["cases"][34]["input_sha256"]),
            "Reader sufficient/premise-removed intervention")

    def test_same_source_can_reuse_input_for_noop_retrieval(self):
        doc = copy.deepcopy(self.doc)
        doc["cases"][33]["input_sha256"] = doc["cases"][32]["input_sha256"]
        for arms in doc["tracks"].values():
            for arm in arms.values():
                arm["results"][33]["input_sha256"] = doc["cases"][32]["input_sha256"]
        out = target.audit(doc)
        self.assertEqual(out["distinct_input_sha256_count"], 111)
        self.assertIs(out["independent_source_groups_not_cryptographically_attested"], True)
        self.assertIs(out["production_promotion_permitted"], False)

    def test_reader_counterfactual_missing(self):
        self.rejected(lambda d: d["cases"][33].update(reader_condition="none"), "repeated Reader")

    def test_reader_answer_flip(self):
        self.rejected(lambda d: d["cases"][32].update(label=1-d["cases"][32]["label"]), "Reader intervention changed")

    def test_reader_does_not_change_modality(self):
        self.rejected(lambda d: d["cases"][33].update(modality="audio"), "Reader intervention changed original task media")

    def test_reader_does_not_change_source(self):
        self.rejected(lambda d: d["cases"][33].update(source_group="different-family"), "Reader intervention changed original task media")

    def test_one_time_component_census_required(self):
        self.rejected(lambda d: d["tracks"]["P5"]["typed"].pop("one_time_in_e2e"),
                      "per-component one-time")
        self.rejected(lambda d: d["tracks"]["P5"]["typed"]["one_time_in_e2e"].pop("training_ms"),
                      "per-component one-time")
        self.rejected(lambda d: d["tracks"]["P5"]["typed"]["one_time_in_e2e"].update(
            training_ms=1), "per-component one-time")

    def test_obsolete_global_cost_flag_is_rejected(self):
        self.rejected(lambda d: d["tracks"]["P5"]["typed"].update(
            e2e_includes_one_time=True), "obsolete")

    def test_all_one_time_components_already_in_e2e(self):
        doc = copy.deepcopy(self.doc)
        doc["tracks"]["P5"]["typed"]["one_time_in_e2e"] = {
            k: True for k in target.ONE_TIME
        }
        life = target.audit(doc)["tracks"]["P5"]["arms"]["typed"]["lifecycle"]
        self.assertEqual(life["one_time_not_in_e2e_ms"], 0)
        self.assertEqual(life["amortized_one_time_ms_per_request"], 0)
        self.assertEqual(life["mean_e2e_plus_amortized_ms"], 10)

    def test_mixed_one_time_costs_count_missing_training_and_jit(self):
        doc = copy.deepcopy(self.doc)
        doc["tracks"]["P5"]["typed"]["one_time_in_e2e"]["load_ms"] = True
        life = target.audit(doc)["tracks"]["P5"]["arms"]["typed"]["lifecycle"]
        self.assertEqual(life["one_time_not_in_e2e_ms"], 8)
        self.assertAlmostEqual(life["mean_e2e_plus_amortized_ms"], 10 + 8 / 80)

    def test_p4_per_case_solver_overrun(self):
        self.rejected(lambda d: d["tracks"]["P4"]["tree_search"]["results"][0].update(
            measured_solver_ms=101), "actual P4 compute exceeded")

    def test_p4_per_case_solver_is_not_omitted(self):
        self.rejected(lambda d: d["tracks"]["P4"]["bellman"]["results"][0].pop(
            "measured_solver_ms"), "measurement")

    def test_cross_case_prediction_swap(self):
        self.rejected(lambda d: d["tracks"]["P0"]["granite_learned"]["results"][16].update(
            input_sha256=d["cases"][0]["input_sha256"]), "swapped input")

    def test_negative_future_net_utility_is_not_clamped_to_zero(self):
        doc = copy.deepcopy(self.doc)
        index = next(i for i, case in enumerate(doc["cases"])
                     if case["split"] == "future1")
        doc["tracks"]["P4"]["ndu_solver"]["results"][index]["observed_utility"] = -0.4
        output = target.audit(doc)
        future = output["tracks"]["P4"]["arms"]["ndu_solver"]["future1"]
        self.assertEqual(future["negative_utility_count"], 1)
        self.assertAlmostEqual(future["mean_observed_utility"], (15 * 0.6 - 0.4) / 16)
        self.assertLess(output["tracks"]["P4"]["paired_family_differences"]
                        ["ndu_solver__vs__bellman"]["future1"]
                        ["mean_paired_utility_difference"], -0.15)

    def test_failed_case_can_record_negative_penalty_without_success(self):
        doc = copy.deepcopy(self.doc)
        index = next(i for i, case in enumerate(doc["cases"])
                     if case["split"] == "future1")
        row = doc["tracks"]["P5"]["typed"]["results"][index]
        row.update(completed=False, observed_utility=-0.2,
                   observed_effect_sha256=None, recovery_status="blocked")
        future = target.audit(doc)["tracks"]["P5"]["arms"]["typed"]["future1"]
        self.assertAlmostEqual(future["accuracy"], 1)
        self.assertAlmostEqual(future["completed_and_correct_fraction"], 15 / 16)
        self.assertEqual(future["negative_utility_count"], 1)

    def test_negative_utility_outside_frozen_range_is_rejected(self):
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["results"][0].update(
            observed_utility=-1.0001), "signed utility")
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["results"][0].update(
            observed_utility=1.0001), "signed utility")
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["results"][0].update(
            observed_utility=True), "signed utility")

    def test_failed_case_cannot_claim_positive_net_utility(self):
        def fail_with_positive_utility(d):
            row = d["tracks"]["P5"]["typed"]["results"][0]
            row.update(completed=False, observed_utility=0.2,
                       observed_effect_sha256=None, recovery_status="blocked")
        self.rejected(fail_with_positive_utility, "failed task assigned positive utility")

    def test_no_result_deletion(self):
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["results"].pop(), "paired")

    def test_zero_latency_not_accepted(self):
        self.rejected(lambda d: d["tracks"]["P5"]["native_cpu"]["results"][0].update(end_to_end_ms=0), "measurement")

    def test_missing_energy_not_zero(self):
        self.rejected(lambda d: d["tracks"]["P0"]["laya_frozen"]["costs"].pop("energy_joules"), "incomplete lifecycle")

    def test_p2_unmatched_params(self):
        self.rejected(lambda d: d["tracks"]["P2"]["split_children"].update(trainable_parameters=9745), "parameter count")

    def test_p2_unmatched_data(self):
        self.rejected(lambda d: d["tracks"]["P2"]["split_children"].update(train_data_sha256=sha("changed")), "example exposure")

    def test_p2_more_data_must_be_real(self):
        self.rejected(lambda d: d["tracks"]["P2"]["parent_more_data"].update(train_cases=64), "additional independent exposure")

    def test_no_misleading_frozen_head(self):
        # The per-arm frozen immutability gate runs before paired scoring.
        self.rejected(lambda d: d["tracks"]["P1"]["shared_frozen"].update(
            final_head_sha256=sha("changed")), "frozen Head changed weights")

    def test_p4_cheap_no_fit_bellman_vs_trained_ndu_is_valid(self):
        arms = self.doc["tracks"]["P4"]
        self.assertEqual(arms["bellman"]["train_steps"], 0)
        self.assertEqual(arms["bellman"]["train_cases"], 0)
        self.assertEqual(arms["bellman"]["trainable_parameters"], 0)
        self.assertEqual(arms["bellman"]["costs"]["training_ms"], 0)
        self.assertGreater(arms["ndu_solver"]["train_steps"], 0)
        out = target.audit(self.doc)
        p4 = out["tracks"]["P4"]
        self.assertIs(p4["training_effort_not_implicitly_equalized"], True)
        self.assertEqual(p4["reported_training_control_census"]["bellman"]["train_steps"], 0)
        self.assertEqual(p4["reported_training_control_census"]["ndu_solver"]["train_steps"], 24)
        self.assertFalse(out["statistical_model_winner_selected"])
        self.assertEqual(out["authority"], "DENY_ALL")
        self.assertIn("ndu_solver__vs__no_search", p4["paired_family_differences"])

    def test_p4_cheap_bellman_cannot_pretend_to_fit(self):
        self.rejected(lambda d: d["tracks"]["P4"]["bellman"].update(
            train_steps=1), "P4 no-fit cheap control")

    def test_p4_zero_fit_control_cannot_hide_training_cost(self):
        self.rejected(lambda d: d["tracks"]["P4"]["bellman"]["costs"].update(
            training_ms=2.0), "P4 zero-step control claims training exposure or cost")

    def test_p4_no_search_must_not_report_solver_execution(self):
        self.rejected(lambda d: d["tracks"]["P4"]["no_search"]["results"][0].update(
            measured_solver_ms=1.0), "P4 no-search baseline cannot claim solver execution")

    def test_p4_bellman_must_not_claim_ndu_cost(self):
        self.rejected(lambda d: d["tracks"]["P4"]["bellman"]["costs"].update(
            ndu_ms=2.0), "P4 no-fit cheap control cannot claim NDU solver charges")

    def test_p4_trained_ndu_cannot_omit_training_charges(self):
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["costs"].update(
            training_ms=0.0), "P4 trained algorithm omitted training exposure or cost")

    def test_p4_both_trained_critic_and_ndu_must_share_data_exposure(self):
        self.rejected(lambda d: d["tracks"]["P4"]["critic"].update(
            train_data_sha256=sha("critic-replacement-data")),
            "P4 both-trained controls have unmatched training exposure")

    def test_p4_unequal_training_steps_remain_visible_and_costed(self):
        doc = copy.deepcopy(self.doc)
        ndu = doc["tracks"]["P4"]["ndu_solver"]
        ndu["train_steps"] = 25
        ndu["costs"]["training_ms"] = 5.0
        p4 = target.audit(doc)["tracks"]["P4"]
        self.assertEqual(p4["reported_training_control_census"]["ndu_solver"]["train_steps"], 25)
        self.assertEqual(p4["reported_training_control_census"]["critic"]["train_steps"], 24)
        self.assertEqual(p4["reported_training_control_census"]["ndu_solver"]["training_ms"], 5.0)
        self.assertGreater(
            p4["arms"]["ndu_solver"]["lifecycle"]["amortized_one_time_ms_per_request"],
            p4["arms"]["bellman"]["lifecycle"]["amortized_one_time_ms_per_request"],
        )

    def test_v3_p4_claim_cannot_be_mislabeled_v4(self):
        self.rejected(lambda d: d.update(
            schema="hepta.six-track-paired-observation.v3"), "non-authorizing")

    def test_p4_equal_budget(self):
        self.rejected(lambda d: d["tracks"]["P4"]["bellman"].update(compute_budget_ms=101), "compute budgets")

    def test_p4_ndu_total_underreport_is_rejected(self):
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["costs"].update(
            ndu_ms=101), "NDU aggregate cost underreports")

    def test_p4_total_cost_above_per_case_budget_is_valid(self):
        out = target.audit(self.doc)["tracks"]["P4"]["arms"]["ndu_solver"]
        self.assertEqual(self.doc["tracks"]["P4"]["ndu_solver"]["compute_budget_ms"], 100)
        self.assertEqual(self.doc["tracks"]["P4"]["ndu_solver"]["costs"]["ndu_ms"], 336)
        self.assertEqual(out["future1"]["case_count"], 16)

    def test_p5_wrong_effect(self):
        self.rejected(lambda d: d["tracks"]["P5"]["native_cpu"]["results"][2].update(
            observed_effect_sha256=sha("different-effects")), "different physical effect")

    def test_p5_uncertain_outcome_not_clean_failure(self):
        def edit(d):
            d["tracks"]["P5"]["native_cpu"]["results"][0].update(completed=False, observed_utility=0.0)
        self.rejected(edit, "unreconciled")

    def test_p3_requires_output_artifact(self):
        self.rejected(lambda d: d["tracks"]["P3"]["multimodal_generator"]["results"][0].pop(
            "generated_artifact_sha256"), "SHA256")

    def test_extreme_scalar_must_not_overflow_or_poison_accounting(self):
        self.rejected(lambda d: d["tracks"]["P5"]["native_cpu"]["costs"].update(
            training_ms=10**350), "physical measurement")
        self.rejected(lambda d: d["tracks"]["P5"]["native_cpu"]["costs"].update(
            training_ms=10**19), "physical measurement")
        self.rejected(lambda d: d["tracks"]["P5"]["native_cpu"]["results"][0].update(
            end_to_end_ms=10**350), "physical measurement")

    def test_extreme_negative_utility_must_not_overflow(self):
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["results"][0].update(
            observed_utility=-(10**350)), "signed utility")
        self.rejected(lambda d: d["tracks"]["P4"]["ndu_solver"]["results"][0].update(
            observed_utility=float("inf")), "signed utility")

    def test_bool_cannot_be_a_numeric_metric(self):
        self.rejected(lambda d: d["tracks"]["P5"]["typed"]["costs"].update(cpu_ms=True), "measurement")

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"bad.json"
            p.write_text('{"ok":1,"ok":2}', encoding="utf-8")
            with self.assertRaisesRegex(target.Invalid, "duplicate JSON key"):
                target.load_json(p)

    def test_nan_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"bad.json"
            p.write_text('{"ok":NaN}', encoding="utf-8")
            with self.assertRaises(target.Invalid):
                target.load_json(p)

    def test_full_file_parse_and_observation_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"observations.json"
            p.write_text(json.dumps(self.doc, allow_nan=False), encoding="utf-8")
            obj, digest = target.load_json(p)
            self.assertEqual(digest, hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(target.audit(obj)["schema"], "hepta.six-track-descriptive-adjudication.v4")


if __name__ == "__main__":
    unittest.main()
