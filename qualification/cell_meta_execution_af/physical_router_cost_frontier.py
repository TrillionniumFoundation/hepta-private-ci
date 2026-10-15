#!/usr/bin/env python3
"""Read-only observed-work lower-bound accounting for paired five-arm Cell trials.

This reviewer performs the full independent original-case numeric replay before
counting work. Its counts are self-reported/structurally checked CPU operations,
not a hardware signature, FLOP total, joule measurement or matched NDU budget.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as audit
from qualification.cell_meta_execution_af import physical_router_paired_screen as paired

SCHEMA = "hepta.cell-meta-observed-work-frontier.v1"
EVAL = ("old_retention", "future_1", "future_2", "ood")
HARD_ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split")
NAMED = ("frozen_stage1_no_second_phase_learning", "unsplit_continued_update",
         "fixed_router", "learned_router", "adaptive_split")
# These are deliberately *unmeasured*, not zero and not inferred from Head rows.
UNMEASURED = ("actual_hardware_encoder_forwards_and_loads",
              "head_backward_and_optimizer_floating_point_ops",
              "router_gradient_and_sampling_floating_point_ops",
              "full_process_peak_rss_and_activations",
              "cpu_energy_or_gpu_energy_joules",
              "physical_cache_hits_and_source_rereads",
              "artifact_cas_and_cell_state_migration",
              "cns_final_use_wal_and_restart_cost",
              "independent_evaluation_search_and_failed_candidate_work")


class CostFrontierDenied(ValueError):
    """Source lineage, work observations or authority boundary is inconsistent."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise CostFrontierDenied(reason)


def count(value: Any, label: str) -> int:
    require(type(value) is int and 0 <= value <= (1 << 48),
            label + ": bounded nonnegative integer required")
    return value


def cpu(value: Any, label: str) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            label + ": finite self-reported CPU time required")
    return float(value)


