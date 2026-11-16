"""Prespecified V5 inference; stopped diagnostics remain visible and scored.

The candidate and its two primary baselines must finish the same32 updates.
Bootstrap coverage is approximate and conditional on fixed fitted seeds/sources.
"""

import itertools

import numpy as np

from cell_field_evaluate import metrics
from cell_field_evaluate_v4 import _draw_components, bootstrap_upper


TASKS = ("agnews", "dbpedia")
HEADS = ("linear", "gated")
SEEDS = (7, 17, 29)
POLICIES = ("zero", "myopic_full_h1", "myopic_guarded_h1", "loss2_h8", "adjoint_h8", "response_h8_guarded")
CANDIDATE = "response_h8_guarded"
BASELINES = ("myopic_full_h1", "loss2_h8")
REQUIRED_COMPLETION = (CANDIDATE, *BASELINES)
SPLITS = ("current", "future", "old")


def evaluation_protocol():
    return {"tasks": list(TASKS), "heads": list(HEADS), "seeds": list(SEEDS), "policies": list(POLICIES),
        "candidate": CANDIDATE, "primary_future_baselines": list(BASELINES), "required_completed_policies": list(REQUIRED_COMPLETION),
        "required_completed_steps": 32, "splits": list(SPLITS), "bootstrap_replicates": 10000, "bootstrap_seed": 20261025,
        "family_alpha": .05, "family_size": 12, "improvement_margin": .001, "retention_margin": 0., "max_cpu_ratio": 3.,
        "bootstrap_method": "class-stratified source-component percentile; per-example seed average; higher quantile",
        "all_policy_census": 72, "cpu_aggregation": "sum over three paired seeds per task/head",
        "stopped_policy_scoring": "retain actual terminal predictions and count stops; only declared required policies block completion gate; all actual execution errors/missing/nonfinite outputs block acceptance",
        "cpu_scope": "own response construction, solver, all prospective trials and committed transitions; identical output/evaluation I/O separately reported",
        "independent_old_path": "report old-test NLL maximum excess across all actually committed states descriptively; primary retention gate remains terminal vs warmup"}


def _entry(collection, task, head, seed):
    group = collection.get(task, {}).get(head, {})
    return group.get(seed, group.get(str(seed), {}))


def _valid_cost(info):
    return (info.get("valid_record") is True and type(info.get("cpu_ns")) in (int, float)
            and np.isfinite(info["cpu_ns"]) and info["cpu_ns"] > 0)


def _complete(info):
    return (_valid_cost(info) and info.get("status") == "completed"
            and info.get("completed_steps") == info.get("registered_steps") == 32)


