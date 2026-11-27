"""Fail-closed, paired source-cluster confirmatory statistics for a *new* NDU v2 run.

This consumes independently scored results and measured cost receipts; it does NOT
re-score images, attest generator provenance, or authorize a model promotion.
The registration SHA256 must have been anchored *before* evaluating the holdout.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import re

from cohort_firewall import check_cohort


METHODS = (
    "base", "static_cells", "learned_router", "best_of_n", "mean_only",
    "risk_actor_critic", "ndu", "ablate_covariance", "ablate_semantic",
    "ablate_horizontal", "ablate_vertical", "ablate_completion",
)
COST_KEYS = ("encoder", "backbone", "cell", "controller", "critic",
             "verifier", "render", "communication")
COMPARATORS = ("best_of_n", "mean_only")
CELL_ABLATIONS = ("ablate_semantic", "ablate_horizontal", "ablate_vertical", "ablate_completion")
HEX256 = re.compile(r"^[0-9a-f]{64}$")


class ConfirmatoryError(ValueError):
    """Input fails a registered protocol or completeness requirement."""


def require(condition, message):
    if not condition:
        raise ConfirmatoryError(message)


def number(value, name, lo=None, hi=None):
    require(type(value) in (float, int) and math.isfinite(value), f"{name}: finite number required")
    require(lo is None or value >= lo, f"{name}: below minimum")
    require(hi is None or value <= hi, f"{name}: above maximum")
    return float(value)


def fractional_cvar(losses, alpha):
    require(len(losses) > 0, "CVaR requires outcomes")
    ordered = sorted(losses, reverse=True)
    mass = (1 - alpha) * len(ordered)
    full = int(mass)
    return (sum(ordered[:full]) + (mass - full) * ordered[full]) / mass


def percentile(samples, fraction):
    ordered = sorted(samples)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] * (1 - (index - low)) + ordered[high] * (index - low)


def registration_check(registration, candidate, history, manifest_digest, *, minimum_sources=128,
                       minimum_bootstraps=2000):
    require(type(registration) is dict and registration.get("schema") == "hepta.ndu-confirmatory-registration.v2", "unknown preregistration schema")
    require(registration.get("methods") == list(METHODS), "comparison/ablation roster not frozen")
    seeds = registration.get("seeds")
    require(type(seeds) is list and len(seeds) >= 3 and
            all(type(seed) is int and 0 <= seed < 2**31 for seed in seeds)
            and len(set(seeds)) == len(seeds), "at least three distinct decoding seeds required")
    source_count = registration.get("test_sources")
    require(type(source_count) is int and source_count >= minimum_sources, "new original-image count below protocol minimum")
    require(registration.get("alpha") == 0.05 and registration.get("cvar_alpha") == 0.9,
            "familywise alpha or CVaR definition differs from registered design")
    n_boot = registration.get("bootstrap_samples")
    require(type(n_boot) is int and n_boot >= minimum_bootstraps, "insufficient paired bootstrap replicates")
    require(type(registration.get("bootstrap_seed")) is int, "bootstrap seed missing")
    require(number(registration.get("selected_dev_risk_weight"), "selected dev lambda") > 0,
            "dev-selected risk weight must be nonzero for covariance effect identification")
    margins = registration.get("margins")
    require(type(margins) is dict and set(margins) ==
            {"quality_gain", "cvar_delta", "severe_delta", "wall_ratio", "coverage_delta", "covariance_cvar_gain", "cell_quality_gain"},
            "required effect/noninferiority margins must be registered")
    for key in margins:
        number(margins[key], key)
    require(0 < margins["quality_gain"] <= 0.1 and -0.1 <= margins["cvar_delta"] <= 0.1
            and 0 <= margins["severe_delta"] <= 0.1
            and 1 <= margins["wall_ratio"] <= 1.2
            and -0.1 <= margins["coverage_delta"] <= 0
            and 0 < margins["covariance_cvar_gain"] <= 0.1
            and 0 <= margins["cell_quality_gain"] <= 0.1,
            "invalid registered directional margins")
    require(type(registration.get("cohort_manifest_sha256")) is str
            and HEX256.fullmatch(registration["cohort_manifest_sha256"])
            and registration["cohort_manifest_sha256"] == manifest_digest,
            "candidate manifest does not match preregistered SHA256")
    firewall = check_cohort(candidate, history)
    require(firewall["status"] == "pass" and firewall["observable_image_identity_disjoint"],
            "candidate cohort did not pass source firewall")
    test_sources = candidate["splits"]["test"]["sources"]
    require(len(test_sources) == source_count, "registered test count differs from manifest")
    test_ids = [item["source_id"] for item in test_sources]
    require(len(set(test_ids)) == source_count, "repeated source in test manifest")
    return seeds, set(test_ids), n_boot, margins, firewall


def episode_roster(episodes, seeds, test_source_ids, *, minimum_decisions=8, maximum_decisions=16):
    require(type(episodes) is list and episodes, "full episode journal required")
    roster = defaultdict(dict)
    source_seeds = defaultdict(set)
    for row in episodes:
        require(type(row) is dict, "invalid episode row")
        require(set(row) == {"source_id", "seed", "method", "quality", "coverage", "severe",
                             "wall_seconds", "control_checkpoints", "cost_parts"},
                "missing/unregistered episode fields")
        source = row["source_id"]
        seed, method = row["seed"], row["method"]
        require(type(source) is str and source in test_source_ids, "unregistered test source ID")
        require(type(seed) is int and seed in seeds, "episode with unregistered seed")
        require(type(method) is str and method in METHODS, "episode with unregistered method")
        require(method not in roster[(source, seed)], "duplicate episode method/source/seed")
        quality = number(row["quality"], "quality", 0, 1)
        wall = number(row["wall_seconds"], "wall_seconds", 0)
        require(wall > 0, "measured wall time must be positive")
        require(type(row["coverage"]) is int and row["coverage"] in (0, 1)
                and type(row["severe"]) is int and row["severe"] in (0, 1),
                "coverage/severe indicators must be binary, not booleans")
        if row["coverage"] == 0:
            require(quality == 0 and row["severe"] == 1,
                    "failed/incomplete/over-budget episodes must retain zero quality and severe loss")
        require(type(row["control_checkpoints"]) is int and row["control_checkpoints"] >= 0,
                "actual executed checkpoint count required")
        parts = row["cost_parts"]
        require(type(parts) is dict and set(parts) == set(COST_KEYS),
                "complete exclusive cost component receipt required")
        accounted = sum(number(parts[k], f"cost.{k}", 0) for k in COST_KEYS)
        require(accounted <= wall + 1e-6, "exclusive cost components exceed actual measured wall")
        if method == "ndu" and row["coverage"] == 1:
            require(minimum_decisions <= row["control_checkpoints"] <= maximum_decisions,
                    "successful NDU episode did not execute 8-16 actual decisions")
        roster[(source, seed)][method] = row
        source_seeds[source].add(seed)
    require(set(source_seeds) == test_source_ids, "test image roster is incomplete")
    require(len(roster) == len(test_source_ids) * len(seeds), "missing source/seed blocks")
    require(all(found == set(seeds) for found in source_seeds.values()),
            "incomplete seed blocks for one or more original images")
    require(all(set(block) == set(METHODS) for block in roster.values()),
            "missing same-image/same-seed comparison or ablation arms")
    require(len(episodes) == len(test_source_ids) * len(seeds) * len(METHODS),
            "full preregistered episode denominator required")
    return roster


def aggregate(roster, sampled_sources, seeds, method, alpha):
    rows = [roster[(source, seed)][method] for source in sampled_sources for seed in seeds]
    n = len(rows)
    return {"quality": sum(row["quality"] for row in rows) / n,
            "cvar": fractional_cvar([1 - row["quality"] for row in rows], alpha),
            "severe": sum(row["severe"] for row in rows) / n,
            "coverage": sum(row["coverage"] for row in rows) / n,
            "wall": sum(row["wall_seconds"] for row in rows) / n}


def effects(roster, sources, seeds, alpha):
    points = {method: aggregate(roster, sources, seeds, method, alpha) for method in METHODS}
    primary = points["ndu"]
    comparisons = {}
    for other in COMPARATORS:
        b = points[other]
        comparisons[other] = {"quality_gain": primary["quality"] - b["quality"],
                              "cvar_delta": primary["cvar"] - b["cvar"],
                              "severe_delta": primary["severe"] - b["severe"],
                              "wall_ratio": primary["wall"] / b["wall"],
                              "coverage_delta": primary["coverage"] - b["coverage"]}
    comparisons["ablate_covariance"] = {
        "covariance_cvar_gain": points["ablate_covariance"]["cvar"] - primary["cvar"],
    }
    for cell in CELL_ABLATIONS:
        comparisons[cell] = {"cell_quality_gain": primary["quality"] - points[cell]["quality"]}
    return points, comparisons


def assess(registration, candidate, history, manifest_digest, episodes, *,
           minimum_sources=128, minimum_bootstraps=2000):
    seeds, test_source_ids, bootstraps, margins, firewall = registration_check(
        registration, candidate, history, manifest_digest,
        minimum_sources=minimum_sources, minimum_bootstraps=minimum_bootstraps)
    roster = episode_roster(episodes, seeds, test_source_ids)
    sources = sorted({source for source, _ in roster})
    points, observed = effects(roster, sources, seeds, registration["cvar_alpha"])
    rng = random.Random(registration["bootstrap_seed"])
    sampled = {method: {metric: [] for metric in metrics} for method, metrics in observed.items()}
    for _ in range(bootstraps):
        draw = rng.choices(sources, k=len(sources))
        _, contrasts = effects(roster, draw, seeds, registration["cvar_alpha"])
        for method, metrics in contrasts.items():
            for metric, value in metrics.items():
                sampled[method][metric].append(value)
    # Familywise Bonferroni correction across all preregistered contrasts:
    # two primary comparators * five metrics + risk ablation + four Cells.
    family_size = sum(len(metrics) for metrics in observed.values())
    tail = registration["alpha"] / (2 * family_size)
    thresholds = {
        "quality_gain": ("lower", margins["quality_gain"]),
        "cvar_delta": ("upper", margins["cvar_delta"]),
        "severe_delta": ("upper", margins["severe_delta"]),
        "wall_ratio": ("upper", margins["wall_ratio"]),
        "coverage_delta": ("lower", margins["coverage_delta"]),
        "covariance_cvar_gain": ("lower", margins["covariance_cvar_gain"]),
        "cell_quality_gain": ("lower", margins["cell_quality_gain"]),
    }
    intervals, all_contrasts_pass = {}, True
    for method, metrics in observed.items():
        intervals[method] = {}
        for name, estimate in metrics.items():
            lo, hi = percentile(sampled[method][name], tail), percentile(sampled[method][name], 1 - tail)
            bound, target = thresholds[name]
            passes = lo > target if bound == "lower" else hi <= target
            intervals[method][name] = {"estimate": estimate, "lower": lo,
                                       "upper": hi, "required_bound": bound,
                                       "registered_margin": target, "pass": passes}
            all_contrasts_pass &= passes
    return {
        "schema": "hepta.ndu-confirmatory-statistics.v2",
        "status": "statistical_thresholds_met" if all_contrasts_pass else "scientific_thresholds_not_met",
        "all_preregistered_statistical_contrasts_pass": all_contrasts_pass,
        "candidate_manifest_sha256": manifest_digest,
        "cohort_firewall_status": firewall["status"],
        "new_source_blocks": len(sources), "independent_source_clusters": len(sources),
        "decoding_seeds": seeds, "full_episode_denominator": len(episodes),
        "simultaneous_method": "source-cluster paired bootstrap; Bonferroni familywise two-sided percentile intervals",
        "familywise_alpha": registration["alpha"], "family_size": family_size,
        "bootstrap_resamples": bootstraps, "interval_quantiles": [tail, 1-tail],
        "points": points, "contrasts": intervals,
        "cost_scope": "actual wall seconds (including failed work); exclusive component upper-bound verified",
        "attestation_scope": "supplied score and cost receipts are checked internally, not independently re-scored or authenticated",
        "external_preregistration_timestamp_verified": False,
        "independent_language_and_pixel_generation_verified": False,
        "terminal_covariance_estimator_verified": False,
        "continuous_fbsde_or_merton_optimality_verified": False,
        "model_promotion_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--registered-sha256", required=True,
                        help="out-of-band SHA256 previously anchored before test outcomes")
    parser.add_argument("--cohort-manifest", type=Path, required=True)
    parser.add_argument("--historical", action="append", type=Path, required=True)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(bool(HEX256.fullmatch(args.registered_sha256)), "registration SHA256 must be lowercase hex")
        raw = args.registration.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == args.registered_sha256,
                "registration does not match externally anchored SHA256")
        registration = json.loads(raw)
        candidate_raw = args.cohort_manifest.read_bytes()
        candidate = json.loads(candidate_raw)
        history = [json.loads(path.read_bytes()) for path in args.historical]
        episodes = [json.loads(line) for line in args.episodes.read_text().splitlines() if line.strip()]
        outcome = assess(registration, candidate, history, hashlib.sha256(candidate_raw).hexdigest(), episodes)
        outcome["registered_sha256"] = args.registered_sha256
        code = 0 if outcome["all_preregistered_statistical_contrasts_pass"] else 2
    except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError) as err:
        outcome = {"schema": "hepta.ndu-confirmatory-statistics.v2",
                   "status": "invalid_or_incomplete_evidence", "error": str(err),
                   "all_preregistered_statistical_contrasts_pass": False,
                   "model_promotion_authorized": False}
        code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(outcome, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": outcome["status"],
                      "all_preregistered_statistical_contrasts_pass": outcome["all_preregistered_statistical_contrasts_pass"]}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
