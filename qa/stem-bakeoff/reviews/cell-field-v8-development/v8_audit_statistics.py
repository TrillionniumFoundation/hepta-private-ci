"""Independent V8 512-source pairing, completion, parity and development selection."""

from collections import Counter
from itertools import product

import numpy as np

from v8_audit_records import require


POLICIES = ("myopic_h1", "loss2_h8", "future_field_h8", "full_h8")
CANDIDATE, BASELINES = "future_field_h8", ("myopic_h1", "loss2_h8")


def ready(case):
    header = case["header"]
    return (case["available"] and header["status"] == "completed" and header["completed_steps"] == 32
        and not header["error"] and header["audit_passed"] is True and not case["actual_errors"]
        and type(header["cpu_ns"]) is int and header["cpu_ns"] > 0
        and all(np.asarray(case[key]).shape == (512,) and np.isfinite(case[key]).all()
            for key in ("future_losses", "old_differences")))


def parity_pair(field, full, fit, index, tolerance=1e-9):
    row = {"fit_id": fit, "configuration_index": index}
    if not field["available"] or not full["available"]:
        return {**row, "passed": False, "reason": "missing field or Full output"}
    if field["actions"].shape != full["actions"].shape or len(field["state_vectors"]) != len(full["state_vectors"]):
        return {**row, "passed": False, "reason": "different committed trace lengths", "absolute_tolerance": tolerance}
    action_error = float(np.max(np.abs(field["actions"]-full["actions"]))) if field["actions"].size else 0.
    state_error = float(np.max(np.abs(field["state_vectors"]-full["state_vectors"])))
    return {**row, "passed": full["header"]["status"] == "completed" and action_error <= tolerance and state_error <= tolerance,
        "maximum_action_absolute_error": action_error, "maximum_full_state_absolute_error": state_error,
        "absolute_tolerance": tolerance}


def configuration_summary(plan, index, cases, parity):
    fits = list(product(plan["versions"], plan["tasks"], plan["head_modes"], plan["seeds"]))
    keys = [(v, t, h, s, p) for v, t, h, s in fits for p in POLICIES]
    require(len(cases) == 96 and set(cases) == set(keys), "all exact96 policy slots, no missing/extra/duplicate")
    invalid = [list(key) for ordinal, fit in enumerate(fits)
        for p in POLICIES[(index+ordinal)%4:]+POLICIES[:(index+ordinal)%4]
        for key in [(*fit, p)] if not ready(cases[key])]
    groups = []
    for v, t, h in product(plan["versions"], plan["tasks"], plan["head_modes"]):
        wanted = [(v, t, h, s, p) for s, p in product(plan["seeds"], POLICIES)]
        available = all(ready(cases[key]) for key in wanted)
        identities = {cases[key]["header"].get("selection_sources_sha256") for key in wanted}
        available = available and len(identities) == 1 and bool(next(iter(identities)))
        group = {"version": v, "task": t, "head": h, "available": available, "future": [],
            "old_mean_difference": None, "candidate_h1_cpu_ratio": None}
        if available:
            candidate = np.stack([cases[v,t,h,s,CANDIDATE]["future_losses"] for s in plan["seeds"]])
            for baseline in BASELINES:
                delta = candidate-np.stack([cases[v,t,h,s,baseline]["future_losses"] for s in plan["seeds"]])
                group["future"].append({"baseline": baseline, "mean_difference": float(delta.mean(axis=0).mean()),
                    "paired_seed_means": delta.mean(axis=1).tolist(), "sources": 512})
            old = np.stack([cases[v,t,h,s,CANDIDATE]["old_differences"] for s in plan["seeds"]])
            candidate_cpu = sum(cases[v,t,h,s,CANDIDATE]["header"]["cpu_ns"] for s in plan["seeds"])
            h1_cpu = sum(cases[v,t,h,s,BASELINES[0]]["header"]["cpu_ns"] for s in plan["seeds"])
            group.update(old_mean_difference=float(old.mean(axis=0).mean()), old_paired_seed_means=old.mean(axis=1).tolist(),
                candidate_cpu_ns=candidate_cpu, h1_cpu_ns=h1_cpu, candidate_h1_cpu_ratio=candidate_cpu/h1_cpu)
        groups.append(group)
    expected_ids = {f"{v}-{t}-seed{s}-{h}" for v,t,h,s in fits}
    parity_passed = (len(parity) == 24 and {r["fit_id"] for r in parity} == expected_ids
        and all(r["configuration_index"] == index and r["passed"] is True for r in parity))
    ratios = [g["candidate_h1_cpu_ratio"] for g in groups if g["available"]]
    old = [g["old_mean_difference"] for g in groups if g["available"]]
    future = [x["mean_difference"] for g in groups for x in g["future"]]
    eligible = not invalid and all(g["available"] for g in groups) and parity_passed and all(x <= 3. for x in ratios)
    plausible = eligible and all(x <= -.006 for x in future) and all(x <= -.020 for x in old)
    rank = [max(0.,max(old)), max(future), float(np.mean(future)), max(ratios), index] if eligible else None
    return {"index": index, "registered": 96, "observed": 96, "missing": [], "unexpected": [], "duplicates": [],
        "invalid": invalid, "groups": groups, "full_reference_parity": parity,
        "full_reference_parity_passed": parity_passed, "eligible": eligible, "plausible": plausible, "rank": rank}