def evaluate_probabilities(probabilities, labels, components, protocol, costs):
    plan = protocol.get("evaluation", protocol)
    if plan != evaluation_protocol():
        raise ValueError("V5 closed comparison family, margins or completion policy changed")
    prepared, rng = {}, np.random.default_rng(plan["bootstrap_seed"])
    for task in TASKS:
        seen = set()
        for split in SPLITS:
            values = set(np.asarray(components[task][split]).tolist())
            if seen & values:
                raise ValueError("a source component crosses evaluation roles")
            seen |= values
            prepared[task, split] = _draw_components(labels[task][split], components[task][split], rng, plan["bootstrap_replicates"])
    records, scores = [], {}
    for task, head, seed in itertools.product(TASKS, HEADS, SEEDS):
        entry = _entry(probabilities, task, head, seed)
        timing = _entry(costs, task, head, seed)
        for policy in (*POLICIES, "warmup_old"):
            for split in (("old",) if policy == "warmup_old" else SPLITS):
                record = {"task": task, "head": head, "seed": seed, "policy": policy, "split": split}
                value = entry.get(policy) if policy == "warmup_old" else entry.get(policy, {}).get(split)
                if policy != "warmup_old":
                    record.update(execution_status=timing.get(policy, {}).get("status"),
                                  completed_steps=timing.get(policy, {}).get("completed_steps"))
                if value is None:
                    record.update(status="unavailable", reason="missing frozen prediction")
                else:
                    try:
                        summary, loss, _ = metrics(value, labels[task][split])
                        record.update(status="completed", **summary)
                        scores[task, head, seed, policy, split] = loss
                    except (ValueError, TypeError) as error:
                        record.update(status="invalid", reason=str(error))
                records.append(record)
    completion, eligible = [], {}
    for task, head in itertools.product(TASKS, HEADS):
        checks = []
        for seed, policy in itertools.product(SEEDS, REQUIRED_COMPLETION):
            info = _entry(costs, task, head, seed).get(policy, {})
            row = {"task": task, "head": head, "seed": seed, "policy": policy, "required_steps": 32,
                   "status": info.get("status", "unavailable"), "completed_steps": info.get("completed_steps"), "criterion_met": _complete(info)}
            completion.append(row)
            checks.append(row["criterion_met"])
        eligible[task, head] = all(checks)
    primary = []
    comparisons = (("future", BASELINES[0], -.001), ("future", BASELINES[1], -.001), ("old", "warmup_old", 0.))
    for task, head, (split, baseline, threshold) in itertools.product(TASKS, HEADS, comparisons):
        row = {"task": task, "head": head, "split": split, "candidate": CANDIDATE, "baseline": baseline,
               "threshold": threshold, "criterion_met": False, "status": "unavailable", "completion_eligible": eligible[task, head]}
        keys = [(task, head, seed, policy, split) for seed in SEEDS for policy in (CANDIDATE, baseline)]
        if all(key in scores for key in keys):
            paired = np.stack([scores[task, head, seed, CANDIDATE, split]-scores[task, head, seed, baseline, split] for seed in SEEDS])
            interval = bootstrap_upper(paired.mean(axis=0), labels[task][split], components[task][split], prepared=prepared[task, split])
            threshold_met = interval["upper_bound"] < threshold if split == "future" else interval["upper_bound"] <= threshold
            row.update(status="completed" if eligible[task, head] else "scored_but_incomplete_execution", **interval,
                numerical_threshold_met=bool(threshold_met), criterion_met=bool(threshold_met and eligible[task, head]),
                paired_seed_mean_differences=paired.mean(axis=1).tolist())
        primary.append(row)
    cost_contrasts = []
    for task, head in itertools.product(TASKS, HEADS):
        row = {"task": task, "head": head, "candidate": CANDIDATE, "baseline": "myopic_full_h1",
               "threshold": 3., "status": "unavailable", "criterion_met": False, "completion_eligible": eligible[task, head]}
        pair = [[_entry(costs, task, head, seed).get(policy, {}) for policy in (CANDIDATE, "myopic_full_h1")] for seed in SEEDS]
        if all(_valid_cost(info) for both in pair for info in both):
            ratio = sum(both[0]["cpu_ns"] for both in pair)/sum(both[1]["cpu_ns"] for both in pair)
            row.update(status="completed" if eligible[task, head] else "scored_but_incomplete_execution", cpu_ratio=float(ratio),
                criterion_met=bool(ratio <= 3 and eligible[task, head]),
                paired_seed_cpu_ratios=[both[0]["cpu_ns"]/both[1]["cpu_ns"] for both in pair])
        cost_contrasts.append(row)
    all_costs = [_entry(costs, task, head, seed).get(policy, {}) for task, head, seed, policy in itertools.product(TASKS, HEADS, SEEDS, POLICIES)]
    prediction_census = all(row["status"] == "completed" for row in records)
    execution_census = all(info.get("valid_record") is True for info in all_costs)
    cost_census = all(_valid_cost(info) for info in all_costs)
    complete = all(row["criterion_met"] for row in completion)
    science = prediction_census and execution_census and complete and all(row["criterion_met"] for row in primary)
    resources = cost_census and complete and all(row["criterion_met"] for row in cost_contrasts)
    return {"schema": "hepta.cell-field-fresh-evaluation.v5", "candidate": CANDIDATE, "records": records,
        "primary_contrasts": primary, "cost_contrasts": cost_contrasts, "completion_gates": completion,
        "registered_fits": 12, "registered_policy_outputs": 72, "census_complete": bool(prediction_census and execution_census),
        "cost_census_complete": cost_census, "required_completion_met": complete,
        "candidate_completed_fits": sum(row["criterion_met"] for row in completion if row["policy"] == CANDIDATE),
        "primary_criteria_met": sum(row["criterion_met"] for row in primary),
        "all_scientific_criteria_met": bool(science), "all_cost_criteria_met": bool(resources),
        "all_registered_gates_met": bool(science and resources),
        "cost_records": [{"task": task, "head": head, "seed": seed, "policy": policy,
            **_entry(costs, task, head, seed).get(policy, {})} for task, head, seed, policy in itertools.product(TASKS, HEADS, SEEDS, POLICIES)],
        "bootstrap": {**plan, "scope": "approximate conditional percentile family; fitted seeds/actions are not independent source samples"},
        "authority": "DENY_ALL", "production_authority": False}
