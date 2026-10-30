"""Paired, source/seed-aware research gates; never a global-NDU certificate.

The registered objective is the finite-horizon, gamma=2 population entropic
certainty equivalent. Bootstrap intervals are approximate, not finite-sample
coverage guarantees. Hashes bind supplied records; they cannot authenticate a
measurement or prove that somebody did not inspect held-out data elsewhere.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random


SCHEMA = "hepta.joint-generation.research-gate.v2"
ARMS = ["ordinary_fixed_mean", "ordinary_dynamic_mean", "hepta_fixed_mean",
        "hepta_dynamic_mean", "hepta_dynamic_risk",
        "hepta_dynamic_risk_actor_only", "ordinary_dynamic_risk", "hepta_fixed_risk"]
LIFECYCLE_COMPONENTS = {"common_training", "candidate_training", "candidate_selection",
                        "distillation", "startup", "model_loading"}
KNOWN_NAMESPACES = {"train", "development", "test", "controller-v2-train",
                    "controller-v2-development", "controller-v2-distillation"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def default_plan(stage="development"):
    """A template to freeze BEFORE its evaluation; not an executed registration."""
    if stage not in {"development", "confirmation"}:
        raise ValueError("Unknown research stage")
    return {
        "schema": SCHEMA, "stage": stage, "gamma": 2.0,
        "estimand": "mean_training_seed_effect_of_per_seed_population_CE",
        "source_namespace": ("controller-v2-development" if stage == "development"
                             else "joint-confirmation-v2-20261030-v1"),
        "historical_namespaces": sorted(KNOWN_NAMESPACES),
        "historical_training_seeds": [17, 29, 43],
        "source_identity_law": "SHA256(joint-mechanism-v1:{namespace}:{source})",
        "source_ids": list(range(32 if stage == "development" else 64)),
        "seeds": [17, 29] if stage == "development" else [101, 211, 307],
        "widths": [32, 64], "arms": list(ARMS), "draws_per_source": 2,
        "comparisons": [
            {"id": "risk", "left": "hepta_dynamic_risk", "right": "hepta_dynamic_mean",
             "metric": "net_ce", "threshold": 0.0},
            {"id": "allocation", "left": "hepta_dynamic_risk", "right": "hepta_fixed_risk",
             "metric": "net_ce", "threshold": 0.0},
            {"id": "operator", "left": "hepta_dynamic_risk", "right": "ordinary_dynamic_risk",
             "metric": "net_ce", "threshold": 0.0},
            {"id": "joint_training", "left": "hepta_dynamic_risk", "right": "hepta_dynamic_risk_actor_only",
             "metric": "net_ce", "threshold": 0.0},
        ],
        "alpha": 0.05, "bootstrap_replicates": 4000, "bootstrap_seed": 641729,
        "require_each_seed_positive": True,
        "amortization_episodes": 10000,
        "cost_scope": ("serving_including_audit_close" if stage == "development"
                       else "full_lifecycle"),
        "failure_utility": -1.0,
    }


def distillation_plan(stage="development"):
    """Development margins are this study's design choices, not field standards."""
    plan = default_plan(stage)
    plan["arms"] = ["hepta_teacher", "hepta_student"]
    plan["comparisons"] = [
        {"id": "student_quality_noninferiority", "left": "hepta_student", "right": "hepta_teacher",
         "metric": "utility_ce", "threshold": -0.005},
        {"id": "student_net_noninferiority", "left": "hepta_student", "right": "hepta_teacher",
         "metric": "net_ce", "threshold": -0.005 if stage == "development" else 0.0},
        {"id": "student_cost_saving", "left": "hepta_student", "right": "hepta_teacher",
         "metric": "cost_saving", "threshold": 0.0},
    ]
    return plan


def _number(value, name, *, nonnegative=False):
    if type(value) not in (float, int) or not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(f"{name} must be finite" + (" and nonnegative" if nonnegative else ""))
    return float(value)


def _unique(values, name, *, integer=False):
    if not isinstance(values, list) or not values or len(set(values)) != len(values):
        raise ValueError(f"{name} must be a nonempty unique list")
    if integer and any(type(v) is not int or v < 0 for v in values):
        raise ValueError(f"{name} must contain nonnegative integers")


