"""Deterministic reference tests; synthetic fixtures are NOT evidence of efficacy."""

from __future__ import annotations

import copy
import json
import math
import random
import unittest

import ndu_dmgp as d


def fixture() -> dict:
    rng = random.Random(20261023)
    manifest = {
        "objective_digest": "objective-frozen-digest",
        "dataset_digest": "dataset-frozen-digest",
        "current_snapshot_digest": "generation-17-frozen",
        "next_snapshot_digest": "generation-18-candidate",
        "current_generation": 17,
        "next_generation": 18,
        "critic_digest": "critic-frozen-version",
        "policy_digest": "actor-proposal-version",
        "observer_id": "eval-independent",
        "actor_id": "actor-owner",
        "critic_owner_id": "critic-owner",
        "hardware_digest": "host-reference-digest",
        "semantic_plan_schema_digest": "semantic-plan-schema-v1",
        "compute_budget_units": 8_000_000,
        "independent_metric_digest": "external-quality-profile-digest",
        "max_policy_kl": 0.05,
        "arms": list(d.ARMS),
        "joint_action_width": 3,
        "outcome_metric_frozen": True,
        "split_assignment_frozen": True,
        "mode": "reference_fixture",
    }
    runs = []
    for split, n in (("future", 40), ("retention", 40)):
        for ix in range(n):
            eps = f"{split}-episode-{ix:03d}"
            group = f"{split}-independent-group-{ix:03d}"
            noise = rng.uniform(-0.01, 0.01)
            for ai, arm in enumerate(d.ARMS):
                benefit = [0, .02, .04, .08, .11, .18][ai]
                if split == "retention":
                    benefit = [0, .01, .01, .01, .005, .012][ai]
                decoder = 5_000_000 - ai * 270_000
                ctrl = 60_000 + ai * 20_000
                runs.append({
                    "split": split, "arm": arm, "episode_id": eps, "group_id": group,
                    "objective_digest": manifest["objective_digest"],
                    "snapshot_digest": manifest["current_snapshot_digest"],
                    "critic_digest": manifest["critic_digest"],
                    "observer_id": manifest["observer_id"],
                    "hardware_digest": manifest["hardware_digest"],
                    "outcome_receipt_digest": f"outcome-{eps}-{arm}",
                    "run_receipt_digest": f"run-{eps}-{arm}",
                    "evaluated_arm": arm,
                    "input_digest": f"frozen-input-{eps}",
                    "semantic_plan_digest": f"plan-{eps}",
                    "admitted_compute_budget_units": manifest["compute_budget_units"],
                    "measured_compute_units": decoder + ctrl,
                    "independent_observed_outcome": True,
                    "hard_constraints_ok": True,
                    "utility": .25 + benefit + noise,
                    "quality": .80 + ai * .001 + noise * .1,
                    "elapsed_ns": decoder + ctrl + 150_000,
                    "decoder_ns": decoder, "controller_ns": ctrl,
                    "peak_rss_bytes": 200_000_000 - ai * 1_000_000,
                    "policy_kl": 0.001 * ai,
                    "modalities": ["text", "image"],
                    "consistency": {
                        "semantic_plan_digest": f"plan-{eps}",
                        "semantic_plan_schema_digest": manifest["semantic_plan_schema_digest"],
                        "verifier_id": manifest["observer_id"],
                        "bidirectional_checked": True,
                        "evidence_digest": f"crossmodal-evidence-{eps}-{arm}",
                        "entity_violations": 0, "timeline_violations": 0,
                        "semantic_agreement": .95,
                    },
                })
    covariance = []
    for i in range(56):
        z = [rng.gauss(0, 0.3) for _ in range(3)]
        covariance.append({
            "group_id": f"joint-{i}", "split": "train",
            "condition_digest": "frozen-condition-bin-1",
            "weight": 1,
            "advantages": [z[0] + z[1] * .2, z[1] + z[0] * .3, z[2] + z[1] * .1],
        })
    closure = []
    for split, n in (("train", 90), ("future", 45)):
        for i in range(n):
            s = rng.uniform(-1, 1)
            h = rng.uniform(-1, 1)
            closure.append({
                "split": split, "group_id": f"closure-{split}-{i}",
                "state": s, "history": h,
                "next_outcome": .45 * s + rng.uniform(-.03, .03),
            })
    credits = []
    for i in range(40):
        reference = .25 + rng.uniform(-.015, .015)
        credits.append({
            "group_id": f"credit-{i}",
            "objective_digest": manifest["objective_digest"],
            "observer_id": manifest["observer_id"],
            "only_one_cell_changed": True,
            "independent_full_circuit_outcome": True,
            "randomized_or_matched_intervention": True,
            "counterfactual_support_digest": f"matched-experiment-{i}",
            "reference_joint_utility": reference,
            "joint_utility": reference + .09 + rng.uniform(-.01, .01),
        })
    return {"manifest": manifest, "runs": runs, "joint_trials": covariance,
            "closure_probe": closure, "credit_pairs": credits}


class QualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = fixture()

    def test_complete_fixture_clears_reference_gates_but_not_production(self) -> None:
        out = d.evaluate(self.bundle)
        self.assertTrue(out["reference_checks_passed"])
        self.assertFalse(out["production_qualified"])
        self.assertEqual(len(out["comparisons_vs_A0"]), 5)
        self.assertEqual(out["covariance"]["rank"], 2)
        self.assertEqual(out["covariance"]["n"], 56)
        self.assertGreater(out["comparisons_vs_A0"]["A5"]["lcb"], 0)
        self.assertGreater(out["net_compute_saving_ns"]["lcb"], 0)
        self.assertGreater(out["wall_latency_saving_ns"]["lcb"], 0)
        self.assertEqual(out, d.evaluate(self.bundle))
        self.assertEqual(len(out["report_digest"]), 64)

    def assert_rejects(self, expected: str) -> None:
        with self.assertRaises(d.EvidenceError) as caught:
            d.evaluate(self.bundle)
        self.assertIn(expected, str(caught.exception))

    def test_self_scored_reward_rejected(self) -> None:
        self.bundle["runs"][0]["independent_observed_outcome"] = False
        self.assert_rejects("self-scored")

    def test_actor_critic_observer_collusion_rejected(self) -> None:
        self.bundle["manifest"]["critic_owner_id"] = "actor-owner"
        self.assert_rejects("independent owners")

    def test_drifting_objective_rejected(self) -> None:
        self.bundle["runs"][5]["objective_digest"] = "rewritten-goal"
        self.assert_rejects("objective_digest")

    def test_snapshot_mutation_rejected(self) -> None:
        self.bundle["manifest"]["next_snapshot_digest"] = "generation-17-frozen"
        self.assert_rejects("current-run")

    def test_stale_next_generation_rejected(self) -> None:
        self.bundle["manifest"]["next_generation"] = 17
        self.assert_rejects("later generation")

    def test_unfrozen_metric_rejected(self) -> None:
        self.bundle["manifest"]["outcome_metric_frozen"] = False
        self.assert_rejects("unfrozen external metric")

    def test_kl_trust_region_rejected(self) -> None:
        self.bundle["runs"][4]["policy_kl"] = .09
        self.assert_rejects("policy_kl")

    def test_mixed_critic_rejected(self) -> None:
        self.bundle["runs"][4]["critic_digest"] = "critic-updated-to-game-metric"
        self.assert_rejects("critic_digest")

    def test_cross_modal_semantic_plan_rejected(self) -> None:
        self.bundle["runs"][0]["consistency"]["semantic_plan_digest"] = "changed"
        self.assert_rejects("semantic plan")

    def test_cross_modal_backward_missing_rejected(self) -> None:
        self.bundle["runs"][0]["consistency"]["bidirectional_checked"] = False
        self.assert_rejects("bidirectional")

    def test_cross_modal_entity_violation_rejected(self) -> None:
        self.bundle["runs"][0]["consistency"]["entity_violations"] = 1
        self.assert_rejects("entity/timeline")

    def test_cross_modal_audio_video_sync_limit_rejected(self) -> None:
        self.bundle["runs"][0]["modalities"] = ["audio", "video"]
        self.bundle["runs"][0]["consistency"]["av_sync_ms"] = 99
        self.assert_rejects("av_sync_ms")

    def test_no_crossmodal_modality_rejected(self) -> None:
        self.bundle["runs"][0]["modalities"] = ["text"]
        self.assert_rejects("two unique output")

    def test_nan_cost_rejected(self) -> None:
        self.bundle["runs"][0]["elapsed_ns"] = math.nan
        self.assert_rejects("elapsed_ns")

    def test_incomplete_arm_rejected(self) -> None:
        self.bundle["runs"] = [r for r in self.bundle["runs"]
                               if not (r["arm"] == "A5" and r["episode_id"] == "future-episode-000")]
        self.assert_rejects("incomplete A0-A5 pairing")

    def test_reused_independent_group_rejected(self) -> None:
        for row in self.bundle["runs"]:
            if row["episode_id"] == "future-episode-001":
                row["group_id"] = "future-independent-group-000"
        self.assert_rejects("correlated group reuse")

    def test_missing_future_sample_rejected(self) -> None:
        self.bundle["runs"] = [r for r in self.bundle["runs"]
                               if not (r["split"] == "future" and int(r["episode_id"].split("-")[-1]) >= 25)]
        self.assert_rejects("paired episodes")

    def test_unlabeled_fallback_cannot_impersonate_a5(self) -> None:
        self.bundle["runs"][5]["evaluated_arm"] = "A3"
        self.assert_rejects("unlabeled policy fallback")

    def test_a5_incremental_gain_over_router_is_required(self) -> None:
        for row in self.bundle["runs"]:
            if row["arm"] == "A2" and row["split"] == "future":
                row["utility"] = .70
        out = d.evaluate(self.bundle)
        self.assertFalse(out["gates"]["a5_beats_router"])

    def test_a5_incremental_gain_over_covariance_portfolio_required(self) -> None:
        for row in self.bundle["runs"]:
            if row["arm"] == "A4" and row["split"] == "future":
                row["utility"] = .70
        out = d.evaluate(self.bundle)
        self.assertFalse(out["gates"]["a5_beats_a4_portfolio"])

    def test_unequal_input_across_arms_rejected(self) -> None:
        self.bundle["runs"][4]["input_digest"] = "different-input"
        self.assert_rejects("unequal multimodal input")

    def test_unequal_semantic_plan_across_arms_rejected(self) -> None:
        self.bundle["runs"][4]["semantic_plan_digest"] = "different-plan"
        self.bundle["runs"][4]["consistency"]["semantic_plan_digest"] = "different-plan"
        self.assert_rejects("unequal shared plan")

    def test_unequal_precommitted_budget_rejected(self) -> None:
        self.bundle["runs"][4]["admitted_compute_budget_units"] = 10_000_000
        self.assert_rejects("unequal precommitted")

    def test_measured_budget_exceed_rejected(self) -> None:
        self.bundle["runs"][4]["measured_compute_units"] = 9_000_000
        self.assert_rejects("measured_compute_units")

    def test_covariance_future_leakage_rejected(self) -> None:
        self.bundle["joint_trials"][0]["split"] = "future"
        self.assert_rejects("evaluation/future leakage")

    def test_covariance_reused_future_group_rejected(self) -> None:
        self.bundle["joint_trials"][0]["group_id"] = "future-independent-group-000"
        self.assert_rejects("training/evaluation group leakage")

    def test_covariance_context_drift_rejected(self) -> None:
        self.bundle["joint_trials"][10]["condition_digest"] = "leaked-future-conditioning"
        self.assert_rejects("mixed pre-decision")

    def test_covariance_rank_collapse_requires_deterministic_fallback(self) -> None:
        for row in self.bundle["joint_trials"]:
            row["advantages"] = [.4, .4, .4]
        self.assert_rejects("unidentifiable rank")

    def test_covariance_insufficient_support_rejected(self) -> None:
        self.bundle["joint_trials"] = self.bundle["joint_trials"][:15]
        self.assert_rejects("insufficient matched")

    def test_covariance_effective_sample_size_rejected(self) -> None:
        for row in self.bundle["joint_trials"]:
            row["weight"] = .00001
        self.bundle["joint_trials"][0]["weight"] = 100
        self.assert_rejects("effective sample size")

    def test_credit_not_local_reward_rejected(self) -> None:
        self.bundle["credit_pairs"][1]["independent_full_circuit_outcome"] = False
        self.assert_rejects("local reward")

    def test_credit_wrong_observer_rejected(self) -> None:
        self.bundle["credit_pairs"][1]["observer_id"] = "critic-owner"
        self.assert_rejects("observer mismatch")

    def test_observed_mode_requires_trust_root(self) -> None:
        self.bundle["manifest"]["mode"] = "observed"
        self.assert_rejects("observer_trust_root_digest")

    def test_no_real_computational_gain_is_visible_blocker(self) -> None:
        for row in self.bundle["runs"]:
            if row["arm"] == "A5":
                row["decoder_ns"] += 3_000_000
                row["elapsed_ns"] += 3_000_000
                row["measured_compute_units"] = min(
                    self.bundle["manifest"]["compute_budget_units"], row["decoder_ns"] + row["controller_ns"])
        out = d.evaluate(self.bundle)
        self.assertFalse(out["gates"]["controller_net_compute_saving"])
        self.assertFalse(out["reference_checks_passed"])

    def test_no_ndu_gain_is_visible_blocker(self) -> None:
        for row in self.bundle["runs"]:
            if row["arm"] == "A5" and row["split"] == "future":
                row["utility"] = .1
        out = d.evaluate(self.bundle)
        self.assertFalse(out["gates"]["a5_future_ndu_gain"])

    def test_retention_loss_is_visible_blocker(self) -> None:
        for row in self.bundle["runs"]:
            if row["arm"] == "A5" and row["split"] == "retention":
                row["utility"] = .1
        self.assertFalse(d.evaluate(self.bundle)["gates"]["retention_noninferiority"])

    def test_compressed_state_missing_history_is_visible_blocker(self) -> None:
        for row in self.bundle["closure_probe"]:
            row["next_outcome"] += 0.45 * row["history"]
        self.assertFalse(d.evaluate(self.bundle)["gates"]["no_history_dependence_detected"])

    def test_credit_only_marginal_harm_is_visible_blocker(self) -> None:
        for row in self.bundle["credit_pairs"]:
            row["joint_utility"] = row["reference_joint_utility"] - .08
        self.assertFalse(d.evaluate(self.bundle)["gates"]["supported_positive_full_circuit_credit"])


if __name__ == "__main__":
    unittest.main()
