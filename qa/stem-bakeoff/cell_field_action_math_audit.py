"""Independent V3 convex-certificate, common-score and ranking arithmetic."""

import itertools
import math

import numpy as np


def common_scores(fields, actions, baseline, old_anchor, plan):
    weights = np.r_[np.full(len(actions), plan["h"]), 1.0]
    old_excess = baseline[:, 1] + fields[:, 1] - old_anchor
    current = plan["direct_coefficient"] * float(np.sum(weights * fields[:, 0]))
    tracking = 0.5 * float(np.sum(weights * (fields[:, 0] + plan["current_shift"])**2))
    forgetting = 0.5 * float(np.sum(weights * np.maximum(old_excess, 0)**2))
    effort = 0.5 * plan["h"] * plan["effort_price"] * float(np.square(actions).sum())
    return {"direct_soft_total": current + forgetting + effort, "tracking_soft_total": tracking + forgetting + effort,
            "direct_current": current, "tracking_current": tracking, "forgetting": forgetting, "effort": effort,
            "initial_old_excess": float(old_excess[0]), "maximum_future_old_excess": float(old_excess[1:].max()),
            "terminal_old_excess": float(old_excess[-1]),
            "future_old_violation_steps": int(np.count_nonzero(old_excess[1:] > plan["feasibility_tolerance"])),
            "future_retention_within_tolerance": bool(np.max(old_excess[1:]) <= plan["feasibility_tolerance"]),
            "terminal_current_nll": float(baseline[-1, 0] + fields[-1, 0]),
            "terminal_old_nll": float(baseline[-1, 1] + fields[-1, 1]),
            "feasibility_tolerance": plan["feasibility_tolerance"]}


def audit_plan(arrays, saved, model, info, old_anchor, plan, close):
    """Check independently derived objective arrays, feasible dual gap or box witness."""
    p, horizon = model["loss_maps"].shape[-1], info["lookahead"]
    maps, baseline = model["loss_maps"], model["reference_observations"]
    weights = np.r_[np.full(horizon, plan["h"]), 1.0]
    root_weights = np.sqrt(weights)
    direct = info["objective"] != "tracking_soft"
    expected = {"M": np.zeros((0, p)) if direct else maps[:horizon + 1, 0] * root_weights[:, None],
        "a": np.zeros(0) if direct else plan["current_shift"] * root_weights,
        "N": maps[:horizon + 1, 1] * root_weights[:, None],
        "b": (baseline[:horizon + 1, 1] - old_anchor) * root_weights,
        "c": plan["direct_coefficient"] * np.sum(weights[:, None] * maps[:horizon + 1, 0], axis=0) if direct else np.zeros(p),
        "constant": 0.0, "regularization": plan["h"] * plan["effort_price"],
        "bound": np.full(p, plan["action_bound"] / np.sqrt(p)),
        "G": maps[1:, 1] if info["objective"] == "direct_hard" else np.zeros((0, p)),
        "q": old_anchor - baseline[1:, 1] if info["objective"] == "direct_hard" else np.zeros(0)}
    for name, value in expected.items(): close("problem_" + name, arrays["problem__" + name], value)
    A = np.vstack([expected["G"], np.eye(p), -np.eye(p)])
    rhs = np.r_[expected["q"] + plan["feasibility_tolerance"], expected["bound"], expected["bound"]]
    close("certificate_A", arrays["certificate_A"], A)
    close("certificate_b", arrays["certificate_b"], rhs)
    record = saved["record"]
    if saved["status"] == "tangent_infeasible_with_box_witness":
        mu = arrays["farkas_weights"]
        if mu.shape != expected["q"].shape or len(mu) == 0 or not np.isfinite(mu).all() or np.any(mu < 0):
            raise ValueError("invalid nonnegative infeasibility witness")
        close("witness_normalization", mu.sum(), 1.0)
        margin = float(-expected["bound"] @ np.abs(expected["G"].T @ mu)
                       - (expected["q"] + plan["feasibility_tolerance"]) @ mu)
        close("witness_margin", record["phase_one"]["witness_margin"], margin)
        if margin <= plan["feasibility_tolerance"] or arrays["u"].size != 0:
            raise ValueError("claimed infeasibility has no separating witness")
        return {"kind": "tangent_infeasible", "witness_margin": margin}
    if saved["status"] != "qualified":
        if record["qualified"] is not False: raise ValueError("failed solver claims qualification")
        return {"kind": "solver_failure"}
    u, dual = arrays["u"], arrays["dual"]
    if u.shape != (p,) or dual.shape != rhs.shape or not np.isfinite(u).all() or not np.isfinite(dual).all() or np.any(dual < 0):
        raise ValueError("invalid primal action or nonnegative dual multipliers")
    x, z = expected["M"] @ u + expected["a"], np.maximum(expected["N"] @ u + expected["b"], 0)
    lam = expected["regularization"]
    value = float(expected["c"] @ u + 0.5 * (x @ x + z @ z + lam * (u @ u)))
    gradient = expected["M"].T @ x + expected["N"].T @ z + expected["c"] + lam * u
    stationarity = gradient + A.T @ dual
    residual = A @ u - rhs
    gap = float(-dual @ residual + (stationarity @ stationarity) / (2 * lam))
    for name, actual, wanted in [("gradient", arrays["gradient"], gradient),
            ("stationarity", arrays["stationarity"], stationarity),
            ("objective", record["objective"], value), ("gap", record["optimality_gap_bound"], gap),
            ("lower_bound", record["objective_lower_bound"], value - gap),
            ("stationarity_squared", record["stationarity_norm_squared"], stationarity @ stationarity),
            ("strong_convexity", record["strong_convexity"], lam),
            ("certificate_violation", record["certificate_primal_violation"], max(0, float(residual.max()))),
            ("bound_violation", record["bound_violation"], max(0, float((np.abs(u) - expected["bound"]).max())))]:
        close(name, actual, wanted)
    raw_violation = max(0, float((expected["G"] @ u - expected["q"]).max())) if len(expected["q"]) else 0.0
    close("raw_hard_violation", record["raw_hard_violation"], raw_violation)
    if (record["qualified"] is not True or residual.max() > 0 or gap < -1e-14
            or gap > plan["solver"]["gap_tolerance"] * (1 + 1e-6) + 1e-14
            or record["gap_tolerance"] != plan["solver"]["gap_tolerance"]
            or record["feasibility_tolerance"] != plan["feasibility_tolerance"]):
        raise ValueError("unqualified action was accepted")
    return {"kind": "qualified", "gap": gap, "raw_hard_violation": raw_violation}


