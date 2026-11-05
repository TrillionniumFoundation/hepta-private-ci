"""Executed finite-bank experiments; fixed candidates, not policy improvement.

All simulator supports and tariffs are declared before draws. Fits, allocation
pilots, paired outcomes and independent reset banks use distinct random streams.
Known reset-law means remain a stronger comparator. Times measure this process;
tariffs are simulated utility prices, not inferred hardware prices.
"""

import argparse
import hashlib
import json
import math
import platform
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .paid_audit import PaidAudit, Plan


ETA, GRID, METHODS = 1.5, 4097, ("poly1", "poly3", "tanh16")
TASKS = ("smooth_positive", "noisy_candidate", "symmetric_null")
PROTOCOL = {"tasks": TASKS, "seeds": (57101, 57102, 57103), "methods": METHODS,
            "fit_pairs": 128, "pilot_pairs": 128, "repetitions": 64,
            "budget": 1024.0, "eta": ETA, "reset_grid_size": GRID,
            "pair_tariff": 1.0, "reset_draw_tariff": 0.02,
            "prediction_per_parameter": 0.001, "fit_operation_tariff": 1e-6,
            "utility_per_tariff_unit": 1e-5, "certificate_repetition": 0,
            "certificate_comparisons": 36, "fit_iterations": 100,
            "continuation_evaluations_per_pair": 2,
            "tariff_scope": "Simulation counters for draws, continuations, predictions and fitting; not complete physical/economic costs.",
            "unpriced_operations": "Allocation search, statistical reduction, source hashing, audit construction and output; measured CPU/wall is separate."}


def clock():
    return np.array([time.process_time(), time.perf_counter()])


def elapsed(start):
    cpu, wall = clock() - start
    return {"cpu_seconds": float(cpu), "wall_seconds": float(wall)}


def stream(task, seed, phase, method=0, repeat=0):
    return np.random.default_rng(np.random.SeedSequence([571, task, seed, phase, method, repeat]))


def outcomes(task, x, e):
    if task == 0:
        baseline = 0.35 + 0.08 * e
        candidate = baseline + 0.25 + 0.15 * x + 0.03 * x**3
    elif task == 1:
        baseline, candidate = 0.45 + 0.08 * e, 0.47 + 0.03 * x + 0.21 * e
    elif task == 2:
        baseline, candidate = 0.5 - 0.20 * x + 0.08 * e, 0.5 + 0.20 * x + 0.08 * e
    else:
        raise ValueError("Unknown frozen task")
    return candidate, baseline, np.exp(-ETA * candidate) - np.exp(-ETA * baseline)


def draw(rng, n, task=None):
    x = 2 * rng.integers(GRID, size=n) / (GRID - 1) - 1
    return x if task is None else (x, *outcomes(task, x, 2 * rng.integers(2, size=n) - 1))


def predict(model, x):
    p = np.asarray(model["parameters"])
    if model["method"].startswith("poly"):
        return np.polynomial.polynomial.polyval(x, p)
    return np.tanh(x[:, None] * p[:16] + p[16:32]) @ p[32:48] + p[48]


def fit(method, x, y, rng):
    start = clock()
    if method.startswith("poly"):
        design = np.vander(x, int(method[-1]) + 1, increasing=True)
        p = np.linalg.solve(design.T @ design + 1e-5 * np.eye(design.shape[1]), design.T @ y)
        calls, iterations, success, status, message = 1, 1, True, 0, "closed_form_ridge"
        operations = len(x) * len(p)**2
    else:
        initial = np.r_[rng.normal(size=16), rng.normal(0, 0.2, 16), rng.normal(0, 0.05, 16), 0.]
        def loss(p):
            h = np.tanh(x[:, None] * p[:16] + p[16:32])
            residual = h @ p[32:48] + p[48] - y
            delta = 2 * residual / len(y)
            hidden = delta[:, None] * p[32:48] * (1 - h*h)
            grad = np.r_[(hidden*x[:, None]).sum(0), hidden.sum(0), h.T @ delta, delta.sum()]
            return float(np.mean(residual**2) + 1e-6*np.dot(p, p)), grad + 2e-6*p
        result = minimize(loss, initial, jac=True, method="L-BFGS-B",
                          options={"maxiter": PROTOCOL["fit_iterations"], "ftol": 1e-12})
        p, calls, iterations, success = result.x, result.nfev, result.nit, bool(result.success)
        status, message = int(result.status), str(result.message)
        operations = len(x) * len(p) * calls
    model = {"method": method, "parameters": p.tolist(), "fit_calls": int(calls),
             "iterations": int(iterations), "optimizer_success": success,
             "optimizer_status": status, "optimizer_message": message,
             "fit_tariff": operations * PROTOCOL["fit_operation_tariff"], "fit_time": elapsed(start)}
    model["support_abs_bound"] = float(np.abs(p).sum() if method.startswith("poly") else
                                       np.abs(p[32:48]).sum() + abs(p[48]))
    return model


