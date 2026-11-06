"""Deterministic checks for the finite-class decision-cost reference.

No random banks, external APIs, fitted confirmation or actual model inference.
"""
import argparse
import hashlib
import json
import math
import platform
import time
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import linprog


def binary_kl(p, q):
    p, q = float(p), float(q)
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


def logsum_kl(p, q):
    return sum(float(x) * math.log(float(x / y)) for x, y in zip(p, q))


def characteristic(probabilities, costs, answers, theta):
    p = np.asarray(probabilities, dtype=float)
    c = np.asarray(costs, dtype=float)
    alternative = [i for i, answer in enumerate(answers) if answer != answers[theta]]
    if not alternative:
        return {"cost": 0., "allocation": [0.] * p.shape[1]}
    divergences = np.array([np.sum(p[theta] * np.log(p[theta] / p[i]), axis=1)
                            for i in alternative])
    mean_costs = np.sum(p[theta] * c, axis=1)
    result = linprog(mean_costs, A_ub=-divergences, b_ub=-np.ones(len(alternative)),
                     bounds=(0, None), method="highs")
    if not result.success:
        return {"status": result.status, "feasible": False}
    dual = -result.ineqlin.marginals
    return {"feasible": True, "cost": float(result.fun),
            "allocation": result.x.tolist(), "dual": dual.tolist(),
            "primal_min_slack": float(np.min(divergences @ result.x - 1)),
            "dual_min_slack": float(np.min(mean_costs - divergences.T @ dual)),
            "duality_gap": float(result.fun - sum(dual))}


