#!/usr/bin/env python3
"""Independent stdlib FP32 replay of *hard-trained* sparse Cell evidence.

No import of training/Top1 producing modules, no Torch, no provider/worker.
Checks source, candidate-v-control binding, pre-split loss and threshold,
parent cloning, packed actual route counts, frozen Head logits, and scoring.
An adversary can still fabricate internally consistent training telemetry;
this audit grants NO source, host, outcome, model-use or production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as base
from qualification.cell_meta_execution_af import physical_router_top1_review as top1

SCHEMA = "hepta.cell-meta-hard-trained-top1.v1"
PARTS = ("old_retention", "future_1", "future_2", "ood")
ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split")
FLAGS: dict[str, Any] = {
    "shared_precomputed_features": True,
    "torch_cpu_fp32_training_self_reported": True,
    "matched_primary_train_eval_head_rows": True,
    "matched_all_head_forward_rows": False,
    "total_compute_matched": False,
    "prospective_future_windows_verified": False,
    "true_ood_verified": False,
    "independent_model_origin_verified": False,
    "external_training_execution_attested": False,
    "ndu_selection_authorized": False,
    "physical_cell_split_permitted": False,
    "model_promotion_permitted": False,
    "production_admission": "BLOCKED",
    "authority_posture": "DENY_ALL",
}


class HardReplayDenied(ValueError):
    """Candidate's weights, training controls or numeric evidence do not replay."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise HardReplayDenied(reason)


def exact_float(value: Any, name: str, *, min_val: float = -math.inf) -> float:
    require(type(value) in (float, int) and math.isfinite(value) and value >= min_val,
            f"{name}: finite valid number required")
    return float(value)


def integer(value: Any, name: str, *, max_val: int = 1 << 48) -> int:
    require(type(value) is int and 0 <= value <= max_val, f"{name}: valid integer required")
    return value


def decode(obj: Any, shape: list[int]) -> list[float]:
    require(type(obj) is dict and set(obj) == {"shape", "data_le_hex"} and
            obj["shape"] == shape, "mismatched frozen tensor shape")
    hx = obj["data_le_hex"]
    count = math.prod(shape)
    require(type(hx) is str and len(hx) == 8 * count and
            all(c in "0123456789abcdef" for c in hx), "incomplete or corrupt float32 bytes")
    values = list(struct.unpack(f"<{count}f", bytes.fromhex(hx)))
    require(all(math.isfinite(x) for x in values), "nonfinite FP32 tensor")
    return values


