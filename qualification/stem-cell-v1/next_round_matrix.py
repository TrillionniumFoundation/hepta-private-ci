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

SCHEMA = "hepta.neuron.next-round-matrix.v1"
ARMS = (
    "shared_421m_head_no_ndu",
    "replicated_421m_no_ndu",
    "small_stem_matched_head_no_ndu",
    "shared_421m_sparse_split_no_ndu",
    "shared_421m_sparse_split_ndu",
)
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
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_plan(*, reader_id: str, task_set_id: str, seed: int = 7347) -> dict:
    if not isinstance(reader_id, str) or not reader_id:
        raise ValueError("reader_id is required")
    if not isinstance(task_set_id, str) or not task_set_id:
        raise ValueError("task_set_id is required")
    if type(seed) is not int or seed <= 0:
        raise ValueError("seed must be a positive integer")
    arms = []
    for arm in ARMS:
        split = "sparse_split" in arm
        ndu = arm.endswith("_ndu")
        replicated = arm.startswith("replicated")
        small = arm.startswith("small")
        arms.append({
            "arm_id": arm,
            "stem": "421m" if not small else "smaller_control",
            "cell_head_budget_params": 2_000_000,
            "resident_stem_copies": 16 if replicated else 1,
            "logical_cells": 32 if split else 16,
            "split": split,
            "ndu": ndu,
            "reader_id": reader_id,
            "task_set_id": task_set_id,
            "modalities": list(MODALITY_PHASES[:3]),
            "video_after_prior_phase": True,
        })
    return {
        "schema": SCHEMA,
        "plan_id": _digest({"reader": reader_id, "tasks": task_set_id, "seed": seed}),
        "seed": seed,
        "arms": arms,
        "fixed_controls": {
            "reader_id": reader_id,
            "task_set_id": task_set_id,
            "training_budget": "identical_examples_steps_and_optimizer",
            "latency_protocol": "warmup_excluded_then_fixed_batch_p50_p95_p99",
            "energy_protocol": "measured_counter_only_null_if_unavailable",
            "split_rule": "offline_candidate_only_then_replay",
        },
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


def validate_plan(plan: dict) -> None:
    if plan.get("schema") != SCHEMA or len(plan.get("arms", [])) != len(ARMS):
        raise ValueError("invalid matrix schema or arm count")
    ids = tuple(arm.get("arm_id") for arm in plan["arms"])
    if ids != ARMS:
        raise ValueError("arms must remain in preregistered order")
    if tuple(plan.get("phase_order", ())) != MODALITY_PHASES:
        raise ValueError("video must be the final modality phase")
    if plan["promotion_gate"].get("production_authorized") is not False:
        raise ValueError("plan cannot authorize production")
    if plan["evidence_status"].get("promotion_permitted") is not False:
        raise ValueError("empty plan cannot permit promotion")
    if tuple(plan.get("required_metrics", ())) != REQUIRED_METRICS:
        raise ValueError("required metric set changed")


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
    destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan_id": plan["plan_id"], "arms": len(plan["arms"]), "promotion_permitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
