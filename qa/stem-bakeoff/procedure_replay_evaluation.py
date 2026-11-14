"""Real selected executions and grouped, explicitly exploratory comparisons."""

from collections import defaultdict
import random
import statistics


def evaluate_policy(cases, choices, *, arm, policy, costs=None):
    from procedure_replay_probe import attempt
    rows = []
    selected_cases = [case for case in cases if case.query.split in ("development", "heldout")]
    if set(choices) != {case.query.query_id for case in selected_cases}:
        raise ValueError("evaluation predictions must cover exactly dev and heldout queries")
    for case in selected_cases:
        choice = choices[case.query.query_id]
        if choice is None:
            row = {"query_id": case.query.query_id, "input_family": case.query.input_family,
                   "template_family": case.query.template_family, "split": case.query.split,
                   "choice": None, "execution": {"execution_calls": 0, "elapsed_ns": 0,
                                                "execution_error": None},
                   "observation": {"success": False}, "abstained": True}
        else:
            row = {**attempt(case, choice), "abstained": False}
        row.update(arm=arm, policy=policy, selector_cost=(costs or {}).get(case.query.query_id, {}))
        rows.append(row)
    summary = {}
    for split in ("development", "heldout"):
        part = [row for row in rows if row["split"] == split]
        executed = [row for row in part if not row["abstained"]]
        successes = sum(row["observation"]["success"] for row in part)
        summary[split] = {"queries": len(part), "successes": successes,
            "success_rate": successes / len(part), "abstentions": len(part) - len(executed),
            "coverage": len(executed) / len(part),
            "selective_success": successes / len(executed) if executed else None,
            "execution_calls": sum(row["execution"]["execution_calls"] for row in part),
            "failed_executions": len(executed) - successes,
            "execution_errors": sum(row["execution"]["execution_error"] is not None for row in part),
            "execution_ns": sum(row["execution"]["elapsed_ns"] for row in part),
            "selector_ns": sum(row["selector_cost"].get("selector_ns", 0) for row in part),
            "per_template": _group_rates(part, "template_family"),
            "per_input_family": _group_rates(part, "input_family")}
    return {"rows": rows, "summary": summary}


def _group_rates(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(int(row["observation"]["success"]))
    return {group: sum(values) / len(values) for group, values in sorted(groups.items())}


def paired_interval(candidate, baseline, *, grouping):
    left = {row["query_id"]: row for row in candidate if row["split"] == "heldout"}
    right = {row["query_id"]: row for row in baseline if row["split"] == "heldout"}
    if set(left) != set(right):
        raise ValueError("paired results do not cover the same heldout queries")
    groups = defaultdict(list)
    for query_id, row in left.items():
        groups[row[grouping]].append(int(row["observation"]["success"])
                                    - int(right[query_id]["observation"]["success"]))
    means = [statistics.mean(values) for values in groups.values()]
    rng = random.Random(77103)
    samples = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(2000))
    return {"grouping": grouping, "groups": len(means), "difference": statistics.mean(means),
            "bootstrap_95_interval": [samples[49], samples[1949]],
            "low_power_and_artificial_template_dependence": True}
