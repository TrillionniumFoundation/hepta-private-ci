"""Report the frozen gates and their limits without introducing a new gate."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ..freeze import verify


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(root, relative):
    return json.loads((root / relative).read_text())


def build(root, output):
    frozen = verify(root)
    calibration = load(root, "calibration_confirmation/RESULTS.json")
    runtime = load(root, "RUNTIME_RESULTS.json")
    review = load(root, "reviews/RUNTIME_FINAL_REVIEW.json")
    calibration_binding = load(root, "reviews/CALIBRATION_CONFIRM_REVIEW_BINDING.json")
    if (calibration_binding["passed"] is not True or calibration_binding["before_after_identical"] is not True
            or calibration_binding["results_sha256"] != digest(root / "calibration_confirmation/RESULTS.json")
            or digest(root / calibration_binding["bound_review_path"]) != calibration_binding["bound_review_sha256"]):
        raise ValueError("Current calibration result/review binding differs")
    actual_calibration_files = {str(path.relative_to(root)): digest(path)
                               for path in (root / "calibration_confirmation").rglob("*") if path.is_file()}
    if actual_calibration_files != calibration_binding["confirmation_files_sha256"]:
        raise ValueError("Current calibration confirmation inputs differ from the bound audit")
    reviews = {
        "prefreeze": "validation/PREFREEZE_REVIEW.json",
        "calibration_preparation": "reviews/CALIBRATION_PREPARE_REVIEW.json",
        "runtime_preparation": "runtime_preparation_review/REVIEW.json",
        "calibration_confirmation_original": "reviews/CALIBRATION_CONFIRM_REVIEW.json",
        "calibration_confirmation_bound": calibration_binding["bound_review_path"],
        "calibration_confirmation_binding": "reviews/CALIBRATION_CONFIRM_REVIEW_BINDING.json",
        "runtime_confirmation": "reviews/RUNTIME_FINAL_REVIEW.json",
    }
    for name, relative in reviews.items():
        if load(root, relative)["passed"] is not True:
            raise ValueError("Independent evidence review is incomplete: " + name)
    if (not runtime["complete"] or review["results_sha256"] != digest(root / "RUNTIME_RESULTS.json")
            or runtime["acceptance"] != review["acceptance"]):
        raise ValueError("Runtime summary/review binding differs")
    for seed in runtime["seeds"]:
        relative = f"runtime_confirmation/seed_{seed}/AUDIT.json"
        if load(root, relative)["passed"] is not True:
            raise ValueError("Missing successful formal native replay: " + str(seed))
    profiles = {}
    for name in ("mixture_zero", "mixture_context"):
        row = calibration["arms"][name]
        profiles[name] = {
            "public_context_histories_per_query": 8 if name == "mixture_context" else 0,
            "joint_empirical_gate": row["passes_joint_empirical_gate"],
            "calibration_gate": row["passes_calibration_gate"],
            "retention_gate": row["passes_retention_gate"],
            "new_nll_efficacy_gate": row["passes_nll_efficacy_gate"],
            "shifted_classwise_ece": row["pooled_shifted_classwise_ece"],
            "shifted_95_interval_coverage": row["pooled_shifted_coverage95"],
            "worst_cross_seed_mean_old_nll_increase": row["worst_cross_seed_mean_old_nll_increase"],
            "worst_single_seed_window_old_nll_increase": row["worst_single_seed_window_old_nll_increase"],
            "final_new_nll_difference": row["final_new_nll_difference"],
            "pointwise_or_every_seed_retention_certificate": False,
        }
    document = {
        "schema": "hepta.analytic-event.round4.acceptance.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": frozen["source_commit"],
        "freeze_sha256": digest(root / "FREEZE.json"),
        "registered_iteration_executed_and_independently_reviewed": True,
        "engineering_completion_is_not_universal_scientific_acceptance": True,
        "new_postconfirmation_scientific_gate": False,
        "independent_review_receipts": {
            name: {"run_path": path, "sha256": digest(root / path), "passed": True}
            for name, path in reviews.items()
        },
        "input_result_hashes": {
            path: digest(root / path) for path in (
                "calibration_confirmation/RESULTS.json", "RUNTIME_RESULTS.json", "MATH_REFERENCE.json")
        },
        "calibration_current_byte_binding": {
            "confirmed_file_count": len(actual_calibration_files),
            "binding_sha256": digest(root / "reviews/CALIBRATION_CONFIRM_REVIEW_BINDING.json"),
            "scope": calibration_binding["current_time_binding"],
            "original_review_receipt_preserved": True,
            "retroactive_original_review_provenance_claimed": False,
        },
        "calibration_profiles": profiles,
        "runtime_gates": runtime["acceptance"],
        "native_replay_scope": review["native_replay_scope"],
        "runtime_interruption_and_recovery": {
            "interrupted_attempts_receipt_sha256": digest(root / "RUNTIME_INTERRUPTION.json"),
            "recovery_completion_sha256": digest(root / "runtime_recovery/COMPLETED.json"),
            "failed_detached_launch_receipt_sha256": digest(root / "RUNTIME_DETACHED_LAUNCH_FAILURE.json"),
            "complete_registered_cohorts_only_enter_scientific_statistics": True,
            "interrupted_attempts_are_additional_work_not_new_independent_samples": True,
            "interrupted_total_native_calls": None,
            "interrupted_total_cpu_seconds": None,
            "interrupted_full_wall_seconds": None,
            "scope": "Exact interrupted bytes and observed lifetime bounds are preserved; completed retries use the same frozen cohorts. Unknown costs are not represented as zero.",
        },
        "runtime_primary_utility_contrasts": {
            key: runtime["utility_contrasts"][key] for key in ("event_vs_direct", "event_vs_float")
        },
        "identification": {
            "context_and_zero_context_are_different_information_tasks": True,
            "fitted_moment_context_joint_empirical_gate": calibration["arms"]["moment_context"]["passes_joint_empirical_gate"],
            "exact_shape_vs_fitted_moment": calibration["mechanism_comparisons"]["mixture_context_minus_moment_context"],
            "exact_shape_vs_same_weight_moment": calibration["mechanism_comparisons"]["mixture_context_minus_same_weight_moment"],
            "event_direct_equivalence_is_not_predictive_superiority": True,
            "calibration_parameter_q24_is_distinct_from_runtime_packet_native_release_q24": True,
            "runtime_forecasts_use_actual_native_outputs": True,
            "physical_source_effective_and_released_distributions_are_separate": True,
        },
        "six_deliverables": [
            {"order": 1, "delivered": "Versioned terminal conditional-law, information, time, threshold, reset and event contracts.",
             "boundary": "Communication increments, missing observations, neutral mass and terminal events are distinct; no newly trained first-passage/reset cell."},
            {"order": 2, "delivered": "Stable tails/log weights, mixtures, gradients, intervals, semigroup and independent dense/integral references.",
             "boundary": "GH64 continuation remains a measured numerical approximation; runtime FP64 complement transport has a documented restricted domain."},
            {"order": 3, "delivered": "Actual trained component/noise/prior/readout parameters, continuous/event/direct/probit/history/original sparse controls.",
             "boundary": "No new function class, hard-spike end-to-end training, or superiority inferred from equivalent controls."},
            {"order": 4, "delivered": "Registered hidden-state task with paid sensor acquisition, wait/repair/stop and final realized utility.",
             "boundary": "The environment is controlled synthetic data; primary runtime claims are paired noninferiority, with descriptive secondary utility comparisons."},
            {"order": 5, "delivered": "Actual Hepta text/PNG delivery and readback, native state evolution, action choice, final scoring and complete cohort native replay.",
             "boundary": "The existing binary is reused byte-exactly; no fresh Rust build. Interrupted partial/unreturned calls and qualification failure/recovery calls are separately reported and not exhaustively replayed."},
            {"order": 6, "delivered": "Versioned adapter state, positive categorical Q24 release, fresh-process recovery, corruption/failure qualification and separately reported costs/retention/calibration.",
             "boundary": "Original-information calibration still fails. No unlimited retention, general-purpose out-of-domain claim, isolated hardware speed/energy result, or production promotion."},
        ],
        "cost_scope": {
            "row_wall_excludes_subsequent_archive_work": True,
            "worker_and_wrapper_wall_include_archive_work": True,
            "row_cpu_excludes_native_child_cpu": True,
            "concurrent_wrapper_walls_are_not_session_elapsed_time": True,
            "adapter_serialized_write_totals_reconstructed_and_final_bytes_verified": True,
            "native_initialization_and_cumulative_filesystem_writes_fully_measured": False,
            "filesystem_write_amplification_bytes": None,
            "hardware_energy": None,
            "monetary_cost": None,
        },
        "production_promotion": False,
        "runtime_authority": {"confidence": 0, "decision": "abstain", "permissions": "DENY_ALL"},
        "remaining_research": [
            "Correct zero-context calibration under the unchanged information budget on a newly frozen cohort.",
            "Test first-passage, censoring, refractory and reset likelihoods in a separately registered cell if biological firing semantics are desired.",
            "Evaluate identified model benefits against matched strong controls and equally available public information.",
            "Measure isolated deployment latency, cumulative native I/O and hardware energy on an appropriate target.",
            "Test longer schedules and external domains without reusing confirmation for tuning.",
        ],
    }
    verify(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(document, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.run_dir.resolve(), args.output.resolve())
    print(json.dumps({"reviewed": True, "runtime_gates": report["runtime_gates"],
                      "calibration_joint_gates": {k: v["joint_empirical_gate"] for k, v in report["calibration_profiles"].items()}}))
