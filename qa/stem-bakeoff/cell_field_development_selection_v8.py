"""Frozen descriptive selection for the twelve V8 development configurations.

These reused historical samples cannot provide confirmatory acceptance. The
plausibility subset only decides whether a separately frozen fresh study merits
consuming its source reserve. No failed trajectory is removed from the census.
"""

from itertools import product

import numpy as np


VERSIONS = ("v5", "v6")
TASKS = ("agnews", "dbpedia")
HEADS = ("linear", "gated")
SEEDS = (7, 17, 29)
POLICIES = ("myopic_h1", "loss2_h8", "future_field_h8", "full_h8")
BASELINES = POLICIES[:2]
CANDIDATE = POLICIES[2]
GROUPS = tuple(product(VERSIONS, TASKS, HEADS))
SELECTION_RULE = {
    "required_policy_outputs_per_configuration": 96, "required_completed_steps": 32,
    "candidate_h1_cpu_ratio_maximum_each_of_8_groups": 3.0,
    "plausible_future_mean_difference_maximum_each_of_16_comparisons": -0.006,
    "plausible_old_mean_difference_maximum_each_of_8_groups": -0.020,
    "eligible": "complete unique census; all96 finite audited32-step trajectories; no actual errors; all8 CPU ratios<=3",
    "selection": "rank plausible subset if nonempty; otherwise best eligible is diagnostic only; no eligible means no selected configuration",
    "rank": ["maximum_positive_old_difference", "worst_future_difference", "mean_future_difference", "maximum_cpu_ratio", "configuration_index"],
    "pairing": "same512 source components per role; average3 paired seed differences per source then average sources",
    "nll": "-log(max(true_class_probability,float64_tiny)); identical to historical source-statistics exports",
    "full_reference": "run full_h8 at every configuration and fit with identical stride; all24 trace parities required for eligibility",
    "forecast_scope": "H8 risk forecast; certified prefix stride1/2/4/8; no safety claim about discarded forecast tail",
    "future_screen_reason": "conservative available-source power planning: stronger than prior -0.003, not a significance gate",
    "scientific_acceptance": False,
}


def configurations():
    return [{"index": index, "configuration": {
        "steps": 32, "dt": 0.02, "effort_price": 0.03, "action_bound": 4.0,
        "old_weight": old, "current_dispersion": 0.0, "relinearizations": 0,
        "commit_stride": stride}}
        for index, (old, stride) in enumerate(product((0.0, 0.25, 0.5), (1, 2, 4, 8)))]


def _finite_row(row):
    try:
        arrays = [np.asarray(row[name], dtype=np.float64) for name in ("future_losses", "old_differences")]
        return (all(a.shape == (512,) and np.isfinite(a).all() for a in arrays)
            and type(row["cpu_ns"]) is int and row["cpu_ns"] > 0)
    except (KeyError, TypeError, ValueError):
        return False