def bits(hex_string: Any, size: int) -> list[int]:
    length = (size + 7) // 8
    require(type(hex_string) is str and len(hex_string) == length * 2 and
            all(ch in "0123456789abcdef" for ch in hex_string), "route bitset shape")
    raw = bytes.fromhex(hex_string)
    selected = [(raw[i//8] >> (i%8)) & 1 for i in range(size)]
    if size % 8:
        require((raw[-1] >> (size % 8)) == 0, "unused routing bits must be zero")
    return selected


def validate_source_shape(panel: Any) -> None:
    """Independently validate bounded panel structure; never attest its truth."""
    expected_parts = ("old_train", "new_train", *PARTS)
    require(type(panel) is dict and set(panel) == {"schema", "source", "partitions"} and
            panel["schema"] == "hepta.cell-meta-router-panel.v1", "unknown research panel")
    meta = panel["source"]
    require(type(meta) is dict and set(meta) == {
        "kind", "stem_sha256", "scope", "dim", "router_feature_index", "seed", "rule"},
        "unknown source-manifest fields")
    dim = meta["dim"]
    require(type(dim) is int and 2 <= dim <= 64 and
            type(meta["router_feature_index"]) is int and
            0 <= meta["router_feature_index"] < dim and
            type(meta["seed"]) is int and meta["seed"] in (41, 47, 53),
            "unsupported feature width / route coordinate / experimental seed")
    require(type(meta["stem_sha256"]) is str and len(meta["stem_sha256"]) == 64 and
            all(c in "0123456789abcdef" for c in meta["stem_sha256"]) and
            any(c != "0" for c in meta["stem_sha256"]), "incomplete Stem identity")
    require(type(meta["scope"]) is str and 1 <= len(meta["scope"]) <= 96 and
            meta["scope"].strip() == meta["scope"] and
            type(meta["kind"]) is str and meta["kind"] in ("synthetic", "external_unverified") and
            type(meta["rule"]) is str and meta["rule"] in ("stable", "conditional", "external") and
            (meta["kind"] == "synthetic") == (meta["rule"] != "external"),
            "unregistered source kind / claim")
    groups, ids = set(), set()
    parts = panel["partitions"]
    require(type(parts) is dict and set(parts) == set(expected_parts),
            "incomplete named partitions")
    total = 0
    bounds = {}
    for part in expected_parts:
        rows = parts[part]
        require(type(rows) is list and len(rows) >= (32 if part in ("old_train", "new_train") else 16),
                "undersized partition")
        total += len(rows)
        require(total <= 8192, "unbounded research panel")
        steps = []
        for row in rows:
            require(type(row) is dict and set(row) == {"id", "source_group", "step",
                    "features", "label"}, "wrong row source fields")
            ident, group = row["id"], row["source_group"]
            require(type(ident) is str and 1 <= len(ident) <= 100 and ident not in ids and
                    type(group) is str and 1 <= len(group) <= 100 and group not in groups,
                    "duplicate / invalid row source family")
            ids.add(ident)
            groups.add(group)
            require(type(row["step"]) is int and row["step"] >= 0 and
                    type(row["label"]) is int and row["label"] in (0, 1),
                    "invalid source step or label")
            vec = row["features"]
            require(type(vec) is list and len(vec) == dim and
                    all(type(v) in (float, int) and math.isfinite(v) and -32 <= v <= 32
                        for v in vec), "nonfinite/unbounded source embedding")
            steps.append(row["step"])
        bounds[part] = (min(steps), max(steps))
    require(all(bounds[expected_parts[i]][1] < bounds[expected_parts[i+1]][0]
                for i in range(len(expected_parts)-1)),
            "retrospective order declaration changed")


def old_stage_brier(records: list[dict[str, Any]], weights: list[float]) -> float:
    width = len(weights) - 1
    return sum((base.sigmoid(sum(x * v for x, v in zip(row["features"]+[1.0],
                                                     weights, strict=True))) - row["label"])**2
               for row in records) / len(records)


def recheck_metrics(records: list[dict[str, Any]], predictions: list[dict[str, Any]],
                    part: str, heads: list[float], gate: list[float],
                    arm: str, active: bool, feature_idx: int, dim: int) -> tuple[dict, list[int]]:
    require(type(predictions) is list and len(predictions) == len(records),
            f"{part}: missing source/case predictions")
    ps = []
    selects = []
    for source, entry in zip(records, predictions, strict=True):
        require(type(entry) is dict and set(entry) == {
            "id", "selected_head", "probability"} and entry["id"] == source["id"],
            "hard-trained inference source identity")
        x = source["features"] + [1.0]
        if not active:
            chosen = 0
        else:
            chosen = int(sum(a * b for a, b in zip(x, gate, strict=True)) >= 0.0)
        require(type(entry["selected_head"]) is int and
                entry["selected_head"] == chosen, "wrong hardened Top-1 selected Head")
        index = chosen * (dim + 1)
        p = base.sigmoid(sum(x[j] * heads[index+j] for j in range(dim+1)))
        p = min(1-base.EPS, max(base.EPS, p))
        observed = entry["probability"]
        require(type(observed) is float and math.isfinite(observed) and
                base.EPS <= observed <= 1-base.EPS and abs(observed-p) < 3e-6,
                "Top-1 logit does not replay from learned bytes")
        ps.append(observed)
        selects.append(chosen)
    ys = [row["label"] for row in records]
    n = len(records)
    calculated = {
        "count": n,
        "accuracy": round(sum(int((p>=.5) == bool(y)) for p, y in zip(ps, ys, strict=True))/n, 7),
        "brier": round(sum((p-y)**2 for p, y in zip(ps, ys, strict=True))/n, 7),
        "nll": round(-sum(y * math.log(p) + (1-y) * math.log1p(-p)
                          for p, y in zip(ps, ys, strict=True))/n, 7),
    }
    return calculated, selects


def replay(panel: dict[str, Any], soft: dict[str, Any],
           posthoc: dict[str, Any], trained: dict[str, Any]) -> dict[str, Any]:
    validate_source_shape(panel)
    base.validate(panel, soft)
    top1.replay(panel, soft, posthoc)
    require(type(trained) is dict and set(trained) == {
        "schema", "source_panel_sha256", "soft_predecessor_sha256",
        "posthoc_predecessor_sha256", "method", "steps_each_stage",
        "learning_rate", "reinforce_scale", "entropy_scale", "router_sampling_seed_xor",
        *FLAGS.keys(), "results",
    }, "hard-trained report has missing or unknown fields")
    require(trained["schema"] == SCHEMA and
            trained["source_panel_sha256"] == base.digest(panel) and
            trained["soft_predecessor_sha256"] == base.digest(soft) and
            trained["posthoc_predecessor_sha256"] == base.digest(posthoc) and
            trained["method"] == "genuinely-sparse-training-reinforce-top1-v1",
            "predecessor or method changed")
    for k, value in FLAGS.items():
        require(type(trained[k]) is type(value) and trained[k] == value,
                f"{k}: elevated research authority or changed truth boundary")
    steps = trained["steps_each_stage"]
    require(type(steps) is int and 2 <= steps <= 100 and
            steps == soft["training_steps_each_stage"], "training exposure controls drift")
    for key, value in (("learning_rate", .35), ("reinforce_scale", .4),
                       ("entropy_scale", .002), ("router_sampling_seed_xor", 0x45CC)):
        require(type(trained[key]) is type(value) and trained[key] == value,
                f"fixed {key} tuning cannot change after observing results")
    require(panel["source"]["seed"] in (41,47,53), "unregistered training seed")
    arms = trained["results"]
    require(type(arms) is list and len(arms) == len(ARMS) and
            [x.get("arm") for x in arms if type(x) is dict] == list(ARMS),
            "missing or reordered hard-trained controls")
    source = panel["partitions"]
    dim = panel["source"]["dim"]
    coordinate = panel["source"]["router_feature_index"]
    n_old, n_new = len(source["old_train"]), len(source["new_train"])
    n_all = n_old+n_new
    n_eval = sum(len(source[p]) for p in PARTS)
    paired = []
    for candidate, post in zip(arms, posthoc["results"], strict=True):
        require(type(candidate) is dict and set(candidate) == {
            "arm", "split_proposed", "split_threshold", "train_only_old_brier",
            "train_only_new_brier", "train_only_excess_brier", "stage1_parent_fp32",
            "stage1_child_fp32", "stage1_gate_fp32", "weights_sha256", "weights_fp32",
            "prediction_sha256", "predictions", "stage2_selected_head_bitsets_le",
            "parameter_slots", "resident_weight_bytes_fp32", "meters",
            "retrospective_evaluation",
        }, "hard-trained arm inventory mismatch")
        arm = candidate["arm"]
        require(arm == post["arm"] and type(candidate["split_proposed"]) is bool,
                "hard-trained arm or Boolean split identity changed")
        active = candidate["split_proposed"]
        parent = decode(candidate["stage1_parent_fp32"], [dim+1])
        child = decode(candidate["stage1_child_fp32"], [dim+1])
        initial_gate = decode(candidate["stage1_gate_fp32"], [dim+1])
        old_brier = old_stage_brier(source["old_train"], parent)
        new_brier = old_stage_brier(source["new_train"], parent)
        for k, val in (("train_only_old_brier", old_brier),
                       ("train_only_new_brier", new_brier),
                       ("train_only_excess_brier", new_brier - old_brier)):
            require(abs(exact_float(candidate[k], k)-val) <= 1e-6,
                    "independent stage1 Brier/trigger disagrees with source and FP32 weights")
        require(type(candidate["split_threshold"]) is float and
                candidate["split_threshold"] == .08, "unregistered split threshold")
        should_split = arm != "no_change" and (
            arm != "adaptive_split" or new_brier - old_brier > .08)
        require(active == should_split, "selection changed after seeing heldout results")
        require(child == (parent if active else [0.0]*(dim+1)),
                "forked child must copy parent at split (or remain dormant)")
        expected_gate = [0.0] * (dim+1)
        if active:
            expected_gate[coordinate] = 1.0
        require(initial_gate == expected_gate, "non-frozen initial Router profile")
        slots = 3*(dim+1)
        require(type(candidate["parameter_slots"]) is int and candidate["parameter_slots"] == slots and
                type(candidate["resident_weight_bytes_fp32"]) is int and
                candidate["resident_weight_bytes_fp32"] == 4*slots,
                "unmatched model capacity")
        heads, gate = base.decode_fp32_weights(candidate, dim)
        if not active or arm == "fixed_router":
            require(gate == expected_gate, "inactive or fixed Router weights mutated")
        predicted = candidate["predictions"]
        require(type(predicted) is dict and set(predicted) == set(PARTS) and
                base.digest(predicted) == candidate["prediction_sha256"],
                "missing/altered prelabel prediction seal")
        retrospect = candidate["retrospective_evaluation"]
        require(type(retrospect) is dict and set(retrospect) == set(PARTS),
                "missing retrospective scoring")
        eval_counts = [0, 0]
        eval_batches = 0
        deltas = {}
        for part in PARTS:
            score, selected = recheck_metrics(source[part], predicted[part], part,
                                              heads, gate, arm, active, coordinate, dim)
            row = retrospect[part]
            require(type(row) is dict and set(row) == set(score) and
                    type(row["count"]) is int and row["count"] == score["count"] and
                    all(abs(exact_float(row[k], k)-score[k]) <= 1e-7
                        for k in ("accuracy", "brier", "nll")),
                    "stored retrospective metric cannot be recomputed")
            eval_counts[0] += selected.count(0)
            eval_counts[1] += selected.count(1)
            eval_batches += int(0 in selected) + int(1 in selected)
            deltas[part] = round(score["brier"] - post["retrospective_evaluation"][part]["brier"], 7)
        traced = candidate["stage2_selected_head_bitsets_le"]
        require(type(traced) is list and len(traced) == steps,
                "all training route traces must be retained (also for failed splits)")
        stages = [bits(x, n_all) for x in traced]
        if not active:
            require(all(all(v == 0 for v in selected) for selected in stages),
                    "unsplit control executed an extra expert")
        if active and arm == "fixed_router":
            expected = [int(r["features"][coordinate] >= 0.0)
                        for p in ("old_train", "new_train") for r in source[p]]
            require(all(selected == expected for selected in stages),
                    "fixed Top-1 Router secretly changed training routes")
        count1 = sum(sum(selected) for selected in stages)
        count0 = steps*n_all-count1
        batch_count = steps + sum(int(0 in selected) + int(1 in selected) for selected in stages)
        observed = candidate["meters"]
        require(type(observed) is dict and set(observed) == {
            "train_head_0_rows", "train_head_1_rows", "eval_head_0_rows",
            "eval_head_1_rows", "train_router_rows", "eval_router_rows",
            "sampled_routes", "train_head_batches", "eval_head_batches",
            "optimizer_steps", "learned_gate_optimizer_steps", "sample_exposures",
            "diagnostic_head_rows", "diagnostic_router_rows", "train_cpu_seconds",
        }, "incomplete training/serving resource ledger")
        budget = {
            "train_head_0_rows": steps*n_old+count0,
            "train_head_1_rows": count1,
            "eval_head_0_rows": eval_counts[0],
            "eval_head_1_rows": eval_counts[1],
            "train_router_rows": steps*n_all if active else 0,
            "eval_router_rows": n_eval if active else 0,
            "sampled_routes": steps*n_all if active and arm in ("learned_router", "adaptive_split") else 0,
            "train_head_batches": batch_count,
            "eval_head_batches": eval_batches,
            "optimizer_steps": 2*steps,
            "learned_gate_optimizer_steps": steps if active and arm in ("learned_router", "adaptive_split") else 0,
            "sample_exposures": steps*(2*n_old+n_new),
            "diagnostic_head_rows": 2*n_all + (2*n_old if active else 0),
            "diagnostic_router_rows": n_old if active else 0,
        }
        for k, val in budget.items():
            require(integer(observed[k], k) == val, f"{k}: claimed hard-Head/route work changed")
        exact_float(observed["train_cpu_seconds"], "train_cpu_seconds", min_val=0)
        require(budget["train_head_0_rows"] + budget["train_head_1_rows"] ==
                steps*(2*n_old+n_new) and
                budget["eval_head_0_rows"] + budget["eval_head_1_rows"] == n_eval,
                "sparse training must execute exactly ONE Head per sample")
        paired.append({"arm": arm, "split_proposed": active,
                       "train_head_rows": steps*(2*n_old+n_new),
                       "eval_head_rows": n_eval,
                       "router_train_rows": budget["train_router_rows"],
                       "diagnostic_head_rows": budget["diagnostic_head_rows"],
                       "posthoc_top1_vs_hard_trained_brier_delta": deltas})
    return {
        "outcome": "HARD_TRAINED_NUMERIC_REPLAY_NO_AUTHORITY",
        "all_arms_source_and_fp32_verified": True,
        "matched_primary_train_eval_head_rows": True,
        "matched_all_head_forward_rows": False,
        "matched_total_compute": False,
        "actual_worker_physical_execution_independently_attested": False,
        "independent_outcomes_or_future_gain_established": False,
        "production_selection_authorized": False,
        "authority_posture": "DENY_ALL",
        "comparisons": paired,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--soft-report", type=Path, required=True)
    parser.add_argument("--posthoc-report", type=Path, required=True)
    parser.add_argument("--hard-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        answer = replay(base.load(args.panel), base.load(args.soft_report),
                        base.load(args.posthoc_report), base.load(args.hard_report))
        print(json.dumps(answer, sort_keys=True))
        return 0
    except (HardReplayDenied, base.AuditError, top1.Top1AuditError,
            KeyError, IndexError, OSError, TypeError, ValueError,
            OverflowError, RecursionError) as exc:
        print(f"HARD TRAINING REPLAY BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