def _per_seed(bundle: dict[str, Any]) -> dict[str, Any]:
    """Account only *already numerically verified* bundles; screen() owns admission."""
    panel, hard, frozen, five = (bundle[k] for k in ("panel", "hard", "frozen", "five"))
    source = panel["source"]
    steps = count(hard["steps_each_stage"], "registered optimizer step budget")
    n0 = len(panel["partitions"]["old_train"])
    n1 = len(panel["partitions"]["new_train"])
    eval_rows = sum(len(panel["partitions"][k]) for k in EVAL)
    n_all = n0 + n1
    base_stage1 = steps * n0
    primary_train = steps * (2 * n0 + n1)
    dim = source["dim"]
    require(type(dim) is int and 2 <= dim <= 64 and steps >= 2,
            "unsupported dimensionality or fitting schedule")
    require(type(hard["results"]) is list and len(hard["results"]) == len(HARD_ARMS),
            "complete hard-trained inventory required")
    require(type(five["arms"]) is list and
            tuple(a["arm"] for a in five["arms"]) == NAMED,
            "five-arm evidence must preserve the exact original inventory")
    require(five["seed"] == source["seed"] and
            five["panel_sha256"] == audit.digest(panel),
            "cost evidence does not bind exact source")
    require(five["complete_lifecycle_compute_matched"] is False and
            five["production_admission"] == "BLOCKED" and
            five["authority_posture"] == "DENY_ALL",
            "source report cannot grant resource parity or model authorization")
    entries: list[dict[str, Any]] = []
    frozen_meter = frozen["meters"]
    frozen_expected = {"reused_stage1_train_rows_reported": base_stage1,
                       "additional_stage2_train_head_rows": 0,
                       "additional_stage2_optimizer_updates": 0,
                       "additional_eval_head_rows": eval_rows,
                       "additional_eval_router_rows": 0,
                       "frozen_head_payload_bytes_fp32": (dim+1) * 4}
    for key, value in frozen_expected.items():
        require(count(frozen_meter[key], "frozen."+key) == value,
                "frozen work accounting mismatch: " + key)
    entries.append({
        "arm": NAMED[0], "split_proposed": False,
        "reused_stage1_primary_head_rows": base_stage1,
        "stage2_primary_train_head_rows": 0, "eval_primary_head_rows": eval_rows,
        "all_primary_head_rows_including_stage1": base_stage1+eval_rows,
        "additional_diagnostic_head_rows": 0,
        "additional_router_train_rows": 0, "additional_router_eval_rows": 0,
        "additional_router_diagnostic_rows": 0,
        "stage2_route_samples": 0, "stage2_head_optimizer_updates": 0,
        "stage2_router_optimizer_updates": 0,
        "head_weight_payload_bytes_fp32": (dim+1)*4,
        "reported_training_cpu_seconds": None,
        "reported_incremental_inference_cpu_seconds": cpu(
            frozen_meter["actual_inference_cpu_seconds"], "frozen inference"),
        "cpu_timings_do_not_have_identical_scope": True,
    })
    for index, expected_name in enumerate(HARD_ARMS):
        item = hard["results"][index]
        v = item["meters"]
        require(item["arm"] == expected_name, "hard expert identity drift")
        split = item["split_proposed"]
        require(type(split) is bool, "split requires exact boolean")
        train = sum(count(v[k], k) for k in ("train_head_0_rows", "train_head_1_rows"))
        ev = sum(count(v[k], k) for k in ("eval_head_0_rows", "eval_head_1_rows"))
        diagnostic = count(v["diagnostic_head_rows"], "diagnostic_head_rows")
        train_router = count(v["train_router_rows"], "train_router_rows")
        eval_router = count(v["eval_router_rows"], "eval_router_rows")
        diagnostic_router = count(v["diagnostic_router_rows"], "diagnostic_router_rows")
        sampled = count(v["sampled_routes"], "sampled_routes")
        n_updates = count(v["optimizer_steps"], "optimizer_steps")
        n_router_updates = count(v["learned_gate_optimizer_steps"], "gate updates")
        needs_sampling = split and expected_name in ("learned_router", "adaptive_split")
        expected_work = {
            "train": primary_train,
            "eval": eval_rows,
            # 2*(old+new) is the frozen Brier and parent baseline diagnostic.
            # A split additionally checks parent/child parity on old_train,
            # which forwards the original and new candidate once each.
            "diagnostic": 2*n_all + (2*n0 if split else 0),
            "train_router": steps*n_all if split else 0,
            "eval_router": eval_rows if split else 0,
            "diagnostic_router": n0 if split else 0,
            "sampled": steps*n_all if needs_sampling else 0,
            "updates": 2*steps,
            "gate_updates": steps if needs_sampling else 0,
        }
        observed = {"train": train, "eval": ev, "diagnostic": diagnostic,
                    "train_router": train_router, "eval_router": eval_router,
                    "diagnostic_router": diagnostic_router, "sampled": sampled,
                    "updates": n_updates, "gate_updates": n_router_updates}
        require(observed == expected_work,
                "actual Head/Router/diagnostic observations do not match branch-specific work")
        require(count(v["sample_exposures"], "sample exposures") == primary_train,
                "sample exposure accounting differs from real primary Head rows")
        parameters = 3*(dim+1)
        require(count(item["parameter_slots"], "parameter slots") == parameters and
                count(item["resident_weight_bytes_fp32"], "FP32 weight bytes") == 4*parameters,
                "shared Head/router FP32 parameter residency not accounted")
        require(five["arms"][index+1]["cost_observation"]["additional_stage2_training_head_rows"]
                == primary_train-base_stage1,
                "reported five-arm cost is inconsistent with actual stage2 rows")
        entries.append({
            "arm": NAMED[index+1], "split_proposed": split,
            "reused_stage1_primary_head_rows": base_stage1,
            "stage2_primary_train_head_rows": primary_train-base_stage1,
            "eval_primary_head_rows": ev,
            "all_primary_head_rows_including_stage1": train+ev,
            "additional_diagnostic_head_rows": diagnostic,
            "additional_router_train_rows": train_router,
            "additional_router_eval_rows": eval_router,
            "additional_router_diagnostic_rows": diagnostic_router,
            "stage2_route_samples": sampled,
            "stage2_head_optimizer_updates": n_updates-steps,
            "stage2_router_optimizer_updates": n_router_updates,
            "head_weight_payload_bytes_fp32": 4*parameters,
            # Actual self-reported CPU covers training/diagnostics, not scored
            # evaluation, model loading, materialization or kernel energy.
            "reported_training_cpu_seconds": cpu(v["train_cpu_seconds"], "train CPU"),
            "reported_incremental_inference_cpu_seconds": None,
            "cpu_timings_do_not_have_identical_scope": True,
        })
    require(tuple(entry["arm"] for entry in entries) == NAMED,
            "source arm ordering changed")
    require(len({entry["stage2_primary_train_head_rows"] for entry in entries[1:]}) == 1
            and len({entry["eval_primary_head_rows"] for entry in entries}) == 1,
            "recorded primary Head row exposures are not comparable")
    return {"seed": source["seed"], "source_kind": source["kind"],
            "source_row_count_not_independent_of_other_seeds": sum(
                len(x) for x in panel["partitions"].values()),
            "shared_old_train_rows": n0, "shared_new_train_rows": n1,
            "shared_reused_stage1_head_rows": base_stage1,
            "stage2_steps": steps, "all_scored_eval_rows": eval_rows,
            "exact_logical_feature_width": dim, "arms": entries}


