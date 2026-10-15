#!/usr/bin/env python3
"""Five-arm, source-bound *retrospective* Cell comparison, without promotion.

Replays original soft / posthoc Top-1 / hard-trained / truly-frozen source
through existing independent stdlib reviewers. Does not train, infer, fetch
models, authenticate observer provenance or grant NDU/production authority.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as baseline_audit
from qualification.cell_meta_execution_af import physical_router_frozen_review as frozen_audit
from qualification.cell_meta_execution_af import physical_router_hard_review as hard_audit
from qualification.cell_meta_execution_af import physical_router_top1_review as top1_audit

SCHEMA = "hepta.cell-meta-five-arm-retrospective.v1"
ARMS = ("frozen_stage1_no_second_phase_learning", "unsplit_continued_update",
        "fixed_router", "learned_router", "adaptive_split")
PARTS = ("old_retention", "future_1", "future_2", "ood")
SEEDS = (41, 47, 53)


class FiveArmDenied(ValueError):
    """Observed bundle is incomplete, inconsistent or makes an unsupported claim."""


def require(ok: bool, why: str) -> None:
    if not ok:
        raise FiveArmDenied(why)


def typed_counter(x: Any, label: str) -> int:
    require(type(x) is int and 0 <= x <= 1 << 48, label + ": bounded integer required")
    return x


def normalized_score(source: dict[str, Any], expected: int) -> dict[str, Any]:
    require(type(source) is dict and set(source) == {"count", "accuracy", "brier", "nll"},
            "incomplete score inventory")
    require(type(source["count"]) is int and source["count"] == expected,
            "wrong scored source-group count")
    for field in ("accuracy", "brier", "nll"):
        value = source[field]
        require(type(value) in (float, int) and math.isfinite(value),
                "invalid score " + field)
        require(0 <= value <= (1 if field in ("accuracy", "brier") else 100),
                "out-of-range score " + field)
    return dict(source)


def descriptive(panel: dict[str, Any], soft: dict[str, Any],
                posthoc: dict[str, Any], hard: dict[str, Any],
                frozen: dict[str, Any]) -> dict[str, Any]:
    # This numeric audit does not call the training/inference producers and it
    # rechecks predecessor tensor identity, predicted probabilities and labels.
    verified = frozen_audit.replay(panel, soft, posthoc, hard, frozen)
    require(verified["outcome"] == "FROZEN_NO_CHANGE_NUMERIC_REPLAY_NO_AUTHORITY",
            "unqualified frozen reviewer")
    require(hard["authority_posture"] == "DENY_ALL" and
            frozen["authority_posture"] == "DENY_ALL", "unauthorized artifact")
    source = panel["source"]
    require(source["seed"] in SEEDS and source["rule"] in ("stable", "conditional", "external"),
            "unregistered seed/source")
    require(source["kind"] == ("external_unverified" if source["rule"] == "external"
                                else "synthetic"), "misrepresented model source")
    require(type(hard["results"]) is list and len(hard["results"]) == 4 and
            tuple(r["arm"] for r in hard["results"]) ==
            ("no_change", "fixed_router", "learned_router", "adaptive_split"),
            "changed hard-train candidate inventory")

    stage1_rows = len(panel["partitions"]["old_train"]) * hard["steps_each_stage"]
    old = hard["results"][0]
    result = []
    for index, name in enumerate(ARMS):
        if index == 0:
            scores = frozen["retrospective_evaluation"]
            meters = frozen["meters"]
            stage2_head = typed_counter(
                meters["additional_stage2_train_head_rows"], "frozen stage2")
            stage2_updates = typed_counter(
                meters["additional_stage2_optimizer_updates"], "frozen updates")
            eval_head = typed_counter(meters["additional_eval_head_rows"], "frozen evaluation")
            train_router = typed_counter(meters["additional_eval_router_rows"], "frozen router")
            diagnostics = 0  # upstream stage-1 diagnostics are recorded by the original trial
            split = False
        else:
            arm = hard["results"][index - 1]
            meters = arm["meters"]
            scores = arm["retrospective_evaluation"]
            total_train = sum(typed_counter(meters[key], key) for key in
                              ("train_head_0_rows", "train_head_1_rows"))
            require(total_train >= stage1_rows, "less training work than common stage1")
            stage2_head = total_train - stage1_rows
            steps = typed_counter(meters["optimizer_steps"], "optimizer_steps")
            require(steps >= hard["steps_each_stage"], "missing common stage1 optimizer")
            stage2_updates = steps - hard["steps_each_stage"]
            eval_head = sum(typed_counter(meters[key], key) for key in
                            ("eval_head_0_rows", "eval_head_1_rows"))
            train_router = typed_counter(meters["train_router_rows"], "train_router_rows")
            diagnostics = typed_counter(meters["diagnostic_head_rows"], "diagnostic_head_rows")
            split = arm["split_proposed"]
            require(type(split) is bool, "non-boolean structural candidate")
        if index == 0:
            require(stage2_head == stage2_updates == train_router == 0,
                    "frozen arm has stage2 update or router work")
        if index == 1:
            require(not split and stage2_head > 0 and stage2_updates > 0,
                    "continued unsplit learning is not the original no-change arm")
        score_set = {part: normalized_score(scores[part], len(panel["partitions"][part]))
                     for part in PARTS}
        result.append({
            "arm": name,
            "split_proposed": split,
            "retrospective_scores": score_set,
            "brier_delta_vs_frozen": {
                part: round(score_set[part]["brier"] -
                            frozen["retrospective_evaluation"][part]["brier"], 7)
                for part in PARTS
            },
            "brier_delta_vs_unsplit_continued": {
                part: round(score_set[part]["brier"] -
                            old["retrospective_evaluation"][part]["brier"], 7)
                for part in PARTS
            },
            "cost_observation": {
                "common_stage1_training_head_rows_reused": stage1_rows,
                "additional_stage2_training_head_rows": stage2_head,
                "additional_stage2_optimizer_updates": stage2_updates,
                "evaluated_head_rows": eval_head,
                "train_router_rows": train_router,
                "diagnostic_head_rows_in_existing_arm": diagnostics,
            },
        })
    require(tuple(r["arm"] for r in result) == ARMS, "comparison arm mismatch")
    return {
        "schema": SCHEMA,
        "panel_sha256": baseline_audit.digest(panel),
        "hard_train_sha256": baseline_audit.digest(hard),
        "frozen_sha256": baseline_audit.digest(frozen),
        "source_kind": source["kind"],
        "source_rule": source["rule"],
        "seed": source["seed"],
        "shared_stem_sha256": source["stem_sha256"],
        "retrospective_not_prospective": True,
        "same_source_calibration_not_ood": True,
        "single_common_frozen_stage1_parent": True,
        "research_only_no_independent_external_outcomes": True,
        "training_budget_unequal_across_five_arms": True,
        "complete_lifecycle_compute_matched": False,
        "statistical_winner_certified": False,
        "ndu_selection_authorized": False,
        "original_worker_model_origin_signed": False,
        "physical_cell_split_permitted": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
        "arms": result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("panel", "soft_report", "posthoc_report", "hard_report", "frozen_report", "out"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        panel, soft, posthoc, hard, frozen = [baseline_audit.load(path) for path in
                                              (args.panel, args.soft_report, args.posthoc_report,
                                               args.hard_report, args.frozen_report)]
        report = descriptive(panel, soft, posthoc, hard, frozen)
        payload = baseline_audit.canonical(report) + b"\n"
        require(len(payload) <= 128 * 1024, "five-arm review exceeds bounded output")
        # Existing numeric reviewer is an analysis-only producer, never a model
        # artifact writer. Create only, never rewrite a predecessor receipt.
        with args.out.open("xb") as file:
            file.write(payload)
        print(json.dumps({"five_arm_report": str(args.out), "no_authority": True,
                          "complete_lifecycle_compute_matched": False}, sort_keys=True))
        return 0
    except (FiveArmDenied, frozen_audit.FrozenReviewDenied, hard_audit.HardReplayDenied,
            baseline_audit.AuditError, top1_audit.Top1AuditError,
            OSError, KeyError, IndexError, ValueError, TypeError, OverflowError,
            RecursionError) as exc:
        print("FIVE-ARM RETROSPECTIVE REVIEW BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