def validate_plan(plan):
    if set(plan) != set(default_plan()) or plan["schema"] != SCHEMA:
        raise ValueError("Unknown or missing registration fields")
    if plan["stage"] not in {"development", "confirmation"} or plan["gamma"] != 2.0:
        raise ValueError("Only the declared finite-horizon gamma=2 objective is supported")
    if plan["estimand"] != default_plan()["estimand"]:
        raise ValueError("Training randomness cannot silently change the population objective")
    for name in ("source_ids", "seeds", "widths", "historical_training_seeds"):
        _unique(plan[name], name, integer=True)
    if any(width < 1 for width in plan["widths"]):
        raise ValueError("Model widths must be positive")
    if len(plan["seeds"]) < 2 or len(plan["source_ids"]) < 2:
        raise ValueError("Crossed source/seed analysis requires at least two of each")
    for name in ("arms", "historical_namespaces"):
        _unique(plan[name], name)
        if any(not isinstance(v, str) or not v for v in plan[name]):
            raise ValueError(f"{name} must contain nonempty names")
    namespace = plan["source_namespace"]
    if not isinstance(namespace, str) or not namespace or ":" in namespace:
        raise ValueError("An unambiguous source namespace is required")
    if (plan["stage"] == "confirmation"
            and namespace in KNOWN_NAMESPACES.union(plan["historical_namespaces"])):
        raise ValueError("Confirmation cannot reuse an already inspected namespace")
    if not KNOWN_NAMESPACES.issubset(plan["historical_namespaces"]):
        raise ValueError("Known historical source roles cannot be removed")
    if not {17, 29, 43}.issubset(plan["historical_training_seeds"]):
        raise ValueError("Known historical training seeds cannot be removed")
    if (plan["stage"] == "confirmation"
            and set(plan["seeds"]).intersection(plan["historical_training_seeds"])):
        raise ValueError("Confirmation must use previously unused training seeds")
    if plan["source_identity_law"] != default_plan()["source_identity_law"]:
        raise ValueError("Changing names cannot silently change the source identity law")
    for name in ("draws_per_source", "bootstrap_replicates", "amortization_episodes"):
        if type(plan[name]) is not int or plan[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    if type(plan["bootstrap_seed"]) is not int or type(plan["require_each_seed_positive"]) is not bool:
        raise ValueError("Explicit bootstrap seed and replication requirement are required")
    if not 0 < _number(plan["alpha"], "alpha") < 1:
        raise ValueError("alpha must be in (0,1)")
    _number(plan["failure_utility"], "failure utility")
    if plan["cost_scope"] not in {"serving_including_audit_close", "full_lifecycle"}:
        raise ValueError("Unknown cost boundary")
    if plan["stage"] == "confirmation" and plan["cost_scope"] != "full_lifecycle":
        raise ValueError("Confirmation requires complete lifecycle costs")
    comparisons = plan["comparisons"]
    if not isinstance(comparisons, list) or not comparisons:
        raise ValueError("Comparisons must be fixed before evaluation")
    ids = []
    for item in comparisons:
        if set(item) != {"id", "left", "right", "metric", "threshold"}:
            raise ValueError("Unknown or incomplete comparison")
        if (item["left"] not in plan["arms"] or item["right"] not in plan["arms"]
                or item["left"] == item["right"]):
            raise ValueError("Comparison arms must be distinct registered candidates")
        if item["metric"] not in {"net_ce", "utility_ce", "cost_saving"}:
            raise ValueError("Unknown comparison metric")
        _number(item["threshold"], "comparison threshold")
        if not isinstance(item["id"], str) or not item["id"]:
            raise ValueError("Comparison identity is required")
        ids.append(item["id"])
    _unique(ids, "comparison identifiers")
    return plan


def seal_plan(plan, path):
    """Create once. Publishing this seal before evaluation is an external step."""
    validate_plan(plan)
    envelope = {"schema": SCHEMA + ".seal", "plan_sha256": digest(plan), "plan": plan}
    with Path(path).open("x") as handle:
        handle.write(json.dumps(envelope, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return envelope


def read_seal(path):
    value = json.loads(Path(path).read_text())
    if (set(value) != {"schema", "plan_sha256", "plan"}
            or value["schema"] != SCHEMA + ".seal"
            or digest(value["plan"]) != value["plan_sha256"]):
        raise ValueError("Registration seal has changed")
    validate_plan(value["plan"])
    return value


def _lifecycle(plan, costs):
    keys = {f"{seed}:{width}:{arm}" for seed in plan["seeds"]
            for width in plan["widths"] for arm in plan["arms"]}
    if costs is None:
        if plan["cost_scope"] == "full_lifecycle":
            raise ValueError("Full lifecycle cost ledger is absent")
        return {key: 0.0 for key in keys}
    if set(costs) != keys:
        raise ValueError("Lifecycle cost ledger must cover every seed/width/arm exactly")
    result = {}
    for key, ledger in costs.items():
        if set(ledger) != LIFECYCLE_COMPONENTS:
            raise ValueError("Lifecycle cost components are missing or unknown")
        result[key] = sum(_number(v, "lifecycle cost", nonnegative=True) for v in ledger.values())
    return result


def _panel(plan, rows, overhead):
    expected = {(width, seed, source, draw, arm) for width in plan["widths"]
                for seed in plan["seeds"] for source in plan["source_ids"]
                for draw in range(plan["draws_per_source"]) for arm in plan["arms"]}
    panel, profiles = {}, set()
    failures = Counter()
    for row in rows:
        required = {"width", "seed", "source", "draw", "arm", "source_namespace",
                    "net_with_audit_close", "utility", "failure", "profile_sha256"}
        if not required.issubset(row):
            raise ValueError("A measured trajectory row is incomplete")
        if any(type(row[k]) is not int for k in ("width", "seed", "source", "draw")):
            raise ValueError("Trajectory panel indices must be exact integers")
        key = tuple(row[k] for k in ("width", "seed", "source", "draw", "arm"))
        if key not in expected or key in panel or row["source_namespace"] != plan["source_namespace"]:
            raise ValueError("Duplicate, unexpected or wrong-namespace trajectory")
        utility = _number(row["utility"], "delivered utility")
        serving_net = _number(row["net_with_audit_close"], "audit-inclusive return")
        serving_cost = utility - serving_net
        if serving_cost < -1e-10:
            raise ValueError("Serving cost cannot be negative")
        if row["failure"] is not None:
            failures[row["arm"]] += 1
            if utility != plan["failure_utility"]:
                raise ValueError("Failed trajectories must retain the registered failure utility")
        profile = row["profile_sha256"]
        if not isinstance(profile, str) or len(profile) != 64 or any(c not in "0123456789abcdef" for c in profile):
            raise ValueError("An exact profile identity is required")
        profiles.add(profile)
        cost = serving_cost
        if plan["cost_scope"] == "full_lifecycle":
            cost += overhead[f"{row['seed']}:{row['width']}:{row['arm']}"] / plan["amortization_episodes"]
        try:
            panel[key] = (math.exp(-2 * (utility - cost)), math.exp(-2 * utility), cost)
        except OverflowError as exc:
            raise ValueError("Unclipped moment exceeds supported numeric range") from exc
        if not all(math.isfinite(v) for v in panel[key]):
            raise ValueError("Nonfinite measured moment")
    if set(panel) != expected or len(profiles) != 1:
        raise ValueError("Incomplete paired panel or inconsistent generation profile")
    return panel, dict(failures), next(iter(profiles))


def _quantile(sorted_values, q):
    position = (len(sorted_values) - 1) * q
    lo = math.floor(position)
    hi = math.ceil(position)
    return sorted_values[lo] * (hi - position) + sorted_values[hi] * (position - lo) if hi != lo else sorted_values[lo]


def analyse_panel(plan, rows, lifecycle_costs=None):
    """Validate complete pairing, then resample crossed seed and source clusters.

    Sources are resampled ONCE per replicate and shared across all seeds, arms
    and widths; seeds are independently resampled and likewise shared. Draws
    stay in their source/seed cell. Thus reused sources are not miscounted as
    independent seed-level replications. A seed pool of two or three remains
    a weak estimate of training variability, explicitly reported below.
    """
    validate_plan(plan)
    overhead = _lifecycle(plan, lifecycle_costs)
    panel, failures, profile = _panel(plan, rows, overhead)
    draws = plan["draws_per_source"]
    cells = {key: tuple(sum(panel[(*key[:3], draw, key[3])][m] for draw in range(draws)) / draws
                        for m in range(3))
             for key in {(w, s, src, arm) for w, s, src, _, arm in panel}}
    family = len(plan["comparisons"]) * len(plan["widths"])
    tail = plan["alpha"] / (2 * family)
    enough_resamples = plan["bootstrap_replicates"] * tail >= 10
    rng = random.Random(plan["bootstrap_seed"])

    def aggregate(width, seed_weights, source_weights):
        source_count, seed_count = sum(source_weights.values()), sum(seed_weights.values())
        result = {}
        for arm in plan["arms"]:
            totals = [0.0, 0.0, 0.0]
            for seed, n_seed in seed_weights.items():
                conditional = [0.0, 0.0, 0.0]
                for source, n_source in source_weights.items():
                    values = cells[(width, seed, source, arm)]
                    for metric in range(3):
                        conditional[metric] += n_source * values[metric]
                totals[0] += n_seed * (-math.log(conditional[0] / source_count) / 2)
                totals[1] += n_seed * (-math.log(conditional[1] / source_count) / 2)
                totals[2] += n_seed * conditional[2] / source_count
            result[arm] = tuple(value / seed_count for value in totals)
        return result

    def difference(values, comparison):
        metric = {"net_ce": 0, "utility_ce": 1, "cost_saving": 2}[comparison["metric"]]
        left, right = values[comparison["left"]][metric], values[comparison["right"]][metric]
        return right - left if metric == 2 else left - right

    seeds = Counter({seed: 1 for seed in plan["seeds"]})
    sources = Counter({source: 1 for source in plan["source_ids"]})
    point = {w: aggregate(w, seeds, sources) for w in plan["widths"]}
    samples = {(w, c["id"]): [] for w in plan["widths"] for c in plan["comparisons"]}
    for _ in range(plan["bootstrap_replicates"]):
        sampled_seeds = Counter(rng.choices(plan["seeds"], k=len(seeds)))
        sampled_sources = Counter(rng.choices(plan["source_ids"], k=len(sources)))
        for width in plan["widths"]:
            values = aggregate(width, sampled_seeds, sampled_sources)
            for comparison in plan["comparisons"]:
                samples[(width, comparison["id"])].append(difference(values, comparison))
    effects = []
    for width in plan["widths"]:
        for comparison in plan["comparisons"]:
            values = sorted(samples[(width, comparison["id"])])
            interval = [_quantile(values, tail), _quantile(values, 1-tail)]
            seed_effects = {str(seed): difference(aggregate(width, {seed: 1}, sources), comparison)
                            for seed in seeds}
            seed_pass = all(v > comparison["threshold"] for v in seed_effects.values())
            effects.append({**comparison, "width": width,
                            "difference": difference(point[width], comparison),
                            "unadjusted_interval": [_quantile(values, plan["alpha"]/2),
                                                    _quantile(values, 1-plan["alpha"]/2)],
                            "bonferroni_interval": interval, "per_seed_difference": seed_effects,
                            "passed": bool(enough_resamples and interval[0] > comparison["threshold"]
                                           and (seed_pass or not plan["require_each_seed_positive"]))})
    passed = all(item["passed"] for item in effects)
    return {"schema": SCHEMA + ".result", "plan_sha256": digest(plan), "stage": plan["stage"],
            "profile_sha256": profile, "rows": len(rows), "rows_sha256": digest(rows),
            "source_namespace": plan["source_namespace"], "estimand": plan["estimand"],
            "panel_complete": True,
            "source_count": len(sources), "training_seed_count": len(seeds),
            "failures_by_arm": failures, "effects": effects, "all_required_comparisons_pass": passed,
            "development_admission_pass": plan["stage"] == "development" and passed,
            "research_qualified": plan["stage"] == "confirmation" and passed,
            "natural_semantic_qualified": False, "global_NDU_optimality_proved": False,
            "cost_scope": plan["cost_scope"], "lifecycle_costs_sha256": digest(lifecycle_costs),
            "bootstrap": {"method": "crossed_paired_seed_source_percentile", "family_size": family,
                          "replicates": plan["bootstrap_replicates"], "alpha": plan["alpha"],
                          "adequate_tail_resamples": enough_resamples,
                          "familywise_adjustment": "Bonferroni nominal; bootstrap coverage is approximate"},
            "limits": ["few training seeds limit population inference", "CE plug-in has finite-sample bias",
                       "cost measurement authenticity requires independent trajectory audit",
                       "claims concern this registered task and scales only"]}


def claim_confirmation(sealed_plan, development_report, candidate_hashes, marker,
                       *, sealed_development_plan):
    """Fail closed before source generation; one claim, even after a failed run.

    The caller must externally publish the plan, development report, and model
    hashes before this call. This local guard is not a trusted timestamp service.
    """
    seal = read_seal(sealed_plan)
    plan = seal["plan"]
    development_seal = read_seal(sealed_development_plan)
    development_plan = development_seal["plan"]
    if (plan["stage"] != "confirmation" or development_report.get("schema") != SCHEMA + ".result"
            or development_report.get("stage") != "development"
            or development_report.get("development_admission_pass") is not True
            or development_report.get("panel_complete") is not True
            or development_report.get("plan_sha256") != development_seal["plan_sha256"]
            or development_plan["stage"] != "development"):
        raise ValueError("A complete passing development gate is required before confirmation")
    for field in ("arms", "widths", "gamma", "estimand", "amortization_episodes"):
        if plan[field] != development_plan[field]:
            raise ValueError("Confirmation cannot silently change the selected comparison family")
    dev_comparisons = {item["id"]: item for item in development_plan["comparisons"]}
    if {item["id"] for item in plan["comparisons"]} != set(dev_comparisons):
        raise ValueError("Confirmation comparison identities must match development")
    for item in plan["comparisons"]:
        old = dev_comparisons[item["id"]]
        if (any(item[field] != old[field] for field in ("left", "right", "metric"))
                or item["threshold"] < old["threshold"]):
            raise ValueError("Confirmation may tighten, but never relax, the selected thresholds")
    if (development_plan["source_namespace"] not in plan["historical_namespaces"]
            or set(development_plan["seeds"]).intersection(plan["seeds"])):
        raise ValueError("Confirmation requires new training seeds and excludes development sources")
    expected = {f"{seed}:{width}:{arm}" for seed in plan["seeds"]
                for width in plan["widths"] for arm in plan["arms"]}
    if set(candidate_hashes) != expected or any(not isinstance(v, str) or len(v) != 64
            or any(c not in "0123456789abcdef" for c in v) for v in candidate_hashes.values()):
        raise ValueError("Every selected candidate must have an immutable SHA-256")
    receipt = {"schema": SCHEMA + ".consumption-claim", "plan_sha256": seal["plan_sha256"],
               "development_report_sha256": digest(development_report),
               "candidate_hashes": candidate_hashes, "source_namespace": plan["source_namespace"],
               "status": "claimed_before_source_access; failure_does_not_restore_freshness"}
    with Path(marker).open("x") as handle:
        handle.write(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, help="Previously sealed JSON registration")
    parser.add_argument("--rows", required=True, help="JSON list of actual compact episode rows")
    parser.add_argument("--lifecycle-costs")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plan = read_seal(args.plan)["plan"]
    costs = json.loads(Path(args.lifecycle_costs).read_text()) if args.lifecycle_costs else None
    result = analyse_panel(plan, json.loads(Path(args.rows).read_text()), costs)
    with Path(args.output).open("x") as handle:
        handle.write(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
