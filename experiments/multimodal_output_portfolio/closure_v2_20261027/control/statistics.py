"""Paired source-level inference and explicit forecast/calibration failures."""

import math

import numpy as np

from .protocol import PROTOCOL as P


def ce(values):
    return -math.log(float(np.exp(-P["gamma"] * np.asarray(values)).mean())) / P["gamma"]


def ece(probabilities, outcomes):
    p, y = np.asarray(probabilities), np.asarray(outcomes)
    result = 0.0
    for i in range(10):
        selected = (p >= i / 10) & (p < (i + 1) / 10 if i < 9 else p <= 1)
        if selected.any():
            result += selected.mean() * abs(p[selected].mean() - y[selected].mean())
    return float(result)


def analyze(rows):
    grouped = {arm: sorted([r for r in rows if r["arm"] == arm], key=lambda r: r["index"]) for arm in P["arms"]}
    if any([r["index"] for r in group] != list(range(P["qualification_pairs"])) for group in grouped.values()):
        raise ValueError("Qualification arm/source grid is incomplete or duplicated")
    summaries = {}
    for arm, group in grouped.items():
        summaries[arm] = {"episodes": len(group), "strict_success": float(np.mean([r["final_score"]["strict_success"] for r in group])),
            "mean_net_utility": float(np.mean([r["net_utility"] for r in group])),
            "ce": ce([r["net_utility"] for r in group]), "actual_corrections": sum(r["admitted"] for r in group),
            "denied_proposals": sum(r["denied"] for r in group), "mean_task_charge": float(np.mean([r["task_charge"] for r in group])),
            "mean_python_plus_native_cpu_ms": float(np.mean([r["python_cpu_ns"] / 1e6
                + 1000 * (r["native_child_user_cpu_seconds"] + r["native_child_system_cpu_seconds"]) for r in group])),
            "mean_wall_ms": float(np.mean([r["wall_ns"] / 1e6 for r in group]))}
    comparisons, rng = [], np.random.default_rng(P["bootstrap_seed"])
    for baseline in P["arms"][1:]:
        left, right = grouped["native_numeric"], grouped[baseline]
        a = np.asarray([[r["final_score"]["strict_success"], r["net_utility"]] for r in left])
        b = np.asarray([[r["final_score"]["strict_success"], r["net_utility"]] for r in right])
        bootstrap = []
        for _ in range(P["bootstrap_replicates"]):
            indices = rng.integers(len(left), size=len(left))
            bootstrap.append([*(a[indices] - b[indices]).mean(0), ce(a[indices, 1]) - ce(b[indices, 1])])
        alpha = (1 - P["interval"]) / 2
        intervals = np.quantile(bootstrap, [alpha, 1 - alpha], axis=0)
        comparisons.append({"comparison": "native_numeric-" + baseline,
            "strict_success_difference": float((a[:, 0] - b[:, 0]).mean()), "strict_97_5_interval": intervals[:, 0].tolist(),
            "net_utility_difference": float((a[:, 1] - b[:, 1]).mean()), "net_utility_97_5_interval": intervals[:, 1].tolist(),
            "ce_difference": ce(a[:, 1]) - ce(b[:, 1]), "ce_97_5_interval": intervals[:, 2].tolist(),
            "changed_actions": sum(x["admitted"] != y["admitted"] for x, y in zip(left, right)),
            "changed_final_bundles": sum(x["final"]["sha256"] != y["final"]["sha256"] for x, y in zip(left, right))})
    calibration = {}
    native = grouped["native_numeric"]
    y = np.asarray([r["final_score"]["strict_success"] for r in native])
    for timing in ("before", "after"):
        probability = np.asarray([r[f"prediction_{timing}"]["strict_probability"] for r in native])
        accepted = probability >= P["semantic_acceptance_confidence"]
        false_acceptance = float(np.mean((y == 0) & accepted))
        value = ece(probability, y)
        samples = []
        for _ in range(P["bootstrap_replicates"]):
            ix = rng.integers(len(y), size=len(y))
            samples.append(ece(probability[ix], y[ix]))
        calibration[timing] = {"ece": value, "ece_97_5_interval": np.quantile(samples, [0.0125, 0.9875]).tolist(),
            "brier": float(np.mean((probability - y) ** 2)), "coverage": float(accepted.mean()),
            "false_acceptance_per_all_cases": false_acceptance,
            "error_among_accepted": float(np.mean(y[accepted] == 0)) if accepted.any() else None,
            "strict_point_gate_passed": bool(value <= P["semantic_ece_threshold"]
                and false_acceptance <= P["semantic_false_acceptance_threshold"]
                and accepted.mean() >= P["minimum_semantic_coverage"]),
            "mean_predicted_moment": float(np.mean([r[f"prediction_{timing}"]["moment"] for r in native])),
            "actual_mean_moment": float(np.mean(np.exp(-P["gamma"] * np.asarray([r["net_utility"] for r in native])))),
            "production_qualification": False}
    contrast = comparisons[0]
    return {"schema": "hepta.ndu.semantic-owner-result.v1", "summaries": summaries, "comparisons": comparisons,
        "semantic_gain_gate_passed": contrast["strict_97_5_interval"][0] > 0 and contrast["net_utility_97_5_interval"][0] > 0,
        "actual_alignment_passed": all(r["future_state_matches"] for r in rows),
        "same_information_history_identical": all(a["admitted"] == b["admitted"] and a["final"]["sha256"] == b["final"]["sha256"]
                                                   for a, b in zip(native, grouped["history"])),
        "generic_memory_identical": all(a["admitted"] == b["admitted"] and a["final"]["sha256"] == b["final"]["sha256"]
                                         for a, b in zip(native, grouped["linear_memory"])),
        "semantic_calibration": calibration, "episodes": len(rows),
        "actual_kernel_executions": sum(r["actual_original_kernel_executions"] for r in rows),
        "actual_generator_calls": sum(r["actual_generator_calls"] for r in rows),
        "actual_media_files": sum(r["actual_delivered_files"] for r in rows),
        "independent_statistical_units": P["qualification_pairs"], "writer_population_independence": False,
        "native_owner_in_neural_generation_decision_loop": True,
        "native_kernel_or_generator_parameters_updated_during_qualification": False,
        "end_to_end_owner_generator_gradient": False, "production_qualification": False}
