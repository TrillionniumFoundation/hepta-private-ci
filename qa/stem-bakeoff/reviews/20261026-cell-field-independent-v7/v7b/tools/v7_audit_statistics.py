"""Independent descriptive arithmetic and frozen V7 selection, without scorer imports."""

from collections import Counter
from itertools import product

import numpy as np

from v7_audit_records import require


def recompute(plan, cases):
    policies = plan["primary_policies"]
    candidate, baselines = "future_field_h8", ("myopic_h1", "loss2_h8")
    groups = list(product(plan["versions"], plan["tasks"], plan["head_modes"]))
    seeds = plan["seeds"]
    summaries, table, maximum_difference = [], [], 0.
    for index in range(12):
        ordered = []
        for ordinal, (version, task, head, seed) in enumerate(product(plan["versions"], plan["tasks"], plan["head_modes"], seeds)):
            shift = (index+ordinal) % 3
            for policy in policies[shift:]+policies[:shift]:
                ordered.append((index, version, task, head, seed, policy))
        require(all(key in cases for key in ordered), "all72 primary records required in every configuration")
        invalid, results = [], []
        for key in ordered:
            case, header = cases[key], cases[key]["header"]
            if not (case["available"] and header["status"] == "completed" and header["completed_steps"] == 32
                    and not header["error"] and header["audit_passed"] is True):
                invalid.append(list(key[1:]))
        for version, task, head in groups:
            by_policy = {policy: [cases[index, version, task, head, seed, policy] for seed in seeds] for policy in policies}
            all_cases = [row for policy in policies for row in by_policy[policy]]
            available = all(case["available"] for case in all_cases)
            available = available and len({case["header"]["selection_sources_sha256"] for case in all_cases}) == 1
            result = {"version": version, "task": task, "head": head, "available": available,
                "future": [], "old_mean_difference": None, "candidate_h1_cpu_ratio": None}
            if available:
                candidate_values = np.stack([case["future_losses"] for case in by_policy[candidate]])
                for baseline in baselines:
                    differences = candidate_values-np.stack([case["future_losses"] for case in by_policy[baseline]])
                    result["future"].append({"baseline": baseline, "mean_difference": float(np.mean(np.mean(differences, axis=0))),
                        "paired_seed_means": np.mean(differences, axis=1).tolist(), "sources": 512})
                old = np.stack([case["old_differences"] for case in by_policy[candidate]])
                candidate_cpu = sum(case["header"]["cpu_ns"] for case in by_policy[candidate])
                h1_cpu = sum(case["header"]["cpu_ns"] for case in by_policy[baselines[0]])
                result.update(old_mean_difference=float(np.mean(np.mean(old, axis=0))),
                    old_paired_seed_means=np.mean(old, axis=1).tolist(), candidate_cpu_ns=candidate_cpu,
                    h1_cpu_ns=h1_cpu, candidate_h1_cpu_ratio=candidate_cpu/h1_cpu)
            results.append(result)
        ratios = [row["candidate_h1_cpu_ratio"] for row in results if row["available"]]
        old = [row["old_mean_difference"] for row in results if row["available"]]
        future = [item["mean_difference"] for row in results for item in row["future"]]
        eligible = not invalid and all(row["available"] for row in results) and all(ratio <= 3. for ratio in ratios)
        plausible = eligible and all(value <= -.003 for value in future) and all(value <= -.020 for value in old)
        rank = [max(0., max(old)), max(future), float(np.mean(future)), max(ratios), index] if eligible else None
        summaries.append({"index": index, "registered": 72, "observed": 72, "missing": [], "unexpected": [],
            "duplicates": [], "invalid": invalid, "groups": results, "eligible": eligible, "plausible": plausible, "rank": rank})
        candidates = [cases[key] for key in ordered if key[-1] == candidate]
        table.append({"index": index, "configuration": plan["configurations"][index]["configuration"],
            "statuses": dict(Counter(cases[key]["header"]["status"] for key in ordered)),
            "complete_primary": sum(cases[key]["header"]["status"] == "completed" and cases[key]["header"]["completed_steps"] == 32 for key in ordered),
            "complete_candidate": sum(case["header"]["status"] == "completed" and case["header"]["completed_steps"] == 32 for case in candidates),
            "actual_error_records": sum(bool(cases[key]["actual_errors"]) for key in ordered),
            "eligible": eligible, "plausible": plausible,
            "future_difference_minimum": min(future) if future else None,
            "future_difference_maximum": max(future) if future else None,
            "future_mean_thresholds_met": sum(value <= -.003 for value in future),
            "old_difference_minimum": min(old) if old else None,
            "old_difference_maximum": max(old) if old else None,
            "old_mean_thresholds_met": sum(value <= -.020 for value in old),
            "cpu_ratio_minimum": min(ratios) if ratios else None,
            "cpu_ratio_maximum": max(ratios) if ratios else None})
    eligible = [row for row in summaries if row["eligible"]]
    plausible = [row for row in eligible if row["plausible"]]
    winner = min(plausible or eligible, key=lambda row: tuple(row["rank"])) if eligible else None
    selection = {"eligible_indices": [row["index"] for row in eligible],
        "plausible_indices": [row["index"] for row in plausible], "selected_index": winner["index"] if winner else None,
        "selected_scope": "plausible_for_separate_confirmation" if plausible else "diagnostic_only" if eligible else "none",
        "confirmation_plausibility_passed": bool(plausible), "scientific_acceptance": False,
        "fresh_confirmation_executed": False}
    return summaries, selection, table


def compare(computed, recorded, path="statistics"):
    """Compare all arithmetic fields while allowing explanatory extra keys."""
    if isinstance(computed, dict):
        require(isinstance(recorded, dict), path+": object")
        return max([compare(value, recorded[key], path+"/"+key) for key, value in computed.items()] or [0.])
    if isinstance(computed, list):
        require(isinstance(recorded, list) and len(computed) == len(recorded), path+": complete list")
        return max([compare(a, b, path+"/"+str(i)) for i, (a, b) in enumerate(zip(computed, recorded, strict=True))] or [0.])
    if isinstance(computed, float):
        require(isinstance(recorded, (int, float)) and np.isfinite(recorded), path+": finite scalar")
        error = abs(computed-recorded)
        require(error <= 1e-12, path+": arithmetic mismatch")
        return error
    require(computed == recorded, path+": exact categorical/census mismatch")
    return 0.
