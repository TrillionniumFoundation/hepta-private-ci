"""Materialize the reviewable R2 addendum; no acquisition, model, or evaluator.

The inherited fields are byte-authenticated and never rewritten in their source.
New numeric choices are a preregistration candidate, not allocated compute or a
claim that the missing trainer, custody owner, or candidate checkpoints exist.
"""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LEGACY = ROOT / "source-recovery/fixed/r2_PARTIAL_FREEZE.json"
LEGACY_SHA = "f720cbb1e97087c8be4ffaec5f006589876b1b3e67dba1cc7ea47c93f4bb108b"


def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def write(name, value):
    path = ROOT / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f"Refusing to overwrite a different frozen candidate: {name}")
    path.write_bytes(raw)
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    legacy = json.loads(LEGACY.read_bytes())
    if digest(legacy["frozen"]) != LEGACY_SHA:
        raise ValueError("Inherited preregistration changed")
    schedules = [
        ["stop"],
        ["text", "draft", "stop"],
        ["perceive", "text", "draft", "stop"],
        ["perceive", "draft", "text", "stop"],
        ["perceive", "text", "draft", "verify", "stop"],
        ["perceive", "draft", "text", "verify", "stop"],
        ["perceive", "text", "draft", "refine", "verify", "stop"],
        ["perceive", "text", "draft", "verify", "refine", "verify", "stop"],
        ["perceive", "text", "draft", "verify", "revise", "text", "draft", "verify", "stop"],
        ["perceive", "text", "draft", "verify", "revise", "text", "refine", "verify", "stop"],
        ["text", "draft", "verify", "revise", "text", "refine", "verify", "stop"],
        ["perceive", "text", "draft", "draft", "verify", "stop"],
    ]
    baselines = {
        "schema": "hepta.r2.baseline-contract.v1",
        "status": "algorithms_and_search_sets_declared_implementations_unbound",
        "method_ids": ["00", "10", "01", "11", "greedy", "planner", "retrieval"],
        "fixed_reference_alias": "00",
        "alias_rule": "fixed is the 00 execution, not a second episode or duplicated physical cost",
        "fixed": {"candidate_schedules": schedules, "candidate_ids": [digest(s) for s in schedules],
                  "selection": "highest validation CE; exact tie uses lexicographically smallest schedule digest",
                  "runtime": "existing FixedSchedule.choose; no actor at ordinary fixed/STOP steps",
                  "scope": "best in this 12-schedule library, not an unrestricted optimal fixed policy"},
        "greedy": {"rule": "For every legal next action, predict one-step incremental independent utility minus its execution and decision cost from the current public View. Choose the highest strictly positive prediction; otherwise STOP. Exact ties use ACTIONS order.",
                   "value_model_training_data": "train-only executed transitions with independent development utility; no test or future executed branch outcome",
                   "regularization_grid": [0.001, 0.01, 0.1, 1.0],
                   "maximum_predictions_per_decision": 7,
                   "implementation_source_sha": None, "predictor_checkpoint_sha256": None,
                   "rejected_substitute": "historical actor-logit argmax"},
        "planner": {"rule": "Deterministic bounded beam search through a train-only learned transition/value model over the same legal public-state actions. Predictions remain labelled predictions. No unexecuted provider outcome or test score is available. Execute only the selected first action, then replan from actual public observations.",
                    "depth_grid": [2, 3], "beam_grid": [2, 4], "expansion_cap_grid": [8, 16],
                    "maximum_model_calls_per_decision": 16,
                    "cost_rule": "Charge every prediction/expansion and any actually executed branch; preserve all unselected work and partially generated artifacts.",
                    "implementation_source_sha": None, "transition_checkpoint_sha256": None,
                    "value_checkpoint_sha256": None,
                    "rejected_substitute": "historical mechanism DP supplied with known neural counterfactual outcomes"},
        "retrieval": {"feature": "mean-pooled frozen pinned VLM vision features",
                      "distance": "cosine similarity; exact tie by source SHA256",
                      "index_population": "train-only clusters and approved output bundles",
                      "top_k_grid": [1, 3, 5], "threshold_grid": [0.0, 0.25, 0.5, 0.75],
                      "return_rule": "Return the top-ranked complete bundle meeting the validation-selected threshold; otherwise abstain. No test-labelled reranker.",
                      "implementation_source_sha": None, "index_sha256": None,
                      "cost_rule": "Index acquisition/build/verification/storage and all query encoding/ranking are recorded; build cost is not zero or charged once per arm."},
        "selection": {"data": "validation only", "objective": "same gamma-2 CE after declared costs",
                      "strong_reference_candidates": ["00", "greedy", "planner", "retrieval"],
                      "strong_reference": None,
                      "tie_break": "lexicographic method ID, then immutable configuration digest",
                      "retain": "all candidates, validation scores, failed/rejected trials, physical costs and search order",
                      "test_usage": "all seven methods are reported; the strongest reference identity is fixed before test dispatch"},
        "implementation_qualification": False,
    }
    data = {
        "schema": "hepta.r2.new-data-contract.v1",
        "status": "NO_INDEPENDENT_NEW_TEST_AVAILABLE",
        "eligible_population": "newly captured natural still images supporting a visible-facts explanation and simple diagram; no diagnosis, hidden identity, or facts not observable in the image",
        "preferred_provenance": "new acquisition after the independent data owner signs the protocol seal; signed capture/release record and permission chain, not EXIF or upload timestamp alone",
        "fallback": "previously unexposed public assets require independent source-cluster and all-prior-cohort audit; upload recency alone never qualifies",
        "unit": "one independently sourced scene/event/capture-session cluster, one primary image and one preassigned neutral instruction",
        "cluster_rule": "same capture session, scene/event, video/burst, originating document, derivative/crop or near-duplicate group stays in one source cluster; repeated author alone is flagged for higher-level sensitivity, not presumed independent",
        "primary_image_rule": "within a qualified cluster choose lexicographically smallest content SHA256 before model evaluation",
        "instructions": [
            "Describe the visible objects and their spatial relations, then produce a simple diagram consistent with that description. Do not add facts that are not visible.",
            "Explain what is visibly present in the image and provide a simple matching diagram. If a detail cannot be determined from the image, leave it unspecified.",
        ],
        "instruction_assignment": "SHA256(protocol digest || opaque source_cluster_id) modulo 2; evaluator checks balance before sealing, never chooses by model response",
        "draws_per_source": 2,
        "draw_rule": "same primary image/instruction, two precommitted execution RNG draws, nested within source; not independent images or tasks",
        "split_rule": "independent owner groups first, excludes all exposed clusters, then assigns train/validation/test by a committed secret randomization seed; no split is performed by this package",
        "counts": {"development_pilot_clusters_max": 32, "train_clusters": None,
                   "validation_clusters": None, "test_count_candidate_grid": [128, 256, 512, 1024, 2048],
                   "selected_test_clusters": None},
        "selection_before_test": "Select the smallest candidate test count reaching the declared precision/power criteria using independent development-only variance and cost measurements; if none qualify, stop before collecting/opening test. The count is immutable once selected.",
        "public_manifest_fields": ["opaque_source_id", "source_cluster_id", "content_sha256", "capture_or_release_utc", "provenance_receipt_sha256", "license_or_permission", "split", "perceptual_duplicate_group", "instruction_sha256", "label_manifest_commitment"],
        "evaluator_private_fields": ["test bytes", "references", "labels", "capture identity keys", "randomization secret", "blind arm order"],
        "custody": {"owner": None, "trainer_identity": None, "evaluator_identity": None,
                    "access_denial_receipts": None, "dispatch_receipt": None,
                    "rule": "separate actual owner and OS/capability boundary; a shared workspace, another agent, chmod0700, or a claimed JSON owner is insufficient"},
        "test_seal_sequence": ["freeze protocol and development-only plan", "provision independent owner and verify trainer denial", "acquire new clusters with provenance and permissions", "audit exact/perceptual/source overlap against all prior cohorts", "freeze split/count/instructions/label rubric and commitments", "finish all training and validation selection", "freeze candidate/index/checkpoint/source hashes", "owner dispatches one complete fixed test panel", "owner exports signed capture roster and blinded outcomes"],
        "exclusions": {"r1_all_original_generated_blank_and_derivatives": True,
                       "historical_v2_v3_and_reserved_confirmation_without_new_proof": True,
                       "availability_batch_20261105_all_24_metadata_candidates": True,
                       "exposed_image_sha256": ["5e89b31717bcbe16e5dc5a6ccd67c99fb431000e1416956e326b826d807cf09a", "4b16f32ff4df05d64ddafde644591ac890e8f92b93b93f8211d50419f96be44a"],
                       "no_reclassification_of_quarantine_as_test": True},
        "test_opened": False, "test_sealed": False,
    }
    rubric = {
        "schema": "hepta.r2.utility-power-candidate.v1",
        "status": "PRE_OUTCOME_CHOICES_FOR_REVIEW_NOT_VALIDATED_EVALUATOR",
        "utility_domain": [-1.0, 1.0],
        "components": {"visible_fact_grounding": 0.4, "instruction_completion": 0.25,
                       "text_diagram_consistency": 0.2, "legibility": 0.15},
        "component_values": [0.0, 0.25, 0.5, 0.75, 1.0],
        "delivered_utility": "2 * weighted_quality - 1; any critical invented visible fact or contradictory diagram sets quality=0 and utility=-1",
        "abstention_utility": 0.0,
        "failure_utilities": {s: -1.0 for s in ["failed", "cancelled", "timeout", "incomplete"]},
        "rater_process": "two independently assigned blind raters; scores and reasons retained; a third blind adjudicator resolves any critical-error disagreement or component spread >=0.5 before arm identity is released",
        "independent_evaluator_implemented": False,
        "minimum_meaningful_ce_gain": 0.02,
        "minimum_gain_interpretation": "one percent of the declared [-1,1] utility range; a research decision threshold chosen before R2 outcomes, not proven production value",
        "joint_required_lower_bounds": {"controller_given_generator_training": 0.02,
                                        "joint_vs_baseline": 0.02,
                                        "joint_vs_strong_reference": 0.02},
        "quality_floors": {"mean_quality_lower_bound": 0.75, "critical_error_rate_upper_bound": 0.01,
                           "noninferiority_vs_selected_reference_quality_lower_bound": -0.02},
        "floor_inference": "three separately preregistered one-sided familywise95% bounds using source-cluster/fit structure; validate the binary rare-error bound with the independent evaluator, not ordinary per-draw binomial counting",
        "power_target": 0.8, "minimum_alternative_ce_gain_for_power": 0.04,
        "precision_target_primary_ci_halfwidth": 0.02,
        "power_data": "new development pilot only; no R1 six cases, test scores, or old synthetic matrix substituted for real-task variance",
        "power_method": "fit a development-only crossed fit/source variance model and calibrate simulations at the fixed gamma2 CE and seven-contrast multiplicity; count whole failed fits and source clusters; freeze code/input hashes and selected N before test acquisition",
        "power_implemented_or_demonstrated": False,
        "no_update_if": ["any readiness gate is open", "capture is incomplete or costs unknown", "any required benefit lower bound fails", "any independent quality/safety floor fails"],
        "automatic_promotion": False,
    }
    budget = {
        "schema": "hepta.r2.budget-contract.v1", "status": "UNALLOCATED_NO_EXECUTION_AUTHORIZATION",
        "primary_estimand": "same_total_budget",
        "allocation": "same maximum total training+search+selection allowance per complete fit/arm; unused allowance is not charged as spending; actual spend is reported, including all failed and unselected work",
        "independent_fits": 32, "full_trainable_arm_fits": 96,
        "00_receipt": "explicit no-gradient/frozen-byte receipt per paired execution block; not 32 newly trained base models",
        "numeric_caps_requiring_development_measurement": {"total_cpu_seconds_per_fit_arm": None,
                                                          "total_wall_seconds_per_fit_arm": None,
                                                          "peak_memory_bytes": None,
                                                          "data_acquisition_bytes": None,
                                                          "retained_disk_bytes": None,
                                                          "total_study_cpu_seconds": None},
        "inference_candidate_limits": {"decision_horizon": 10, "deadline_seconds": 600.0,
                                       **legacy["frozen"]["common_inference_limits"]},
        "deadline_scope": "existing synchronous runner checks after provider return; no hard-deadline guarantee. A separately qualified runner is needed to enforce physical process budgets and retain unknown/killed outcomes.",
        "cpu_tariff": 0.02, "wall_tariff": 0.001,
        "real_action_service_tariffs": {a: None for a in ["perceive", "text", "draft", "revise", "refine", "verify", "stop", "controller", "finalize"]},
        "tariff_rule": "all explicit values and units must be sealed before training; no inherited zero default is an admissible unknown-cost conversion",
        "event_categories": legacy["frozen"]["cost_contract"]["exclusive_categories"],
        "outer_scopes": legacy["frozen"]["cost_contract"]["outer_scopes"],
        "physical_event_rules": ["event IDs are fixed by an independently retained capture roster", "identical receipt retry counts once; conflicting duplicate fails", "no cross-arm or outer/episode event reuse", "inclusive envelopes are reported separately and never summed with exclusive leaves", "missing/rejected/partial/unselected work cannot be dropped", "unknown cost is null with reason, never zero"],
        "required_measurements": ["inclusive parent wall envelope", "exclusive CPU including reaped children", "exclusive wall", "peak RSS bytes", "network payload bytes", "retained disk bytes", "actual metered energy or explicit unknown", "all setup/training/validation/analysis/publication costs"],
        "confirmatory_episode_formula": "32 fits * N independently sourced clusters * 2 nested draws * 7 methods",
        "episode_counts_by_N": {str(n): 32*n*2*7 for n in data["counts"]["test_count_candidate_grid"]},
        "upper_envelope_is_not_actual_cost": True,
        "compute_reserved": False, "native_training_budget_measured": False,
    }
    protocol = {
        "schema": "hepta.r2.executable-preregistration-candidate.v3",
        "status": "EXECUTABLE_ACCOUNTING_AND_ANALYSIS_CONTRACT_WITH_SIX_OPEN_ADMISSION_GATES",
        "source_sha": legacy["frozen"]["source_commit"], "source_tree": legacy["frozen"]["source_tree"],
        "evidence_pr": 4857, "evidence_head": "de2b1212242cfa6f25563b99a385497a86dc7e49",
        "inherited_frozen_fields_sha256": LEGACY_SHA, "inherited_fields_preserved": True,
        "inherited": legacy["frozen"],
        "addendum_contracts": {"baselines": digest(baselines), "data": digest(data),
                               "rubric": digest(rubric), "budget": digest(budget)},
        "analysis": {"methods": baselines["method_ids"], "gamma": 2.0,
                     "fit_seeds": legacy["frozen"]["statistical_design"]["fit_seeds"],
                     "draws": [0, 1], "bootstrap_replicates": 99999, "bootstrap_seed": 4835202611,
                     "rng": "NumPy PCG64; independent multinomial fit and cluster counts; all methods/draws remain paired",
                     "interval_rule": "sorted percentile order statistics: floor(p*(B-1)) lower, ceil((1-p)*(B-1)) upper; p=0.05/(2*7)",
                     "effect_formulas": legacy["frozen"]["contrasts"],
                     "old_analyzer_gap": "975e factorial.analyze supports six effects, B<=10000 and unadjusted95%; do not use it as the seven-contrast confirmatory engine",
                     "new_engine_scope": "read-only arithmetic and capture accounting; it authenticates neither evaluator custody nor truth of signed observations"},
        "remaining_gate_ids": [g["id"] for g in legacy["remaining_gates"]],
        "fully_sealed": False, "training_performed": False, "test_opened": False,
        "candidate_weights_created": False, "production_qualified": False, "no_update": True,
    }
    files = [write("BASELINE_CONTRACT.json", baselines), write("DATA_CONTRACT.json", data),
             write("UTILITY_AND_POWER.json", rubric), write("BUDGET_CONTRACT.json", budget),
             write("PROTOCOL.json", protocol)]
    readiness = {
        "schema": "hepta.r2.readiness-input.v1", "protocol_sha256": digest(protocol),
        "actual_gates": {g["id"]: {"status": "OPEN", "evidence_sha256": None,
                                    "requirement": g["required"]} for g in legacy["remaining_gates"]},
        "selected_test_clusters": None, "strong_reference": None,
        "actual_test_manifest": None, "actual_candidate_manifest": None,
        "trainer_entrypoint": None, "evaluator_owner": None,
        "permitted_now": ["development-only source review", "protocol review", "synthetic format/arithmetic controls"],
        "model_calls": 0, "training_calls": 0, "evaluation_calls": 0,
        "reason": "No independently sealed new test, real trainer, admitted budget/baselines, validated evaluator or new candidates exists in the inspected evidence.",
    }
    files.append(write("READINESS_INPUT.json", readiness))
    print(json.dumps({"files": files, "protocol_sha256": digest(protocol), "no_update": True}, indent=2))


if __name__ == "__main__":
    main()