def evaluate(bundles: dict[int, dict[str, Any]], paired_report: dict[str, Any]) -> dict[str, Any]:
    # Mandatory, non-optional independent model/route/outcome replay precedes
    # any comparison of training, evaluation or physical cost claims.
    actual_paired = paired.screen(bundles)
    # JSON object keys are strings on disk, while the source reviewer keeps
    # integer seed keys in memory. Compare their canonical JSON bytes instead.
    require(audit.canonical(actual_paired) == audit.canonical(paired_report),
            "saved original-source paired evidence differs from recomputed replay")
    sources = {seed: _per_seed(bundles[seed]) for seed in paired.SEEDS}
    require(len({source["source_row_count_not_independent_of_other_seeds"]
                 for source in sources.values()}) == 1,
            "inconsistent shared source inventories across training seeds")
    original_sources = sources[paired.SEEDS[0]]["source_row_count_not_independent_of_other_seeds"]
    # Exactly one source table may be shared by many Heads; physical re-encoding
    # and external-source provenance remain unverified, not set to 0 or 'passed'.
    return {"schema": SCHEMA,
            "source_paired_report_sha256": audit.digest(paired_report),
            "source_panel_sha256_per_seed": {
                str(seed): audit.digest(bundles[seed]["panel"]) for seed in paired.SEEDS},
            "unique_original_rows_not_multiplied_by_seeds": original_sources,
            "paired_training_seed_count": len(paired.SEEDS),
            "per_seed_observed_work": {str(k): v for k,v in sources.items()},
            "observed_primary_head_train_eval_equal_across_hard_arms": True,
            "frozen_no_change_has_unequal_post_stage1_budget": True,
            "additional_diagnostic_and_router_work_differs_between_arms": True,
            "full_lifecycle_cost_matched": False,
            "actual_encoder_hardware_forward_receipt_available": False,
            "all_costs_independently_attested": False,
            "unmeasured_resource_components": list(UNMEASURED),
            "cpu_timing_scope_is_comparable": False,
            "actual_future_outcomes_verified": False,
            "independent_ndu_selection_authorized": False,
            "statistical_or_resource_winner_certified": False,
            "production_admission": "BLOCKED", "authority_posture": "DENY_ALL"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundles = paired.read_bundles(args.bundle_dir)
        saved = audit.load(args.bundle_dir / "paired-original-source-screen.json")
        report = evaluate(bundles, saved)
        payload = audit.canonical(report)+b"\n"
        require(len(payload) <= 192*1024, "bounded nonauthorizing resource summary required")
        with args.out.open("xb") as f:
            f.write(payload)
        print(json.dumps({"path": str(args.out), "schema": SCHEMA,
                          "authority_posture": "DENY_ALL",
                          "resource_winner_established": False}, sort_keys=True))
        return 0
    except (CostFrontierDenied, paired.PairedScreenDenied, KeyError, IndexError,
            TypeError, ValueError, OSError, OverflowError, RecursionError) as exc:
        print("OBSERVED-WORK FRONTIER DENIED: "+str(exc),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
