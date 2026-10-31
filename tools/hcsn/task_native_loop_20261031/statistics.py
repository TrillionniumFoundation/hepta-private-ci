"""Paired fit-level inference; failures are retained and block admission."""
import numpy as np
from scipy.stats import t

CONTRASTS = {
    "D-B": {"analytic_value": 1, "ordinary_value": -1},
    "C-A": {"analytic_fixed": 1, "ordinary_fixed": -1},
    "B-A": {"ordinary_value": 1, "ordinary_fixed": -1},
    "D-C": {"analytic_value": 1, "analytic_fixed": -1},
    "interaction": {"analytic_value": 1, "ordinary_value": -1,
                    "analytic_fixed": -1, "ordinary_fixed": 1},
}


def interval(values, comparisons=5):
    values = np.asarray(values, float)
    if len(values) < 2 or not np.all(np.isfinite(values)):
        return dict(available=False, reason="Insufficient complete independent fits")
    mean = float(values.mean())
    half = float(t.ppf(1-.05/(2*comparisons), len(values)-1)*values.std(ddof=1)/np.sqrt(len(values)))
    return dict(available=True, mean=mean, lower=mean-half, upper=mean+half,
                independent_fits=len(values), fit_values=values.tolist(),
                familywise_alpha=.05, comparisons=comparisons,
                method="Two-sided Student t across paired fit means")


def summarize_group(rows, expected):
    scored = [r for r in rows if r.get("score") is not None]
    complete = len(rows) == expected and len(scored) == expected
    result = dict(expected_sessions=expected, observed_sessions=len(rows), scored_sessions=len(scored),
                  complete=complete, failure_count=sum(r["status"] != "complete" for r in rows))
    if not scored:
        return result
    for metric in ("utility", "reward", "charged_cost", "query_cost", "latency_cost", "completed_jobs", "correct_jobs"):
        result[metric] = float(np.mean([r["score"][metric] for r in scored]))
    completed = sum(r["score"]["completed_jobs"] for r in scored)
    correct = sum(r["score"]["correct_jobs"] for r in scored)
    result["completed_accuracy"] = correct/completed if completed else None
    result["completion_fraction"] = completed/(2*len(scored))
    result["correct_fraction_of_available_jobs"] = correct/(2*len(scored))
    for metric in ("runtime_cpu_seconds", "runtime_wall_seconds", "fitted_law_regret"):
        if all(r.get(metric) is not None for r in scored):
            result[metric] = float(np.mean([r[metric] for r in scored]))
    for metric in ("READ", "SKIP", "FIRE", "STOP", "content_invocations", "failed_read_attempts"):
        result[metric] = float(np.mean([r["counts"].get(metric, 0) for r in scored]))
    outcomes = [item for row in scored for item in row.get("outcome_learning_records", [])]
    if outcomes:
        result["observed_outcome_calibration"] = dict(decisions=len(outcomes),
            fitted_law_td_bias=float(np.mean([o["fitted_law_td_residual"] for o in outcomes])),
            fitted_law_td_mse=float(np.mean([o["fitted_law_td_residual"]**2 for o in outcomes])),
            scope="Labels revealed after terminal. Oracle-bootstrap TD uses realized reward and the fitted-law optimal successor value.")
        chosen = [o for o in outcomes if o["critic_q"] is not None]
        if chosen:
            result["observed_outcome_calibration"].update(
                critic_decisions=len(chosen),
                critic_policy_return_bias=float(np.mean([o["critic_policy_return_residual"] for o in chosen])),
                critic_policy_return_mse=float(np.mean([o["critic_policy_return_residual"]**2 for o in chosen])),
                critic_oracle_bootstrap_td_mse=float(np.mean([o["critic_oracle_bootstrap_td_residual"]**2 for o in chosen])),
                return_warning="Realized returns follow the deployed policy, whereas fitted teacher Q assumes optimal continuation; this is selected-action observational calibration, not unexecuted-action value identification.")
            bins = []
            edges = [-float("inf"), 0., .25, .5, .75, 1., 1.5, 2., float("inf")]
            for left, right in zip(edges[:-1], edges[1:]):
                members = [o for o in chosen if left <= o["critic_q"] < right]
                bins.append(dict(lower=None if not np.isfinite(left) else left,
                    upper=None if not np.isfinite(right) else right, decisions=len(members),
                    mean_q=float(np.mean([o["critic_q"] for o in members])) if members else None,
                    mean_realized_return=float(np.mean([o["realized_policy_return"] for o in members])) if members else None))
            result["observed_outcome_calibration"]["predeclared_q_bins"] = bins
    return result


