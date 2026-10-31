"""Fixed paired writer/speaker analysis of actually generated output bundles."""

import math

import numpy as np


def calibration(rows):
    scored = [row for row in rows if row["predicted_strict_success"] is not None]
    if not scored:
        return {"available": False, "reason": "Unchanged mixed renderer has no registered canonical-endpoint confidence law"}
    bins = []
    for lower, upper in zip((0., .5, .8, .95), (.5, .8, .95, 1.000001)):
        group = [row for row in scored if lower <= row["predicted_strict_success"] < upper]
        if group:
            bins.append({"lower": lower, "upper": upper, "count": len(group),
                         "confidence": float(np.mean([r["predicted_strict_success"] for r in group])),
                         "strict_success": float(np.mean([r["strict_success"] for r in group]))})
    return {"available": True, "bins": bins,
            "selected_ECE": sum(b["count"] * abs(b["confidence"] - b["strict_success"]) for b in bins) / len(scored),
            "selected_moment_RMSE": float(np.mean([(r["predicted_entropic_moment"] - math.exp(-2 * r["utility"])) ** 2
                                                  for r in scored]) ** .5),
            "posterior_Brier": float(np.mean([r["posterior_Brier"] for r in scored])),
            "posterior_NLL_finite_mean": float(np.mean([r["posterior_NLL"] for r in scored if r["posterior_NLL"] is not None])),
            "posterior_NLL_infinite_cases": sum(r["posterior_NLL"] is None for r in scored),
            "endpoint_regret": float(np.mean([r["endpoint_regret"] for r in scored])),
            "scope": "Descriptive selected prediction calibration; not the separate native qualification certificate"}


def summarize(rows):
    utility = np.asarray([row["utility"] for row in rows], dtype=np.float64)
    timing = ("input_preparation_wall_ns", "shared_input_encode_wall_ns", "decision_wall_ns", "generation_wall_ns",
              "codec_wall_ns", "generation_verification_wall_ns", "audit_wall_ns", "deployment_wall_ns_charging_full_input")
    return {"actual_bundles": len(rows), "CE": float(-np.log(np.exp(-2 * utility).mean()) / 2),
            "mean_utility": float(utility.mean()),
            "strict_success": float(np.mean([row["strict_success"] for row in rows])),
            "modality_success": {name: float(np.mean([row["modality_success"][name] for row in rows]))
                                 for name in ("text", "image", "audio", "video")},
            "physical_execution_position_counts": {str(position): sum(r["physical_execution_order"] == position for r in rows)
                                                   for position in range(8)},
            "actual_wall_ns": {key: {"mean": float(np.mean([r[key] for r in rows])),
                                     "p50": float(np.quantile([r[key] for r in rows], .5)),
                                     "p95": float(np.quantile([r[key] for r in rows], .95))} for key in timing},
            "calibration": calibration(rows)}


def panel_metrics(arms, names):
    return {key: float(np.mean([arms[name][key] for name in names]))
            for key in ("CE", "mean_utility", "strict_success")}


def analyze(rows, spec):
    names = [arm["name"] for arm in spec["arms"]]
    expected = spec["pair_count"] * len(spec["routes"])
    if len(rows) != expected * len(names) or len({(r["case"], r["route"], r["arm"]) for r in rows}) != len(rows):
        raise ValueError("Actual branch census is incomplete or duplicated")
    grouped = {name: [row for row in rows if row["arm"] == name] for name in names}
    if any(len(group) != expected for group in grouped.values()):
        raise ValueError("An arm lacks a registered actual output")
    arms = {name: summarize(group) for name, group in grouped.items()}
    selected = ["nll-17", "nll-29", "nll-43"]
    failed = ["brier-17", "brier-29", "brier-43"]
    panel = panel_metrics(arms, selected)
    baseline = arms["canonical_no_training"]
    result = {"arms": arms, "selected_NLL_panel": panel,
              "failed_Brier_panel_retained": panel_metrics(arms, failed),
              "by_route": {route: {name: summarize([r for r in group if r["route"] == route])
                                   for name, group in grouped.items()} for route in spec["routes"]},
              "primary_point_difference": {key: panel[key] - baseline[key] for key in panel},
              "mechanism_descriptive_differences": {
                  "canonical_minus_unchanged": {key: baseline[key] - arms["unchanged_full_reference"][key] for key in panel},
                  "NLL_minus_Brier": {key: panel[key] - panel_metrics(arms, failed)[key] for key in panel}},
              "all_additional_contrasts_descriptive": True,
              "binary_endpoint_risk_superiority_identifiable": False}
    clusters = sorted({row["cluster"] for row in rows})
    result["source_cluster_count"] = len(clusters)
    if spec["mode"] == "old_smoke":
        result["primary_gate"] = {"evaluated": False, "reason": "Old-data technical smoke; no independent efficacy inference"}
        return result
    if len(clusters) != 85 or any(sum(r["cluster"] == cluster for r in grouped["canonical_no_training"]) != 8
                                  for cluster in clusters):
        raise ValueError("Expected all eight route/pair tasks inside each of the 85 clusters")
    contrast_arms = ["canonical_no_training", *selected]
    moments, successes = [], []
    for cluster in clusters:
        local = [[r for r in grouped[name] if r["cluster"] == cluster] for name in contrast_arms]
        moments.append([np.mean([math.exp(-2 * r["utility"]) for r in group]) for group in local])
        successes.append([np.mean([r["strict_success"] for r in group]) for group in local])
    generator = np.random.default_rng(spec["bootstrap_seed"])
    indices = generator.integers(0, len(clusters), (spec["bootstrap_replicates"], len(clusters)))
    resampled_ce = -np.log(np.asarray(moments)[indices].mean(axis=1)) / 2
    resampled_strict = np.asarray(successes)[indices].mean(axis=1)
    draws = {"CE": resampled_ce[:, 1:].mean(axis=1) - resampled_ce[:, 0],
             "strict_success": resampled_strict[:, 1:].mean(axis=1) - resampled_strict[:, 0]}
    alpha = spec["familywise_alpha"] / spec["primary_families"]
    intervals = {key: np.quantile(value, (alpha / 2, 1 - alpha / 2)).tolist() for key, value in draws.items()}
    result["primary_gate"] = {"evaluated": True, "interval_confidence": 1 - alpha,
                              "paired_cluster_percentile_intervals": intervals,
                              "CE_superiority": intervals["CE"][0] > 0,
                              "strict_success_noninferiority_margin": 0.,
                              "strict_success_noninferiority": intervals["strict_success"][0] >= 0,
                              "passed": intervals["CE"][0] > 0 and intervals["strict_success"][0] >= 0,
                              "bootstrap_seed": spec["bootstrap_seed"], "bootstrap_replicates": spec["bootstrap_replicates"],
                              "cluster_unit": "Matched image writer and unique speech speaker; routes/pairs/seeds retained together",
                              "scope": "Fixed three-seed panel and fixed generated-task census; not universal model or observer-family generalization"}
    return result
