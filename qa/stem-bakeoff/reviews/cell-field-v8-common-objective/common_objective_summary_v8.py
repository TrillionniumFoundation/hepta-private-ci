"""Descriptive common-J32 attribution; never external-future inference."""

from itertools import product
import numpy as np


PAIRINGS = (("proposal_endpoint", "full32_one_action", "myopic_h1_zero_tail"),
    ("free_action_count", "full32_eight_actions", "full32_one_action"),
    ("loss2_compression", "loss2_32_eight_actions", "full32_eight_actions"),
    ("field_identity", "field32_eight_actions", "full32_eight_actions"))
TIE = 1e-12


def summarize(rows, costs, report):
    by_fit = {}
    for row in rows:
        by_fit.setdefault(row["fit"], {})[row["branch"]] = row
    branches = list(next(iter(by_fit.values())))
    branch_summary = []
    for branch in branches:
        values = [fit[branch] for fit in by_fit.values()]
        zero = [fit["zero32"] for fit in by_fit.values()]
        result = {"branch": branch, "fits": len(values)}
        for key in ("J32", "current_terminal", "old_terminal", "effort", "action_l2",
                    "saturated_coordinate_fraction_in_free_prefix"):
            result["mean_"+key] = float(np.mean([r[key] for r in values]))
        result.update(J32_improved_vs_zero=sum(r["J32"] < b["J32"]-TIE for r, b in zip(values, zero)),
            J32_worsened_vs_zero=sum(r["J32"] > b["J32"]+TIE for r, b in zip(values, zero)),
            current_improved_vs_zero=sum(r["current_terminal"] < b["current_terminal"]-TIE for r, b in zip(values, zero)),
            old_improved_vs_zero=sum(r["old_terminal"] < b["old_terminal"]-TIE for r, b in zip(values, zero)),
            any_old_violation_fits=sum(r["old_violating_steps"] > 0 for r in values),
            violating_physical_steps=sum(r["old_violating_steps"] for r in values),
            terminal_old_violation_fits=sum(r["terminal_maximum_old_excess"] > 0. for r in values),
            mean_J32_change_from_zero=float(np.mean([r["J32"]-b["J32"] for r, b in zip(values, zero)])),
            mean_old_change_from_warmup=float(np.mean([r["old_terminal"]-r["warmup_old_mean"] for r in values])))
        result["prediction_errors_on_identical_actual_actions"] = {model: {
            "root_mean_square_J32_error": float(np.sqrt(np.mean([r["forecasts"][model]["actual_minus_predicted_J32"]**2 for r in values]))),
            "mean_panel_rmse": float(np.mean([r["forecasts"][model]["panel_rmse"] for r in values])),
            "mean_old_panel_rmse": float(np.mean([r["forecasts"][model]["old_panel_rmse"] for r in values])),
            "predicted_J32_improvement_vs_zero": sum(r["forecasts"][model]["predicted_J32"] < b["J32"]-TIE for r, b in zip(values, zero))}
            for model in ("full", "field", "loss2")}
        branch_summary.append(result)
    comparisons, group_rows = [], []
    for kind, target, baseline in PAIRINGS:
        paired = []
        for fit, variants in by_fit.items():
            a, b = variants[target], variants[baseline]
            change = a["J32"]-b["J32"]
            tangent = a["forecasts"]["full"]["predicted_J32"]-b["forecasts"]["full"]["predicted_J32"]
            remainder = a["forecasts"]["full"]["actual_minus_predicted_J32"]-b["forecasts"]["full"]["actual_minus_predicted_J32"]
            if not np.isclose(change, tangent+remainder, atol=1e-13, rtol=0.):
                raise ValueError("matched-action attribution fails algebraic decomposition")
            paired.append({"fit": fit, "version": a["version"], "task": a["task"], "head": a["head"], "seed": a["seed"],
                "actual_J32_difference": change, "full_tangent_J32_difference": tangent,
                "nonlinear_remainder_difference": remainder,
                "current_risk_difference": a["current_terminal"]-b["current_terminal"],
                "old_risk_difference": a["old_terminal"]-b["old_terminal"],
                "effort_difference": a["effort"]-b["effort"]})
        comparisons.append({"contrast": kind, "target": target, "baseline": baseline,
            "fits": len(paired), "actual_improved": sum(p["actual_J32_difference"] < -TIE for p in paired),
            "actual_worsened": sum(p["actual_J32_difference"] > TIE for p in paired),
            "full_tangent_improved": sum(p["full_tangent_J32_difference"] < -TIE for p in paired),
            "mean_actual_J32_difference": float(np.mean([p["actual_J32_difference"] for p in paired])),
            "mean_full_tangent_J32_difference": float(np.mean([p["full_tangent_J32_difference"] for p in paired])),
            "mean_nonlinear_remainder_difference": float(np.mean([p["nonlinear_remainder_difference"] for p in paired])),
            "paired_rows": paired})
    for version, task, head, branch in product(("v5", "v6"), ("agnews", "dbpedia"), ("linear", "gated"), branches):
        selected = [r for r in rows if (r["version"], r["task"], r["head"], r["branch"]) == (version, task, head, branch)]
        if len(selected) != 3 or {r["seed"] for r in selected} != {7, 17, 29}:
            raise ValueError("complete three-seed descriptive group required")
        group_rows.append({"version": version, "task": task, "head": head, "branch": branch,
            **{key: float(np.mean([r[key] for r in selected])) for key in
                ("J32", "current_terminal", "old_terminal", "effort", "warmup_old_mean")},
            "any_old_violation_fits": sum(r["old_violating_steps"] > 0 for r in selected)})
    reference_cpu = sum(c["reference_cpu_ns"] for c in costs)
    map_cpu = sum(c["cpu_ns"] for c in costs)
    rollout_cpu = sum(r["rollout_cpu_ns"] for r in rows)
    return {"branch_aggregates": branch_summary, "paired_attribution": comparisons, "descriptive_group_rows": group_rows,
        "costs": {"producer_total_cpu_ns": report["cpu_ns"], "producer_total_wall_ns": report["wall_ns"],
            "shared_reference_cpu_ns": reference_cpu, "shared_coefficient_cpu_ns": map_cpu,
            "all_actual_rollout_cpu_ns": rollout_cpu,
            "remaining_runner_io_and_checks_cpu_ns": report["cpu_ns"]-reference_cpu-map_cpu-rollout_cpu,
            "actual_branch_panel_head_evaluations_from_frozen_loop": 144*33*8,
            "reference_panel_head_evaluations_from_frozen_loop": 24*33*8,
            "actual_branch_optimizer_updates": 144*32, "shared_reference_optimizer_updates": 24*32,
            "oracle_cost_scope": "CPU clocks include computation around each region; individual query latency was not measured. Deterministic call-site counts are inferred from frozen loops.",
            "fair_per_policy_cpu_gate_benchmark": False},
        "numerical_tie_threshold": TIE,
        "limits": ["Planning-only descriptive contrasts; no independent future/old selection labels used.",
            "A one-free-action J32 planner is not the myopic H1 planner.",
            "All branches are unguarded and may violate the original old anchors; no production candidate is admitted.",
            "Field264 exceeds full continuous theta/m/v dimension108/156; complete metadata, clock and RNG remain in checkpoints.",
            "Full/field local equality does not ensure nonlinear objective improvement or heldout generalization.",
            "Action freedom, forecast compression and proposal endpoint comparisons hold other declared settings fixed; their effects on these panels do not establish an external-future causal effect."]}