def analyze(rows, freeze, protocol):
    policies = list(protocol["arms"])+["direct_fixed", "fitted_dp"]
    result = dict(schema="hcsn.task.native.statistics.v1", splits={},
                  uncertainty=protocol["uncertainty"], failed_runs=[
                      {k: r.get(k) for k in ("seed", "split", "session_id", "policy", "status", "error")}
                      for r in rows if r["status"] != "complete"],
                  cpu_scope="Native runtime CPU includes child process startup, model loading, inference, real reads, persistence and serialization plus parent launch/parse overhead. Scoring, oracle regret and evidence compression are separate evaluator costs. Python fitted-DP CPU is a different implementation and is not a hardware-matched speed comparison.",
                  fixed_column_interpretation="C-A utility is structurally zero because both fixed actions use the same exact posterior threshold; their cell states may have different measured propagation costs.")
    for split in ("test", "ood"):
        by_fit = {}
        for seed in protocol["seeds"]:
            by_fit[str(seed)] = {policy: summarize_group(
                [r for r in rows if r["seed"] == seed and r["split"] == split and r["policy"] == policy],
                protocol[f"{split}_sessions"]) for policy in policies}
        contrasts = {}
        metrics = ("utility", "reward", "completed_jobs", "completed_accuracy", "completion_fraction",
                   "correct_fraction_of_available_jobs", "READ", "runtime_cpu_seconds", "fitted_law_regret")
        for name, coefficients in CONTRASTS.items():
            contrasts[name] = {}
            for metric in metrics:
                values = []
                for seed in protocol["seeds"]:
                    groups = by_fit[str(seed)]
                    if not all(groups[p]["complete"] and groups[p].get(metric) is not None for p in coefficients):
                        continue
                    values.append(sum(weight*groups[p][metric] for p, weight in coefficients.items()))
                contrasts[name][metric] = (interval(values) if len(values) == len(protocol["seeds"])
                    else dict(available=False, reason="A planned fit/session/metric is missing; no successful-run-only contrast", complete_fits=len(values)))
        sensitivity = []
        for price in protocol["cpu_prices_utility_per_second"]:
            for amortization in protocol["amortization_sessions"]:
                values = []
                for seed in protocol["seeds"]:
                    groups = by_fit[str(seed)]
                    a, b = groups["analytic_value"], groups["ordinary_value"]
                    if not all(g["complete"] and g.get("runtime_cpu_seconds") is not None for g in (a, b)):
                        continue
                    fitting = freeze["fits"][str(seed)]["training_cpu_seconds"]
                    cpu_delta = a["runtime_cpu_seconds"]-b["runtime_cpu_seconds"]
                    cpu_delta += (fitting["analytic"]-fitting["ordinary"])/amortization
                    values.append(a["utility"]-b["utility"]-price*cpu_delta)
                estimate = interval(values) if len(values) == len(protocol["seeds"]) else dict(available=False)
                sensitivity.append(dict(cpu_price=price, amortization_sessions=amortization,
                                        contrast="D-B", estimate=estimate))
        strong = {}
        for comparator in ("direct_fixed", "fitted_dp"):
            values = []
            for seed in protocol["seeds"]:
                a, b = by_fit[str(seed)]["analytic_value"], by_fit[str(seed)][comparator]
                if a["complete"] and b["complete"]:
                    values.append(a["utility"]-b["utility"])
            strong[f"D-{comparator}"] = interval(values) if len(values) == len(protocol["seeds"]) else dict(available=False)
        u = contrasts["D-B"]["utility"]
        accuracy = contrasts["D-B"]["completed_accuracy"]
        full_cost = next(r["estimate"] for r in sensitivity if r["cpu_price"] == .01 and r["amortization_sessions"] == 1000)
        failures = [r for r in result["failed_runs"] if r["split"] == split]
        result["splits"][split] = dict(fits=by_fit, contrasts=contrasts,
            exploratory_strong_baselines=strong, cpu_sensitivity=sensitivity,
            numerical_utility_gate=bool(u.get("available") and u["lower"] > 0),
            accuracy_noninferiority_gate=bool(accuracy.get("available") and accuracy["lower"] >= -protocol["quality_noninferiority_margin"]),
            complete_cost_gate=bool(full_cost.get("available") and full_cost["lower"] > 0),
            all_planned_runs_complete=not failures and all(g["complete"] for groups in by_fit.values() for g in groups.values()))
    result["statistical_gates_passed"] = all(all(s[key] for key in (
        "numerical_utility_gate", "accuracy_noninferiority_gate", "complete_cost_gate", "all_planned_runs_complete"))
        for s in result["splits"].values())
    result["native_independent_audit_required"] = True
    result["production_admission"] = False
    result["production_admission_reason"] = "Independent semantic/causal verification and scoped production decision remain separate; statistics alone cannot activate the model."
    return result