def flow_lower_bound(deadline, divergence, threshold):
    """Time-expanded prepare/probe/reset flow relaxation, not a policy solver."""
    count = 2 * deadline + 1
    objective = np.zeros(count)
    for t in range(deadline):
        objective[t] = (.14, .13, .03)[t % 3]
    flow = np.zeros((deadline + 1, count))
    for t in range(deadline + 1):
        flow[t, deadline + t] = 1
        if t < deadline:
            flow[t, t] = 1
        if t:
            flow[t, t - 1] = -1
    rhs = np.zeros(deadline + 1)
    rhs[0] = 1
    information = np.zeros(count)
    information[1:deadline:3] = divergence
    result = linprog(objective, A_ub=[-information], b_ub=[-threshold],
                     A_eq=flow, b_eq=rhs, bounds=(0, None), method="highs")
    return {"feasible": bool(result.success), "status": result.status,
            "cost": float(result.fun) if result.success else None,
            "completed_probe_cap": (deadline + 1) // 3}


def binomial_law(n, p):
    return [F(math.comb(n, j)) * p ** j * (1 - p) ** (n - j)
            for j in range(n + 1)]


def bayes_error(n, p, q):
    return sum(min(x, y) for x, y in zip(binomial_law(n, p), binomial_law(n, q))) / 2


def finite_wrong_mass(probabilities, answers, delta, cap):
    """Exact prefix enumeration of a common adaptive likelihood stopping rule.

    The cap returns unresolved rather than forcing a decision. This checks the
    time-uniform error inequality, not the efficiency of the main construction.
    """
    members = len(probabilities)
    threshold = F(members - 1) / delta
    completed = [[F(0) for _ in range(2)] for _ in range(members)]
    unresolved = [F(0) for _ in range(members)]

    def walk(masses, depth, last):
        chosen = next((j for j in range(members)
                       if all(answers[i] == answers[j] or masses[j] >= threshold * masses[i]
                              for i in range(members))), None)
        if chosen is not None:
            for i, mass in enumerate(masses):
                completed[i][int(answers[chosen] != answers[i])] += mass
            return
        if depth == cap:
            for i, mass in enumerate(masses):
                unresolved[i] += mass
            return
        experiment = (depth + last) % 2
        for outcome in range(2):
            walk([mass * probabilities[i][experiment][outcome]
                  for i, mass in enumerate(masses)], depth + 1, outcome)

    walk([F(1)] * members, 0, 0)
    return [{"correct": str(row[0]), "wrong": str(row[1]),
             "unresolved": str(unresolved[i]), "wrong_float": float(row[1])}
            for i, row in enumerate(completed)]


def verify():
    checks, evidence = [], {}

    def check(name, condition):
        checks.append(name)
        if not condition:
            raise AssertionError(name)

    # An adaptive experiment: A first; only a zero response requests B.
    laws = [[F(1, 2), F(1, 3)], [F(4, 5), F(3, 4)]]
    transcripts, expected_counts, tree_costs = [], [], []
    for pa, pb in laws:
        transcripts.append([pa, (1 - pa) * pb, (1 - pa) * (1 - pb)])
        expected_counts.append([F(1), 1 - pa])
        tree_costs.append(2 * pa + (1 - pa) * (1 + 3 * pb + 2 * (1 - pb)))
    directed = []
    for i, j in ((0, 1), (1, 0)):
        pa, pb = laws[i]
        chain = binary_kl(pa, laws[j][0]) + float(1 - pa) * binary_kl(pb, laws[j][1])
        direct = logsum_kl(transcripts[i], transcripts[j])
        predicted_cost = (1 + pa) + (1 - pa) * (2 + pb)
        check("adaptive_joint_KL_" + str(i), abs(chain - direct) < 1e-14)
        check("outcome_dependent_cost_" + str(i), predicted_cost == tree_costs[i])
        directed.append({"theta": i, "KL": direct, "expected_cost": str(tree_costs[i]),
                         "expected_counts": list(map(str, expected_counts[i]))})
    evidence["adaptive_transcript"] = directed

    # A three-model catalog: answer 0 versus either of two answer-1 models.
    means = [[F(1, 2), F(1, 2)], [F(1, 10), F(1, 2)], [F(1, 2), F(1, 10)]]
    probabilities = [[[1 - p, p] for p in row] for row in means]
    answers, costs = [0, 1, 1], [[1., 1.], [2., 2.]]
    expected = [3 / binary_kl(.5, .1), 1 / binary_kl(.1, .5), 2 / binary_kl(.1, .5)]
    allocation_rows = []
    for theta in range(3):
        result = characteristic(probabilities, costs, answers, theta)
        check("allocation_primal_dual_" + str(theta), result["feasible"] and
              min(result["primal_min_slack"], result["dual_min_slack"]) > -1e-10 and
              abs(result["duality_gap"]) < 1e-10)
        check("allocation_analytic_match_" + str(theta), abs(result["cost"] - expected[theta]) < 1e-10)
        allocation_rows.append({"theta": theta, "analytic_cost": expected[theta], **result})
    evidence["cost_allocation"] = allocation_rows
    impossible = characteristic([[[.5, .5]], [[.5, .5]]], [[1., 1.]], [0, 1], 0)
    check("observationally_identical_opposite_answers_infeasible", impossible == {"status": 2, "feasible": False})

    likelihood_rows = []
    for delta in (F(1, 5), F(1, 10), F(1, 20)):
        rows = finite_wrong_mass(probabilities, answers, delta, 12)
        for theta, row in enumerate(rows):
            check("likelihood_prefix_" + str(delta) + "_" + str(theta),
                  F(row["wrong"]) <= delta and F(row["correct"]) + F(row["wrong"]) + F(row["unresolved"]) == 1)
        likelihood_rows.append({"delta": str(delta), "cap": 12, "models": rows})
    evidence["likelihood_prefix"] = likelihood_rows

    p, q, resource = F(57, 100), F(87, 100), .30
    divergence = [binary_kl(p, q), binary_kl(q, p)]
    threshold = binary_kl(.95, .05)
    flow_rows = []
    for deadline in (1, 2, 8, 20, 40, 80):
        for theta, d in enumerate(divergence):
            result = flow_lower_bound(deadline, d, threshold)
            needed = threshold / d
            predicted_feasible = needed <= result["completed_probe_cap"] + 1e-12
            check("flow_feasibility_" + str((deadline, theta)), result["feasible"] == predicted_feasible)
            if result["feasible"]:
                analytic = .27 * needed if needed <= 1 else .30 * needed - .03
                check("flow_cost_boundary_" + str((deadline, theta)), abs(result["cost"] - analytic) < 1e-10)
            flow_rows.append({"deadline": deadline, "theta": theta, **result})
    evidence["paid_state_time_flow"] = flow_rows
    first_kl_cap = math.ceil(threshold / min(divergence))
    strong_error = bayes_error(first_kl_cap, p, q)
    check("KL_feasibility_is_not_sufficient", first_kl_cap * min(divergence) >= threshold and strong_error > F(1, 20))
    evidence["deadline_counterexample"] = {"delta": ".05", "probe_cap": first_kl_cap,
        "minimum_time_for_cap": 3 * first_kl_cap - 1,
        "full_probe_Bayes_error_exact": str(strong_error), "full_probe_Bayes_error": float(strong_error),
        "inference": "Bayes error already exceeds delta, so no rule can have both conditional errors at most delta."}

    nuisance_rows = []
    for epsilon in (.10, .03, .01, .003):
        nuisance = binary_kl(.5 + epsilon, .5 - epsilon)
        for theta, d in enumerate(divergence):
            base_p = (float(p), float(q))[theta]
            other_p = (float(q), float(p))[theta]
            joint = [base_p * (.5 + epsilon), base_p * (.5 - epsilon),
                     (1 - base_p) * (.5 + epsilon), (1 - base_p) * (.5 - epsilon)]
            same_eta = [other_p * (.5 + epsilon), other_p * (.5 - epsilon),
                        (1 - other_p) * (.5 + epsilon), (1 - other_p) * (.5 - epsilon)]
            check("nuisance_cancels_for_answer_" + str((epsilon, theta)), abs(logsum_kl(joint, same_eta) - d) < 1e-12)
            nuisance_rows.append({"epsilon": epsilon, "theta": theta, "answer_constant": resource / d,
                "full_model_constant": resource / min(d, nuisance), "ratio": d / min(d, nuisance)})
    evidence["nuisance_separation"] = nuisance_rows
    overshoot = max(abs(math.log(float(q / p))), abs(math.log(float((1 - q) / (1 - p)))))
    evidence["binary_cost_bounds"] = [{"delta": delta, "theta": theta,
        "lower_cost": resource * binary_kl(1 - delta, delta) / d,
        "upper_cost": resource * (math.log(1 / delta) + overshoot) / d,
        "upper_to_lower_ratio": (math.log(1 / delta) + overshoot) / binary_kl(1 - delta, delta)}
        for delta in (.05, .001, 1e-6) for theta, d in enumerate(divergence)]
    evidence["gating_values"] = {"prior_stop": .5,
                                "negative_member_forced_deploy": float(p) - .22,
                                "negative_member_optimal_stop": .5,
                                "positive_member_deploy": float(q) - .22,
                                "calibration_cycle_resource": resource}
    evidence["amortization_bounds"] = [{"delta": row["delta"], "gain": .15,
        "necessary_volume_strictly_greater_than": row["lower_cost"] / .15,
        "sufficient_volume_strictly_greater_than": row["upper_cost"] / ((1 - row["delta"]) * .15),
        "scope": "Analytic finite-catalog expected-cost bounds under declared synthetic prices, not a confirmation result."}
        for row in evidence["binary_cost_bounds"] if row["theta"] == 1]
    return {"checks": checks, "check_count": len(checks), "evidence": evidence}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    if output.exists() or output.is_symlink():
        raise SystemExit("Refusing to overwrite a verification receipt")
    started = time.perf_counter()
    root = Path(__file__).resolve().parent
    sources = [root / "DECISION_COST_THEORY.md", Path(__file__).resolve()]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {"schema": "ndu.decision-cost-verification.v1", "status": "PASS",
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Deterministic exact finite enumeration and floating-point LP audits; no new confirmation data, actual LLM, provider bill, external proof review or general RL claim.",
              "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "source_sha256_before": before, **verify()}
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    if before != after:
        raise AssertionError("Sources changed during verification")
    report.update(source_sha256_after=after, elapsed_compute_seconds=time.perf_counter() - started,
                  finished_at_utc=datetime.now(timezone.utc).isoformat())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "checks": report["check_count"],
                      "receipt_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))
