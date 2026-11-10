"""Prespecified source-level MEM6 inference; missing labels stay visible.

Each source receives equal weight after averaging its planned paired cases.
The bootstrap resamples whole sources within the frozen role. Its interpretation
requires source independence; this code cannot establish that external fact.
"""

from collections import defaultdict
import math
import random


PROFILE = {
    "resamples": 20000,
    "seed": 20261110,
    "lower_quantile": 0.05,
    "minimum_source_groups": 20,
    "minimum_groups_each_role": 4,
    "minimum_source_mean_difference": 0.05,
}


def source_inference(rows):
    """Read already-validated original per-episode rows, never shadow choices."""
    pairs, operations = defaultdict(dict), set()
    for row in rows:
        operation, mode = row["original_operation_id"], row["mode"]
        if operation in operations or mode not in {"current_only", "bounded"}:
            raise ValueError("unique operations and the two retention modes required")
        operations.add(operation)
        pair = pairs[row["pair_id"]]
        if mode in pair or row["unconditional_success"] not in (True, False, None):
            raise ValueError("duplicate arm or invalid success observation")
        if (
            row["unconditional_success"] is not None
            and type(row["unconditional_success"]) is not bool
        ):
            raise ValueError("success must be Boolean or unknown")
        pair[mode] = row
    if not pairs:
        raise ValueError("nonempty complete planned pairs required")
    sources = defaultdict(list)
    roles = {}
    unknown_pairs = 0
    for pair in pairs.values():
        if set(pair) != {"current_only", "bounded"}:
            raise ValueError("missing arms must be explicit UNKNOWN rows")
        off, on = pair["current_only"], pair["bounded"]
        for field in ("source_group_id", "split", "case_id"):
            if off[field] != on[field]:
                raise ValueError("paired source, role or case differs")
        source, role = on["source_group_id"], on["split"]
        if (
            role not in {"development", "retention_validation"}
            or roles.setdefault(source, role) != role
        ):
            raise ValueError("one released role per source required")
        a, b = on["unconditional_success"], off["unconditional_success"]
        unknown_pairs += a is None or b is None
        lower = (0 if a is None else int(a)) - (1 if b is None else int(b))
        upper = (1 if a is None else int(a)) - (0 if b is None else int(b))
        sources[source].append((lower, upper))
    bounds, strata = {}, defaultdict(list)
    for source in sorted(sources):
        values = sources[source]
        lower = sum(x[0] for x in values) / len(values)
        upper = sum(x[1] for x in values) / len(values)
        bounds[source] = {
            "role": roles[source],
            "planned_pairs": len(values),
            "missing_label_bounds": [lower, upper],
        }
        strata[roles[source]].append(lower)
    n = len(bounds)
    lower_mean = sum(v["missing_label_bounds"][0] for v in bounds.values()) / n
    upper_mean = sum(v["missing_label_bounds"][1] for v in bounds.values()) / n
    rng, bootstrap = random.Random(PROFILE["seed"]), []
    for _ in range(PROFILE["resamples"]):
        sample = [
            rng.choice(strata[role])
            for role in sorted(strata)
            for _ in range(len(strata[role]))
        ]
        bootstrap.append(sum(sample) / n)
    bootstrap.sort()
    lower = bootstrap[math.ceil(PROFILE["lower_quantile"] * len(bootstrap)) - 1]
    adequate = n >= PROFILE["minimum_source_groups"] and all(
        len(strata[role]) >= PROFILE["minimum_groups_each_role"]
        for role in ("development", "retention_validation")
    )
    return {
        "schema": "hepta.mem6.source-inference.v1",
        "profile": dict(PROFILE),
        "planned_pairs": len(pairs),
        "unknown_pairs": unknown_pairs,
        "source_group_count": n,
        "by_source": bounds,
        "role_source_counts": {k: len(v) for k, v in strata.items()},
        "source_equal_weight_difference": lower_mean if not unknown_pairs else None,
        "missing_label_bounds": [lower_mean, upper_mean],
        "worst_case_unknown_one_sided_95pct_lower": lower,
        "adequate_prespecified_source_count": adequate,
        "numerical_benefit_threshold_met": adequate
        and lower > 0
        and lower_mean >= PROFILE["minimum_source_mean_difference"],
        "source_independence_authenticated": False,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "interpretation": "Stratified source bootstrap conditional on source independence; not a guarantee or owner/cost qualification",
    }