def summarize_configuration(index, rows, parity):
    """Return all8 descriptive groups and eligibility, preserving missing slots."""
    expected = set(product(VERSIONS, TASKS, HEADS, SEEDS, POLICIES))
    slots, unexpected, duplicates = {}, [], []
    for row in rows:
        key = tuple(row.get(k) for k in ("version", "task", "head", "seed", "policy"))
        if key not in expected:
            unexpected.append(list(key))
        elif key in slots:
            duplicates.append(list(key))
        else:
            slots[key] = row
    missing = [list(key) for key in sorted(expected-set(slots))]
    invalid = []
    for key, row in slots.items():
        if (row.get("status") != "completed" or row.get("completed_steps") != 32
                or row.get("error") or row.get("audit_passed") is not True or not _finite_row(row)):
            invalid.append(list(key))
    groups = []
    for version, task, head in GROUPS:
        group = {"version": version, "task": task, "head": head,
            "available": False, "future": [], "old_mean_difference": None, "candidate_h1_cpu_ratio": None}
        wanted = [(version, task, head, seed, policy) for seed, policy in product(SEEDS, POLICIES)]
        available = all(key in slots and _finite_row(slots[key])
            and slots[key].get("status") == "completed" and slots[key].get("completed_steps") == 32
            and slots[key].get("audit_passed") is True and not slots[key].get("error") for key in wanted)
        available = available and len({slots[key].get("selection_sources_sha256") for key in wanted}) == 1
        if available and all(slots[key].get("selection_sources_sha256") for key in wanted):
            def values(policy, field):
                return np.stack([np.asarray(slots[version, task, head, seed, policy][field]) for seed in SEEDS])
            candidate = values(CANDIDATE, "future_losses")
            for baseline in BASELINES:
                delta = candidate-values(baseline, "future_losses")
                group["future"].append({"baseline": baseline, "mean_difference": float(delta.mean(axis=0).mean()),
                    "paired_seed_means": delta.mean(axis=1).tolist(), "sources": 512})
            old = values(CANDIDATE, "old_differences")
            candidate_cpu = sum(slots[version, task, head, seed, CANDIDATE]["cpu_ns"] for seed in SEEDS)
            h1_cpu = sum(slots[version, task, head, seed, BASELINES[0]]["cpu_ns"] for seed in SEEDS)
            group.update(available=True, old_mean_difference=float(old.mean(axis=0).mean()),
                old_paired_seed_means=old.mean(axis=1).tolist(), candidate_cpu_ns=candidate_cpu,
                h1_cpu_ns=h1_cpu, candidate_h1_cpu_ratio=candidate_cpu/h1_cpu)
        groups.append(group)
    complete = not (missing or unexpected or duplicates or invalid) and all(g["available"] for g in groups)
    ratios = [g["candidate_h1_cpu_ratio"] for g in groups if g["available"]]
    expected_fits = {f"{v}-{t}-seed{s}-{h}" for (v, t, h), s in product(GROUPS, SEEDS)}
    parity_passed = (len(parity) == 24 and {row["fit_id"] for row in parity} == expected_fits
        and all(row.get("configuration_index") == index and row.get("passed") is True for row in parity))
    eligible = complete and parity_passed and all(value <= 3.0 for value in ratios)
    future = [row["mean_difference"] for group in groups for row in group["future"]]
    old = [g["old_mean_difference"] for g in groups if g["available"]]
    plausible = eligible and all(x <= -0.006 for x in future) and all(x <= -0.020 for x in old)
    rank = ([max(0.0, max(old)), max(future), float(np.mean(future)), max(ratios), index]
        if eligible else None)
    return {"index": index, "registered": 96, "observed": len(rows), "missing": missing,
        "unexpected": unexpected, "duplicates": duplicates, "invalid": invalid,
        "groups": groups, "eligible": eligible, "plausible": plausible, "rank": rank,
        "full_reference_parity": parity, "full_reference_parity_passed": parity_passed,
        "scope": "development only; all prior roles reused; full reference at every fit; no scientific acceptance"}


def select_configuration(summaries):
    if (len(summaries) != 12 or sorted(row["index"] for row in summaries) != list(range(12))):
        raise ValueError("all twelve configuration summaries, including failures, are required")
    eligible = [row for row in summaries if row["eligible"]]
    plausible = [row for row in eligible if row["plausible"]]
    selected = min(plausible or eligible, key=lambda row: tuple(row["rank"])) if eligible else None
    return {"schema": "hepta.cell-field-development-selection.v8", "rule": SELECTION_RULE,
        "eligible_indices": [r["index"] for r in eligible], "plausible_indices": [r["index"] for r in plausible],
        "selected_index": selected["index"] if selected else None,
        "selected_scope": "plausible_for_separate_confirmation" if plausible else "diagnostic_only" if eligible else "none",
        "confirmation_plausibility_passed": bool(plausible),
        "fresh_confirmation_executed": False,
        "next_condition": "independent selected-policy replay/parity audit and separately frozen fresh protocol required",
        "scientific_acceptance": False}
