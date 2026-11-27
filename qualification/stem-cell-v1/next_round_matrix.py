"""Pre-registered next-round matrix for shared Stem/Cell experiments.

This module only builds and validates an execution plan. It never invents
model scores, loads weights, or authorizes promotion. Real runs must use the
existing local-snapshot runners and append their receipts to the plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

# V1 plans contain ambiguous NDU flags/budgets. Keep historical bytes; rebuild
# under V2 rather than silently reinterpret an already-run experiment.
SCHEMA = "hepta.neuron.next-round-matrix.v2"
ARMS = (
    "shared_421m_head_no_ndu",
    "replicated_421m_no_ndu",
    "small_stem_matched_head_no_ndu",
    "shared_421m_sparse_split_no_ndu",
    "shared_421m_sparse_split_ndu",
    "shared_421m_sparse_fixed16_no_ndu",
    "shared_421m_sparse_direct32_no_ndu",
    "shared_421m_sparse_direct32_64m_no_ndu",
    "shared_421m_sparse_split_64m_no_ndu",
)

# initial cells, final cells, final per-cell Head ceiling, routed cells, split.
# These are allocation ceilings, NOT measured trainable tensor counts or FLOPs.
ARM_PROFILES = (
    (16, 16, 2_000_000, 16, False),
    (16, 16, 2_000_000, 16, False),
    (16, 16, 2_000_000, 16, False),
    (16, 32, 1_000_000, 2, True),
    (16, 32, 1_000_000, 2, True),
    (16, 16, 2_000_000, 2, False),
    (32, 32, 1_000_000, 2, False),
    (32, 32, 2_000_000, 2, False),
    (16, 32, 2_000_000, 2, True),
)
# Tuple indices identify comparisons; arm order is part of the frozen protocol.
CONTRASTS = (
    ("weight_sharing", 1, 0, True),
    ("backbone", 0, 2, True),
    ("sparse_routing", 0, 5, True),
    ("cell_count_fixed_budget", 5, 6, True),
    ("adaptive_split", 6, 3, True),
    ("ndu", 3, 4, True),
    ("capacity", 6, 7, False),
    ("adaptive_split_64m", 7, 8, True),
)
WORK_POOLS = {
    "offline": ("train", "evaluation", "migration"),
    "online": ("search", "inference"),
}
MODALITY_PHASES = ("text", "image", "audio", "video")
REQUIRED_METRICS = (
    "retained_task",
    "independent_eval",
    "unsupported_claim_rate",
    "brier_or_ece",
    "active_flops",
    "p50_latency_ms",
    "p95_latency_ms",
    "p99_latency_ms",
    "peak_memory_bytes",
    "energy_joules",
    "new_cell_incremental_bytes",
)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_plan(*, reader_id: str, task_set_id: str, seed: int = 7347) -> dict:
    if not isinstance(reader_id, str) or not reader_id:
        raise ValueError("reader_id is required")
    if not isinstance(task_set_id, str) or not task_set_id:
        raise ValueError("task_set_id is required")
    if type(seed) is not int or seed <= 0:
        raise ValueError("seed must be a positive integer")
    arms = []
    for arm, profile in zip(ARMS, ARM_PROFILES, strict=True):
        initial, final, head_ceiling, top_k, split = profile
        ndu = arm == "shared_421m_sparse_split_ndu"
        replicated = arm.startswith("replicated")
        small = arm.startswith("small")
        arms.append({
            "arm_id": arm,
            "stem": "421m" if not small else "smaller_control",
            "cell_head_budget_params": head_ceiling,
            "total_head_budget_params": final * head_ceiling,
            "initial_logical_cells": initial,
            "active_cells_per_round_cap": top_k,
            "allocation_semantics": "final_capacity_ceiling_not_actual_count",
            "router_and_critic_params": "measure_separately_and_count_in_total",
            "growth_costs": "count_all_training_search_evaluation_and_migration",
            "compute_matching": "measured_phase_totals_not_equal_steps",
            "resident_stem_copies": 16 if replicated else 1,
            "logical_cells": final,
            "split": split,
            "ndu": ndu,
            "reader_id": reader_id,
            "task_set_id": task_set_id,
            "modalities": list(MODALITY_PHASES[:3]),
            "video_after_prior_phase": True,
        })
    plan = {
        "schema": SCHEMA,
        "seed": seed,
        "arms": arms,
        "fixed_controls": {
            "reader_id": reader_id,
            "task_set_id": task_set_id,
            "training_budget": "same_data_access_and_optimizer_with_measured_work_caps",
            "compute_protocol": "freeze_numeric_caps_and_tolerance_before_execution",
            "cost_phases": ["train", "search", "evaluation", "inference", "migration"],
            "flop_scope": "encoder_head_router_critic_verifier_and_failed_work",
            "parameter_scope": "unique_physical_tensors_and_lifecycle_peak",
            "matched_steps_imply_matched_compute": False,
            "work_pools": {name: list(phases) for name, phases in WORK_POOLS.items()},
            "latency_protocol": "warmup_excluded_then_fixed_batch_p50_p95_p99",
            "energy_protocol": "measured_counter_only_null_if_unavailable",
            "split_rule": "offline_candidate_only_then_replay",
        },
        "contrasts": [
            {"contrast_id": name, "baseline": ARMS[left], "candidate": ARMS[right],
             "match_total_head_budget": match,
             "requires_measured_compute_match": True,
             "matching_scope": "paired_tasks_and_frozen_offline_online_work_pools",
             "actual_match_status": "unobserved"}
            for name, left, right, match in CONTRASTS
        ],
        "required_metrics": list(REQUIRED_METRICS),
        "phase_order": ["text", "image", "audio", "video"],
        "promotion_gate": {
            "baseline": "shared_421m_head_no_ndu",
            "candidate": "shared_421m_sparse_split_ndu",
            "must_exceed": ["retained_task", "independent_eval"],
            "must_not_regress": ["unsupported_claim_rate", "brier_or_ece"],
            "cost_constraints": ["p95_latency_ms", "active_flops", "energy_joules", "new_cell_incremental_bytes"],
            "requires_all_metrics_observed": True,
            "production_authorized": False,
        },
        "evidence_status": {
            "real_421m_weights_loaded": False,
            "independent_outcomes_loaded": False,
            "energy_counter_attested": False,
            "multimodal_codecs_loaded": False,
            "promotion_permitted": False,
        },
    }
    plan["plan_id"] = _digest(plan)
    return plan


def validate_plan(plan: dict) -> None:
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError("V2 matrix required; audit/rebuild V1, never relabel old runs")
    try:
        controls = plan["fixed_controls"]
        expected = build_plan(reader_id=controls["reader_id"],
                              task_set_id=controls["task_set_id"], seed=plan["seed"])
        # Canonical JSON equality also distinguishes bool from int and rejects
        # unknown fields. Rehashing a malformed plan cannot legitimize it.
        if _digest(plan) != _digest(expected):
            raise ValueError("matrix semantics, allocation or content identity changed")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("incomplete or noncanonical matrix") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reader-id", required=True)
    parser.add_argument("--task-set-id", required=True)
    parser.add_argument("--seed", type=int, default=7347)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        raise FileExistsError("append-only plan already exists")
    plan = build_plan(reader_id=args.reader_id, task_set_id=args.task_set_id, seed=args.seed)
    validate_plan(plan)
    # Exclusive create closes the check/write race without overwriting history.
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"plan_id": plan["plan_id"], "arms": len(plan["arms"]), "promotion_permitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
