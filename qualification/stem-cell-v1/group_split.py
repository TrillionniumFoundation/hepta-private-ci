"""Advisory split selection under a fixed normalized external objective.

The confidence bound is a conservative, nonasymptotic Hoeffding bound on
equally weighted SOURCE GROUP means. Dependence inside a group is allowed;
independence between groups and genuine heldout provenance are declarations,
not established by this code. No test-set outcomes may select a candidate.
Bounds concern one preregistered candidate, not repeated or adaptive searches.
This is the linear normalized utility profile, not a general NDU/FBSDE solver.
"""
import hashlib
import json
import math


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _number(value, name, lower=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < lower:
        raise ValueError(f"finite {name} >= {lower} required")


def _identity(value, name):
    if not isinstance(value, str) or not 1 <= len(value.encode()) <= 256:
        raise ValueError(f"bounded {name} required")


def _sha(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("sha256 identity required")
    try:
        if len(bytes.fromhex(value)) != 32:
            raise ValueError("invalid digest length")
    except ValueError as exc:
        raise ValueError("hex sha256 identity required") from exc


def selection_manifest_sha256(pairs):
    """Register case membership before labels; does not certify provenance."""
    return _digest(sorted((p["before_case_id"], p["after_case_id"],
                           p["source_group"], p["cohort"]) for p in pairs))


def freeze_split_policy(*, subject_id, parent_candidate_id, candidate_id, generation,
                        objective_sha256, selection_manifest_sha256, prices,
                        cpu_seconds_bound, wall_seconds_bound, min_source_groups=30,
                        confidence=.95, max_old_regression=.05, minimum_net_gain=0):
    """Freeze thresholds, normalized prices and candidate BEFORE selection.

    cpu_second/wall_second prices are separate declared resource and latency
    preferences; byte_second prices extra residency. Prices must be chosen
    externally, never optimized against these heldout labels.
    """
    for name, value in (("subject", subject_id), ("parent", parent_candidate_id),
                        ("candidate", candidate_id)):
        _identity(value, name)
    if parent_candidate_id == candidate_id:
        raise ValueError("split candidate must differ from parent")
    if type(generation) is not int or generation < 1:
        raise ValueError("positive split generation required")
    for value in (objective_sha256, selection_manifest_sha256):
        _sha(value)
    if not isinstance(prices, dict) or set(prices) != {"cpu_second", "wall_second", "byte_second"}:
        raise ValueError("complete normalized cost prices required")
    for value in prices.values():
        _number(value, "price")
    if not any(prices.values()):
        raise ValueError("at least one positive cost price required")
    for name, value in (("CPU bound", cpu_seconds_bound), ("wall bound", wall_seconds_bound),
                        ("minimum gain", minimum_net_gain), ("retention margin", max_old_regression)):
        _number(value, name)
    if (type(min_source_groups) is not int or min_source_groups < 2
            or type(confidence) not in (int, float) or not .5 < confidence < 1
            or max_old_regression > 1):
        raise ValueError("valid confidence, group count and retention margin required")
    body = dict(schema="hepta.group-split.selection.v1", subject_id=subject_id,
                parent_candidate_id=parent_candidate_id, candidate_id=candidate_id,
                generation=generation, objective_sha256=objective_sha256,
                selection_manifest_sha256=selection_manifest_sha256, prices=dict(prices),
                cpu_seconds_bound=cpu_seconds_bound, wall_seconds_bound=wall_seconds_bound,
                min_source_groups=min_source_groups, confidence=confidence,
                max_old_regression=max_old_regression, minimum_net_gain=minimum_net_gain)
    return {**body, "policy_id": _digest(body)}


def assess_split(policy, pairs, overhead, *, preregistered_policy_id,
                 independent_source_groups_declared=False):
    """Return evidence and a retain/reject suggestion; never mutate a Cell.

    Complete per-arm observed costs are mandatory, including zero costs.
    Oneoff training/migration and extra residency are amortized ONLY over the
    number of actually paired observations, never a projected future volume.
    Caller must preserve the frozen registration externally; digest equality
    authenticates neither preregistration time nor source independence.
    """
    try:
        expected = freeze_split_policy(**{k: v for k, v in policy.items()
                                         if k not in ("schema", "policy_id")})
    except (TypeError, AttributeError) as exc:
        raise ValueError("complete frozen split policy required") from exc
    if policy != expected or preregistered_policy_id != expected["policy_id"]:
        raise ValueError("split policy differs from preregistered thresholds")
    if type(independent_source_groups_declared) is not bool:
        raise ValueError("explicit independence declaration required")
    if not isinstance(pairs, (list, tuple)) or not 1 <= len(pairs) <= 1_000_000:
        raise ValueError("bounded nonempty paired selection observations required")
    price = policy["prices"]
    groups = {"new": {}, "old": {}, "all": {}}
    seen = set()
    for pair in pairs:
        required = {"before_case_id", "after_case_id", "source_group", "cohort", "split",
                    "objective_sha256", "before_success", "after_success",
                    "before_cpu_seconds", "after_cpu_seconds", "before_wall_seconds",
                    "after_wall_seconds"}
        if not isinstance(pair, dict) or set(pair) != required:
            raise ValueError("complete paired outcome/cost record required")
        for key in ("before_case_id", "after_case_id", "source_group"):
            _identity(pair[key], key)
        case = pair["before_case_id"]
        if case != pair["after_case_id"] or case in seen:
            raise ValueError("unique matched before/after case IDs required")
        seen.add(case)
        if (pair["split"] != "selection" or pair["cohort"] not in ("new", "old")
                or pair["objective_sha256"] != policy["objective_sha256"]):
            raise ValueError("fixed-objective old/new heldout selection split required")
        if any(type(pair[f"{arm}_success"]) is not bool for arm in ("before", "after")):
            raise ValueError("external binary success outcomes required")
        gain = int(pair["after_success"]) - int(pair["before_success"])
        net = gain
        for meter in ("cpu", "wall"):
            for arm in ("before", "after"):
                value = pair[f"{arm}_{meter}_seconds"]
                _number(value, f"measured {arm} {meter}")
                if value > policy[f"{meter}_seconds_bound"]:
                    raise ValueError("observed cost exceeds preregistered bounded support")
            net -= price[f"{meter}_second"] * (pair[f"after_{meter}_seconds"]
                                                - pair[f"before_{meter}_seconds"])
        groups[pair["cohort"]].setdefault(pair["source_group"], []).append((net, gain))
        groups["all"].setdefault(pair["source_group"], []).append((net, gain))
    if selection_manifest_sha256(pairs) != policy["selection_manifest_sha256"]:
        raise ValueError("selection membership differs from preregistered manifest")
    keys = {"training_cpu_seconds", "training_wall_seconds", "migration_cpu_seconds",
            "migration_wall_seconds", "resident_bytes", "resident_duration_seconds",
            "amortization_observed_count"}
    if not isinstance(overhead, dict) or set(overhead) != keys:
        raise ValueError("complete measured split lifecycle costs required")
    for key, value in overhead.items():
        _number(value, key)
    if type(overhead["resident_bytes"]) is not int:
        raise ValueError("measured integer extra resident bytes required")
    if (type(overhead["amortization_observed_count"]) is not int
            or overhead["amortization_observed_count"] != len(pairs)):
        raise ValueError("amortization denominator must equal genuinely observed pair count")
    lifecycle = sum(price[f"{meter}_second"] * sum(overhead[f"{phase}_{meter}_seconds"]
                    for phase in ("training", "migration")) for meter in ("cpu", "wall"))
    lifecycle += price["byte_second"] * overhead["resident_bytes"] * overhead["resident_duration_seconds"]
    amortized = lifecycle / len(pairs)
    if not math.isfinite(amortized):
        raise ValueError("lifecycle utility cost overflow")
    # Union bound: simultaneous lower bounds for all/new net and old retention.
    alpha = (1 - policy["confidence"]) / 3
    cost_bound = sum(price[f"{meter}_second"] * policy[f"{meter}_seconds_bound"]
                     for meter in ("cpu", "wall"))
    if not math.isfinite(cost_bound):
        raise ValueError("normalized per-case utility cost bound overflow")
    stats = {}
    for cohort, clusters in groups.items():
        n = len(clusters)
        net = [sum(v[0] for v in values) / len(values) for values in clusters.values()]
        gains = [sum(v[1] for v in values) / len(values) for values in clusters.values()]
        radius = math.sqrt(math.log(1 / alpha) / (2 * n)) if n else math.inf
        mean_net = sum(net) / n - amortized if n else None
        mean_gain = sum(gains) / n if n else None
        stats[cohort] = dict(source_groups=n, cases=sum(map(len, clusters.values())),
            mean_net_utility=mean_net, net_utility_lower=(mean_net - 2 * (1 + cost_bound) * radius
                if n else None), mean_success_gain=mean_gain,
            success_gain_lower=(mean_gain - 2 * radius if n else None))
    sufficient = (independent_source_groups_declared and
                  all(s["source_groups"] >= policy["min_source_groups"] for s in stats.values()))
    retained = sufficient and all(stats[c]["net_utility_lower"] > policy["minimum_net_gain"]
                                 for c in ("new", "all"))
    retained = retained and stats["old"]["success_gain_lower"] >= -policy["max_old_regression"]
    return dict(schema="hepta.group-split.advisory.v1", policy_id=policy["policy_id"],
        subject_id=policy["subject_id"], parent_candidate_id=policy["parent_candidate_id"],
        candidate_id=policy["candidate_id"], generation=policy["generation"],
        decision=("retain_candidate" if retained else "reject_candidate") if sufficient else "insufficient",
        cohorts=stats, lifecycle_utility_cost=lifecycle, amortized_utility_cost=amortized,
        observed_pairs=len(pairs), confidence=policy["confidence"],
        simultaneous_bounds=["all.net_utility_lower", "new.net_utility_lower", "old.success_gain_lower"],
        estimand="equal_source_group_mean_with_observed_case_amortization",
        independent_source_groups_declared=independent_source_groups_declared,
        provenance_verified=False, preregistration_time_verified=False, execution_authority=False)