def allocate(d, h, setup, price):
    covariance = np.cov(d, h, ddof=1)
    v, c, z = covariance[0, 0], covariance[0, 1], covariance[1, 1]
    available = PROTOCOL["budget"] - setup
    m0 = math.floor(available)
    if m0 < 2:
        raise ValueError("Frozen setup exhausts this study's budget")
    best = {"m": m0, "n": 0, "beta": 0., "risk": float(v/m0), "route": "direct_after_setup"}
    for m in range(2, math.floor(available / (1 + price)) + 1):
        n = math.floor((available - (1 + price)*m) / (0.02 + price))
        if n < 2 or z <= 0:
            continue
        beta = c/z * n/(m+n)
        risk = (v - 2*beta*c + beta*beta*z)/m + beta*beta*z/n
        if risk < best["risk"]:
            best = {"m": m, "n": n, "beta": float(beta), "risk": float(risk), "route": "paid_reset"}
    return {**best, "setup": setup, "prediction_tariff": price,
            "direct_after_setup_m": m0, "pilot_moments": [float(v), float(c), float(z)]}


def known_mean(model):
    p = np.asarray(model["parameters"])
    if model["method"].startswith("poly"):
        value = p[0] + (p[2] * (GRID + 1)/(3*(GRID - 1)) if len(p) == 4 else 0.)
        return float(value), len(p)*0.001, 0
    value = predict(model, np.linspace(-1, 1, GRID)).mean()
    return float(value), GRID*len(p)*0.001, GRID


def score(estimates, truth):
    error = np.asarray(estimates) - truth
    squared = error**2
    return {"estimates": list(map(float, estimates)), "mse": float(squared.mean()),
            "mse_mc_se": float(squared.std(ddof=1)/math.sqrt(len(squared))),
            "bias": float(error.mean()), "bias_mc_se": float(error.std(ddof=1)/math.sqrt(len(error)))}


def certificate(task, seed, model, allocation, paired, h, reset):
    x, candidate, baseline, d = paired
    a, p = allocation, PROTOCOL
    target = hashlib.sha256(json.dumps([p, task, seed, model, a], sort_keys=True).encode()).hexdigest()
    bound = 0. if model is None else model["support_abs_bound"]
    audit = PaidAudit(Plan(target, ETA, (0., 1.), (-bound, bound), beta=a["beta"],
                          comparisons=p["certificate_comparisons"], budget=p["budget"]*1e-5,
                          fit_cost=a["setup"]*1e-5, fit_ids=("fit_bank", "allocation_pilot")))
    price = a["prediction_tariff"] if a["beta"] != 0 else 0.
    for i in range(len(d)):
        audit.pair(f"pair:{i}", target, float(candidate[i]), float(baseline[i]), float(h[i]), (1+price)*1e-5)
    for i in range(len(reset)):
        audit.reset(f"reset:{i}", target, float(reset[i]), (0.02+price)*1e-5)
    return audit.decide()


