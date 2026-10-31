"""Complete crossed-source inference and predeclared actual-time price curves."""

import hashlib
import json

import numpy as np

from ...abc_next.settings import MANIFEST
from ...abc_recovery.statistics import (_ce, cost_summary, crossed_bootstrap, loss_tails,
                                        paired_comparison, summarize_utility)
from .serial import POLICIES


PRICES = (0., .0005, .001, .002, .005, .01, .02, .05)
BOOTSTRAP_SEED = 2026102519


def cubes(rows, spec):
    profile = spec["profile"]
    seeds, views = profile["training_seeds"], profile["views"]
    start, count, scenarios = profile["pair_start"], profile["pair_count"], profile["scenarios"]
    shape = len(seeds), count, len(views), scenarios
    names = (*POLICIES, "selected_feedback")
    cells = {name: {metric: np.empty(shape) for metric in ("wall_ms", "cpu_ms", "actions", "complete")}
             for name in names}
    quality = {observer: {name: {metric: np.empty(shape) for metric in ("utility", "success", "loss")}
                          for name in names} for observer in ("primary", "secondary")}
    expected_ids = json.loads(MANIFEST.read_text())["roles"]["test"]["source_ids"]
    selection = {e["seed"]: e["selected_candidate"] for e in spec["controllers"]}
    reference = {e["seed"]: e["selected_nonfeedback"] for e in spec["controllers"]}
    seen, records, failures = set(), {}, []
    for row in rows:
        key = row["seed"], row["case"], row["view"], row["scenario"], row["policy"]
        if (key in seen or row["seed"] not in seeds or not start <= row["case"] < start + count
                or row["view"] not in views or not 0 <= row["scenario"] < scenarios or row["policy"] not in POLICIES):
            raise ValueError("Duplicate or out-of-census request")
        if tuple(row["source_ids"]) != tuple(expected_ids[2 * row["case"]:2 * row["case"] + 2]):
            raise ValueError("Request does not bind registered individual images")
        if row["selected_candidate"] != selection[row["seed"]] or row["selected_nonfeedback"] != reference[row["seed"]]:
            raise ValueError("Post-hoc policy or reference selection")
        seen.add(key); records[key] = row
        if row["status"] != "completed" or set(row.get("observer_scores", {})) != {"primary", "secondary"}:
            failures.append({"identity": key, "status": row["status"], "error": row.get("error")})
            continue
        index = seeds.index(row["seed"]), row["case"] - start, views.index(row["view"]), row["scenario"]
        policy = row["policy"]
        for metric, value in (("wall_ms", row["request_wall_ns"] / 1e6), ("cpu_ms", row["request_cpu_ns"] / 1e6),
                              ("actions", len(row["completed_path"])), ("complete", int(row["required_output_complete"]))):
            if not np.isfinite(value) or value < 0:
                raise ValueError("Invalid measured cost or completion")
            cells[policy][metric][index] = value
        for observer in quality:
            for metric, key_name in (("utility", "utility"), ("success", "joint_fact_correct"), ("loss", "joint_loss")):
                value = row["observer_scores"][observer][key_name]
                if not np.isfinite(value) or (metric == "success" and value not in (0, 1)):
                    raise ValueError("Invalid measured terminal quality")
                quality[observer][policy][metric][index] = value
    expected_count = int(np.prod(shape)) * len(POLICIES)
    if len(seen) != expected_count:
        raise ValueError(f"Incomplete request census: {len(seen)} of {expected_count}")
    if failures:
        return None, None, {"failures": failures, "requests": len(seen), "quality_inference_allowed": False}
    unequal = []
    for key, old in records.items():
        if key[-1] == "old_feedback":
            cached = records[(*key[:-1], "cached_feedback")]
            for field in ("decisions", "completed_path", "output_sha256", "runtime_ledger_sha256"):
                if old[field] != cached[field]:
                    unequal.append({"identity": key[:-1], "field": field})
    for index, seed in enumerate(seeds):
        selected = "compact_feedback" if selection[seed] == "compact" else "cached_feedback"
        for metric in cells[selected]:
            cells["selected_feedback"][metric][index] = cells[selected][metric][index]
        for observer in quality:
            for metric in quality[observer][selected]:
                quality[observer]["selected_feedback"][metric][index] = quality[observer][selected][metric][index]
    return cells, quality, {"requests": len(seen), "failures": [], "cache_identity_mismatches": unequal,
        "cache_matched_pairs": expected_count // 4, "quality_inference_allowed": not unequal,
        "required_completion": {name: float(cells[name]["complete"].mean()) for name in names}}


def ce_draws(cube, plan):
    source = _ce(cube.reshape(*cube.shape[:2], -1), 2.)
    draws = np.empty(len(plan.seed_indices))
    for start in range(0, len(draws), 128):
        si, ci = plan.seed_indices[start:start + 128, :, None], plan.source_indices[start:start + 128, None, :]
        draws[start:start + len(si)] = _ce(source[si, ci], 2.).mean(-1)
    return draws