def audit_ranking(runs, protocol, report, close):
    """Reconstruct all ordering counts and regret from sealed common scores."""
    rows = {(r["initial_index"], r["common_objective"], r["prediction_model"]): r for r in report["records"]}
    if len(rows) != 72 or len(report["records"]) != 72: raise ValueError("ranking census differs")
    completed = 0
    for index, initial in enumerate(runs["initial_order"]):
        registered = [r for r in runs["records"] if r["initial_index"] == index]
        usable = [r for r in registered if r["status"] == "completed"]
        excluded = [{"run_id": r["run_id"], "status": r["status"]} for r in registered if r["status"] != "completed"]
        for objective, observation in itertools.product(("direct_soft_total", "tracking_soft_total"), ("loss2", "full")):
            row = rows[(index, objective, observation)]
            if (any(row[key] != initial[key] for key in ("seed", "head", "anchor_offset"))
                    or row["registered_candidates"] != 19 or row["excluded"] != excluded):
                raise ValueError("ranking population identity differs")
            if len(usable) < 2:
                if row["status"] != "insufficient_executed_candidates": raise ValueError("missing candidates silently ranked")
                continue
            ids = [r["run_id"] for r in usable]
            p = np.array([r["predicted_scores"][observation][objective] for r in usable])
            a = np.array([r["actual_scores"][objective] for r in usable])
            tol = protocol["ranking_tie_tolerance"]
            counts = dict.fromkeys(("concordant", "discordant", "predicted_only_tie", "actual_only_tie", "both_tied"), 0)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pt, at = abs(p[i] - p[j]) <= tol, abs(a[i] - a[j]) <= tol
                    if pt and at: key = "both_tied"
                    elif pt: key = "predicted_only_tie"
                    elif at: key = "actual_only_tie"
                    elif (p[i] < p[j]) == (a[i] < a[j]): key = "concordant"
                    else: key = "discordant"
                    counts[key] += 1
            strict = counts["concordant"] + counts["discordant"]
            denominator = math.sqrt((strict + counts["predicted_only_tie"]) * (strict + counts["actual_only_tie"]))
            tied = np.flatnonzero(p <= p.min() + tol)
            selected, oracle = int(tied[0]), int(a.argmin())
            if (row["status"] != "completed" or row["candidate_ids"] != ids or row["pair_counts"] != counts
                    or row["predicted_top"] != ids[selected] or row["executed_candidate_oracle"] != ids[oracle]
                    or row["predicted_tied_minima"] != [ids[i] for i in tied]):
                raise ValueError("independent ranking or tie selection differs")
            expected = {"candidate_count": len(ids), "pair_count": len(ids) * (len(ids) - 1) // 2,
                "tie_tolerance": tol, "strict_pairs": strict,
                "strict_pair_coverage": strict / (len(ids) * (len(ids) - 1) / 2),
                "predicted_top_actual_regret": a[selected] - a[oracle],
                "worst_predicted_tie_actual_regret": max(a[tied] - a[oracle])}
            for key, value in expected.items(): close("ranking_" + key, row[key], value)
            for key, value in [("strict_order_agreement", counts["concordant"] / strict if strict else None),
                               ("kendall_tau_b", (counts["concordant"] - counts["discordant"]) / denominator if denominator else None)]:
                if value is None:
                    if row[key] is not None: raise ValueError("undefined ranking statistic invented")
                else: close("ranking_" + key, row[key], value)
            completed += 1
    return {"registered_ranking_rows": 72, "completed_ranking_rows": completed,
            "scope": "fixed finite candidate pools; no independent-anchor inference"}