def recompute(plan, cases, all_parity):
    require(tuple(plan["primary_policies"]) == POLICIES and len(cases) == 1152, "registered complete four-policy grid")
    summaries, table = [], []
    for index in range(12):
        subset = {key[1:]: value for key,value in cases.items() if key[0] == index}
        parity = [r for r in all_parity if r["configuration_index"] == index]
        summary = configuration_summary(plan, index, subset, parity)
        summaries.append(summary)
        groups = summary["groups"]
        future = [r["mean_difference"] for g in groups for r in g["future"]]
        old = [g["old_mean_difference"] for g in groups if g["available"]]
        ratios = [g["candidate_h1_cpu_ratio"] for g in groups if g["available"]]
        table.append({"index": index, "configuration": plan["configurations"][index]["configuration"],
            "statuses": dict(Counter(c["header"]["status"] for c in subset.values())),
            "complete_primary": sum(ready(c) for c in subset.values()),
            "complete_candidate": sum(ready(c) for key,c in subset.items() if key[-1] == CANDIDATE),
            "actual_error_records": sum(bool(c["actual_errors"]) for c in subset.values()),
            "eligible": summary["eligible"], "plausible": summary["plausible"],
            "full_field_parity_passed": summary["full_reference_parity_passed"],
            "available_32step_groups": sum(g["available"] for g in groups),
            "future_difference_minimum": min(future) if future else None,
            "future_difference_maximum": max(future) if future else None,
            "future_mean_thresholds_met": sum(x <= -.006 for x in future),
            "old_difference_minimum": min(old) if old else None,
            "old_difference_maximum": max(old) if old else None,
            "old_mean_thresholds_met": sum(x <= -.020 for x in old),
            "cpu_ratio_minimum": min(ratios) if ratios else None,
            "cpu_ratio_maximum": max(ratios) if ratios else None})
    eligible = [r for r in summaries if r["eligible"]]
    plausible = [r for r in eligible if r["plausible"]]
    winner = min(plausible or eligible, key=lambda r: tuple(r["rank"])) if eligible else None
    selection = {"eligible_indices": [r["index"] for r in eligible], "plausible_indices": [r["index"] for r in plausible],
        "selected_index": winner["index"] if winner else None,
        "selected_scope": "plausible_for_separate_confirmation" if plausible else "diagnostic_only" if eligible else "none",
        "confirmation_plausibility_passed": bool(plausible), "fresh_confirmation_executed": False, "scientific_acceptance": False}
    return summaries, selection, table


def compare(computed, recorded, path="statistics"):
    if isinstance(computed, dict):
        require(isinstance(recorded, dict), path+": object required")
        return max([compare(v,recorded[k],path+"/"+k) for k,v in computed.items()] or [0.])
    if isinstance(computed, list):
        require(isinstance(recorded,list) and len(computed)==len(recorded), path+": exact list census")
        return max([compare(a,b,path+"/"+str(i)) for i,(a,b) in enumerate(zip(computed,recorded,strict=True))] or [0.])
    if isinstance(computed,float):
        require(isinstance(recorded,(int,float)) and np.isfinite(recorded), path+": finite scalar")
        error = abs(computed-recorded)
        require(error <= 1e-12, path+": arithmetic mismatch")
        return error
    require(computed == recorded, path+": categorical or census mismatch")
    return 0.