def run(output):
    start = clock()
    dump = lambda path, data: path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
               (Path(__file__), Path(__file__).with_name("paid_audit.py"))}
    dump(output.with_suffix(".protocol.json"), {"protocol": PROTOCOL, "source_sha256": sources})
    prepared = []
    for task in range(len(TASKS)):
        for seed in PROTOCOL["seeds"]:
            before = clock()
            train = draw(stream(task, seed, 1), PROTOCOL["fit_pairs"], task)
            pilot = draw(stream(task, seed, 2), PROTOCOL["pilot_pairs"], task)
            acquisition_time = elapsed(before)
            for j, method in enumerate(METHODS):
                model = fit(method, train[0], train[3], stream(task, seed, 3, j))
                before = clock()
                h = predict(model, pilot[0])
                price = len(model["parameters"]) * PROTOCOL["prediction_per_parameter"]
                setup = PROTOCOL["fit_pairs"] + PROTOCOL["pilot_pairs"] + model["fit_tariff"] + len(h)*price
                allocation = allocate(pilot[3], h, setup, price)
                prepared.append({"task": task, "seed": seed, "method_index": j, "model": model,
                                 "allocation": allocation, "acquisition_time": acquisition_time,
                                 "pilot_prediction_and_allocation_time": elapsed(before)})
    dump(output.with_suffix(".lock.json"), {"protocol": PROTOCOL, "source_sha256": sources, "plans": prepared})
    rows, direct_rows = [], []
    # Exact finite-table truth is only used after all fits/allocations are locked.
    grid = np.repeat(np.linspace(-1, 1, GRID), 2)
    signs = np.tile([-1, 1], GRID)
    truths = [float(outcomes(t, grid, signs)[2].mean()) for t in range(len(TASKS))]
    for task in range(len(TASKS)):
        for seed in PROTOCOL["seeds"]:
            before, estimates, cert = clock(), [], None
            for rep in range(PROTOCOL["repetitions"]):
                pair = draw(stream(task, seed, 10, repeat=rep), 1024, task)
                estimates.append(pair[3].mean())
                if rep == 0:
                    a = {"m": 1024, "n": 0, "beta": 0., "setup": 0., "prediction_tariff": 0.}
                    cert = certificate(task, seed, None, a, pair, np.zeros(1024), np.array([]))
            direct_rows.append({"task": TASKS[task], "seed": seed, **score(estimates, truths[task]),
                                "actual_pairs": 1024*PROTOCOL["repetitions"], "tariff_per_estimate": 1024.,
                                "execution_time": elapsed(before), "first_repetition_certificate": cert})
    for frozen in prepared:
        task, seed, j = frozen["task"], frozen["seed"], frozen["method_index"]
        model, a = frozen["model"], frozen["allocation"]
        before, mean_start = clock(), clock()
        exact_h, mean_fee, mean_calls = known_mean(model)
        mean_time = elapsed(mean_start)
        known_m = math.floor((PROTOCOL["budget"] - a["setup"] - mean_fee)/(1+a["prediction_tariff"]))
        v, c, z = a["pilot_moments"]
        known_beta = c/z if z > 0 else 0.
        estimates, sunk_direct, known, cert = [], [], [], None
        times = {name: np.zeros(2) for name in ("paid", "sunk_direct", "known_mean", "certificate")}
        for rep in range(PROTOCOL["repetitions"]):
            lap = clock()
            pair = draw(stream(task, seed, 20, j, rep), a["m"], task)
            h = predict(model, pair[0]) if a["beta"] != 0 else np.zeros(a["m"])
            reset = predict(model, draw(stream(task, seed, 21, j, rep), a["n"])) if a["n"] else np.array([])
            estimates.append((pair[3] - a["beta"]*h).mean() + (a["beta"]*reset.mean() if a["n"] else 0.))
            times["paid"] += clock() - lap
            lap = clock()
            sunk_direct.append(draw(stream(task, seed, 22, j, rep), a["direct_after_setup_m"], task)[3].mean())
            times["sunk_direct"] += clock() - lap
            lap = clock()
            kp = draw(stream(task, seed, 23, j, rep), known_m, task)
            known.append((kp[3] - known_beta*predict(model, kp[0])).mean() + known_beta*exact_h)
            times["known_mean"] += clock() - lap
            if rep == 0:
                lap = clock()
                cert = certificate(task, seed, model, a, pair, h, reset)
                times["certificate"] += clock() - lap
        price = a["prediction_tariff"]
        tariff = a["setup"] + a["m"]*(1 + (price if a["beta"] != 0 else 0)) + a["n"]*(0.02+price)
        rows.append({**frozen, "task": TASKS[task], "truth_moment_difference": truths[task],
                     "paid_reset": score(estimates, truths[task]), "direct_after_setup": {
                         **score(sunk_direct, truths[task]), "tariff_per_estimate": a["setup"]+a["direct_after_setup_m"]},
                     "known_reset_mean": {**score(known, truths[task]), "m": known_m, "beta": known_beta,
                                          "mean_fee": mean_fee, "mean_model_calls": mean_calls, "mean_time": mean_time,
                                          "tariff_per_estimate": a["setup"]+mean_fee+known_m*(1+price)},
                     "actual_paid_pairs": a["m"]*PROTOCOL["repetitions"],
                     "actual_independent_resets": a["n"]*PROTOCOL["repetitions"],
                     "actual_sunk_direct_pairs": a["direct_after_setup_m"]*PROTOCOL["repetitions"],
                     "actual_known_mean_pairs": known_m*PROTOCOL["repetitions"],
                     "actual_predictor_evaluation_samples": PROTOCOL["pilot_pairs"] + mean_calls +
                         PROTOCOL["repetitions"]*(known_m + (a["m"] + a["n"] if a["beta"] != 0 else 0)),
                     "tariff_per_paid_estimate": tariff, "execution_time": elapsed(before),
                     "route_times": {key: {"cpu_seconds": float(value[0]), "wall_seconds": float(value[1])}
                                     for key, value in times.items()},
                     "first_repetition_certificate": cert})
    report = {"protocol": PROTOCOL, "source_sha256": sources, "python": platform.python_version(),
              "numpy": np.__version__, "rows": rows, "direct": direct_rows, "total_time": elapsed(start),
              "truth_enumeration_pairs": len(TASKS)*2*GRID, "failed_simulator_calls": 0,
              "actual_shared_fit_and_pilot_pairs": len(TASKS)*len(PROTOCOL["seeds"])*(PROTOCOL["fit_pairs"]+PROTOCOL["pilot_pairs"]),
              "scope": "Fixed bounded simulated candidates; repeated estimator MSE, not policy improvement or hardware efficiency.",
              "cost_scope": "Each estimate charges the declared standalone fit/pilot counters; setup executed once per frozen cell. Search/certification arithmetic has measured time but no tariff. Actual timers include diagnostics and competing routes; shared acquisition timed once and charged to each method. This is not a complete economic-cost or hardware-efficiency comparison.",
              "statistical_premises": "IID finite uniform resets; IID outcome signs; independent seed streams; frozen fitting and coefficients; no evaluation reuse or refitting.",
              "limits": "MSE and MC SE are descriptive. Known reset-law mean is a stronger comparator. Hoeffding triangle supports can widen after control variates. Ordinary float64 is not validated interval arithmetic. No production, novelty or learned-policy claim."}
    dump(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"cells": len(result["rows"]), "seconds": result["total_time"]}))
