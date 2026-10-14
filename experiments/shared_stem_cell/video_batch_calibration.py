"""Schedule-matched calibration for the frozen video NDU Reader.

A scalar/FIFO continuation price is not a valid microbatch calibration price:
batched depth-synchronous reads change when a SHA-cached frame is visible.
Replay the EXACT physical grouping on pre-heldout calibration probabilities,
without asking for frames, later labels, or any new trainable parameters.
This is a research selector, NOT an IID, risk, or production guarantee.
"""
from __future__ import annotations

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import video_anytime as a
from experiments.shared_stem_cell import video_temporal as t
from experiments.shared_stem_cell import video_value as v

MAX_GROUP = 4
FAMILIES = ("confidence", "value", "cache_value")


def verify(exits, frame_ids, critic, *, batch_size=MAX_GROUP):
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_GROUP:
        raise e.InputError("fixed bounded video microbatch size required")
    if not isinstance(exits, dict) or set(exits) != set(a.DEPTHS):
        raise e.InputError("complete precomputed calibration Reader exits required")
    n = len(exits[2])
    if not isinstance(frame_ids, list) or len(frame_ids) != n or not 1 <= n <= 256:
        raise e.InputError("complete calibration source identities required")
    for d in a.DEPTHS:
        t.score(exits[d], torch.zeros(n, dtype=torch.long))
    for row in frame_ids:
        v.next_pair_marginal(set(), row, 2)
    for d in a.DEPTHS[:-1]:
        v.estimate(exits[d], d, critic)
    return n


def replay(exits, frame_ids, critic, policy, *, batch_size=MAX_GROUP):
    """Replay actual group-depth order; update cache BEFORE choosing next depth.

    Input contains *all* depth exit probabilities only because it is calibration.
    Policy at each depth uses only the corresponding already-observed exit.
    """
    n = verify(exits, frame_ids, critic, batch_size=batch_size)
    if not isinstance(policy, dict) or policy.get("kind") not in ("fixed", *FAMILIES):
        raise e.InputError("registered microbatch calibration policy required")
    kind = policy["kind"]
    if kind == "fixed":
        if policy.get("depth") not in a.DEPTHS:
            raise e.InputError("invalid fixed depth")
    elif kind == "confidence":
        if type(policy.get("threshold")) is not float or policy["threshold"] not in a.THRESHOLDS:
            raise e.InputError("invalid confidence grid threshold")
    elif type(policy.get("price")) is not float or policy["price"] not in v.COSTS:
        raise e.InputError("invalid critic price grid")
    known, calls, hits, requested, picks, records = set(), 0, 0, 0, [None] * n, []
    for start in range(0, n, batch_size):
        active = list(range(start, min(start + batch_size, n)))
        for d in a.DEPTHS:
            if not active:
                break
            needed = [f for i in active for f in frame_ids[i][d-2:d]]
            fresh = set(needed) - known
            calls += bool(fresh)
            hits += sum(k in known for k in needed)
            requested += len(needed)
            known.update(fresh)
            next_active = []
            for i in active:
                p = exits[d][i:i+1]
                expected = (float(v.estimate(p, d, critic)[0])
                            if d < 8 and kind in ("value", "cache_value") else None)
                marginal = (v.next_pair_marginal(known, frame_ids[i], d)
                            if d < 8 and kind == "cache_value" else None)
                stop = (d == 8 or kind == "fixed" and d >= policy["depth"]
                        or kind == "confidence" and float(p.max()) >= policy["threshold"]
                        or kind == "value" and expected <= policy["price"]
                        or kind == "cache_value" and expected <= v.cache_price(policy["price"], marginal))
                if stop:
                    picks[i] = (d, int(p.argmax()))
                else:
                    next_active.append(i)
            records.append({"batch": start//batch_size, "depth": d, "case_indices": active,
                            "request_rows": len(needed), "physical_video_calls": int(bool(fresh))})
            active = next_active
    if any(p is None for p in picks):
        raise e.InputError("incomplete schedule-matched route")
    return {"picks": picks, "physical_video_calls": int(calls), "unique_frames": len(known),
            "cache_hits": hits, "requested_frame_rows": requested, "events": records,
            "schedule": "fifo_microbatch_depth_synchronous", "batch_size": batch_size}