def price_curve(candidate, reference, candidate_cost, reference_cost, plan):
    points, draws, records = [], [], []
    for price in PRICES:
        a, b = candidate - price * candidate_cost, reference - price * reference_cost
        point = summarize_utility(a)["joint_ce"] - summarize_utility(b)["joint_ce"]
        distribution = ce_draws(a, plan) - ce_draws(b, plan)
        points.append(point); draws.append(distribution)
        records.append({"utility_per_ms": price, "CE_gain": point,
                        "pointwise_descriptive_95_interval": np.quantile(distribution, [.025, .975]).tolist()})
    centered = np.stack(draws, 1) - np.asarray(points)[None, :]
    radius = float(np.quantile(np.abs(centered).max(1), .95))
    for record in records:
        record["nominal_simultaneous_95_interval_over_frozen_grid"] = [record["CE_gain"] - radius, record["CE_gain"] + radius]
    return {"definition": "CE_gamma2(U - lambda * actual_per_request_cost_ms), computed jointly before risk aggregation",
        "prices_are_sensitivity_parameters_not_user_valuations": True,
        "grid": records, "bootstrap_max_absolute_centered_radius": radius,
        "coverage": "Nominal max-deviation bootstrap band over this frozen 8-price grid; finite-five-seed coverage not guaranteed; no continuum or project-wide guarantee",
        "certified_economic_optimality": False}


def aggregate(rows, spec):
    costs, quality, audit = cubes(rows, spec)
    base = {"schema": "hepta.abc4.control-quality-cost-result.v1", "census": audit,
            "profile": spec["profile"], "inference": spec["inference"]}
    if not audit["quality_inference_allowed"]:
        return {**base, "status": "failed_census_or_cache_identity", "scientific_gates_passed": False}
    plan = crossed_bootstrap(len(spec["profile"]["training_seeds"]), spec["profile"]["pair_count"],
                             replicates=4000, seed=BOOTSTRAP_SEED)
    result = {**base, "status": "complete", "bootstrap_indices_sha256": plan.sha256,
              "quality": {}, "cost": {}, "primary_comparisons": {}, "actual_price_sensitivity": {}}
    for name, cell in costs.items():
        result["cost"][name] = {metric: {"mean": float(values.mean()), "p50": float(np.quantile(values, .5)),
                    "p95": float(np.quantile(values, .95)), "maximum": float(values.max())}
                    for metric, values in cell.items() if metric in {"wall_ms", "cpu_ms"}}
    comparisons = (("selected_feedback", "reference"), ("selected_feedback", "old_feedback"),
                   ("cached_feedback", "old_feedback"), ("compact_feedback", "old_feedback"))
    for candidate, reference in comparisons:
        key = candidate + "_minus_" + reference
        confidence = .975 if candidate == "selected_feedback" else .95
        result["cost"][key] = {metric: cost_summary(costs[candidate][metric], reference=costs[reference][metric],
                                        confidence=confidence, bootstrap=plan)
                                for metric in ("wall_ms", "cpu_ms")}
    for observer, cells in quality.items():
        result["quality"][observer] = {}
        for name, metrics in cells.items():
            result["quality"][observer][name] = {"raw_utility": summarize_utility(metrics["utility"]),
                "proxy_net_utility": summarize_utility(metrics["utility"] - .002 * costs[name]["actions"]),
                "success": float(metrics["success"].mean()), "loss_tails": loss_tails(metrics["loss"]),
                "by_view": {view: {"raw_CE": summarize_utility(metrics["utility"][:, :, v:v + 1])["joint_ce"],
                                   "success": float(metrics["success"][:, :, v].mean()),
                                   "mean_loss": float(metrics["loss"][:, :, v].mean())}
                            for v, view in enumerate(spec["profile"]["views"])}}
        contrasts = {}
        for candidate, reference in comparisons:
            key = candidate + "_minus_" + reference
            confidence = .975 if candidate == "selected_feedback" and observer == "primary" else .95
            contrasts[key] = {"raw_CE": paired_comparison(cells[candidate]["utility"], cells[reference]["utility"],
                                        confidence=confidence, bootstrap=plan),
                              "success": paired_comparison(cells[candidate]["success"], cells[reference]["success"],
                                        estimand="success_rate", confidence=confidence, bootstrap=plan)}
        result["primary_comparisons"][observer] = contrasts
        result["actual_price_sensitivity"][observer] = {metric: price_curve(cells["selected_feedback"]["utility"],
            cells["reference"]["utility"], costs["selected_feedback"][metric], costs["reference"][metric], plan)
            for metric in ("wall_ms", "cpu_ms")}
    first = result["primary_comparisons"]["primary"]["selected_feedback_minus_reference"]
    second = result["primary_comparisons"]["primary"]["selected_feedback_minus_old_feedback"]
    measured = result["cost"]["selected_feedback_minus_old_feedback"]["wall_ms"]
    result["registered_gates"] = {
        "new_feedback_quality_over_strong_nonfeedback": {"raw_CE_lower_positive": first["raw_CE"]["interval"][0] > 0,
            "success_zero_margin_lower_nonnegative": first["success"]["interval"][0] >= 0},
        "efficient_replacement_of_old_feedback": {"raw_CE_loss_within_.005": second["raw_CE"]["interval"][0] >= -.005,
            "success_loss_within_.005": second["success"]["interval"][0] >= -.005,
            "mean_wall_cost_upper_negative": measured["intervals"]["mean"][1] < 0},
        "actual_cost_price_is_user_calibrated": False,
        "all_priced_economic_claims_are_sensitivity_only": True}
    return result