def select(exits, labels, frame_ids, critic, *, batch_size=MAX_GROUP):
    """Choose *microbatch* prices from calibration only, before heldout access.

    A candidate must meet the strongest FIXED-DEPTH calibration correct count.
    As true physical forwards dominate this experiment, compare them first;
    then count unique encoded frames, requested rows, correctness, grid order.
    """
    n = verify(exits, frame_ids, critic, batch_size=batch_size)
    if (not isinstance(labels, torch.Tensor) or labels.dtype != torch.long
            or labels.device.type != "cpu" or labels.shape != (n,)
            or bool(((labels < 0) | (labels > 1)).any())):
        raise e.InputError("complete calibration-only binary targets required")
    truth = labels.tolist()

    def profile(policy):
        simulated = replay(exits, frame_ids, critic, policy, batch_size=batch_size)
        predicted = simulated.pop("picks")
        simulated.pop("events")
        return {**simulated, "correct": sum(pred == y for (_depth, pred), y in zip(predicted, truth)),
                "cases": len(truth), "mean_depth": sum(d for d, _ in predicted)/len(truth)}

    def costkey(row, index):
        return (row["physical_video_calls"], row["unique_frames"],
                row["requested_frame_rows"], -row["correct"], index)

    fixed = {str(d): profile({"kind": "fixed", "depth": d}) for d in a.DEPTHS}
    floor = max(p["correct"] for p in fixed.values())
    best = min(a.DEPTHS, key=lambda d: (-fixed[str(d)]["correct"],
             *costkey(fixed[str(d)], d)[:3], d))
    policies, profiles, grids = {}, {}, {}
    for family, settings in (("confidence", a.THRESHOLDS), ("value", v.COSTS),
                             ("cache_value", v.COSTS)):
        field = "threshold" if family == "confidence" else "price"
        rows = []
        for option in settings:
            configured = {"kind": family, field: float(option)}
            rows.append({"setting": float(option), **profile(configured)})
        eligible = [i for i, row in enumerate(rows) if row["correct"] >= floor]
        if eligible:
            chosen = min(eligible, key=lambda i: costkey(rows[i], i))
            policies[family] = {"kind": family, field: float(settings[chosen])}
            profiles[family] = rows[chosen]
        else:
            policies[family] = {"kind": "fixed", "depth": best,
                "fallback_reason": "did_not_reach_best_fixed_microbatch_calibration_correct_count"}
            profiles[family] = fixed[str(best)]
        grids[family] = rows
    # Reporting only. On a cost/accuracy tie the simpler fixed-depth baseline wins.
    arms = {**{f"fixed_{d}": fixed[str(d)] for d in a.DEPTHS}, **profiles}
    best_arm = min(arms, key=lambda arm: (
        *costkey(arms[arm], 0)[:-1], 0 if arm.startswith("fixed_") else 1,
        (*[f"fixed_{d}" for d in a.DEPTHS], *FAMILIES).index(arm)))
    return {"schema": "hepta.video-batch-calibration.v1", "batch_size": batch_size,
        "research_best_arm": best_arm, "research_best_policy": (
            {"kind": "fixed", "depth": int(best_arm.split("_")[1])}
            if best_arm.startswith("fixed_") else policies[best_arm]),
        "schedule": "fifo_microbatch_depth_synchronous",
        "best_fixed_depth": best, "best_fixed_correct": floor,
        "fixed_profiles": fixed, "grids": grids, "policies": policies,
        "family_profiles": profiles, "selection_uses_holdout_labels": False,
        "critic_retrained": False, "reader_retrained": False,
        "same_calibration_cohort_as_scalar_choice": True,
        "population_nonregression_certified": False, "production_accepted": False}
