"""Independent residual/simulation and reproducible finite-oracle evidence.

Run: python -m experiments.hcsn_task_value_v1.oracle_validation
Every run retains its report, including failures; no training-performance claim.
"""

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import subprocess
import sys
import time

import numpy as np
import scipy

from ..hcsn_hx_unified_v3.coupled_qvi import Rectangle, TwoCell
from ..hcsn_hx_unified_v3.erlang_async_qvi import solve_erlang_policy
from ..hcsn_hx_unified_v3.stopping import Stop
from .oracle import build, solve_jacobi, solve_policy
from .oracle_gradients import direction, one_sided_gradients


def configuration():
    cells = TwoCell(Stop(.035, .45, .16, 1., .13, .4),
                    Stop(-.02, .42, .16, 1.1, -.11, .6))
    return cells, Rectangle(-2., 4.5, 9, -2., 4.5, 9), (2, 2)


def task_model(cells=None, *, reset_shift=0., reward_shift=0.):
    default, rect, phases = configuration()
    cells = default if cells is None else cells
    x, y = np.linspace(-2., 4.5, 9), np.linspace(-2., 4.5, 9)
    z = np.r_[x, [0., 0.]]; w = np.r_[y, [0., 0.]]
    running = .05*z[:, None]*w[None, :]-.03*(z[:, None]**2+w[None, :]**2)
    running[9:, :] -= .07
    running[:, 9:] -= .09
    running += reward_shift*np.sin(z[:, None]+.2*w[None, :])
    logits = -.4*(x[None, :]-.1*np.tanh(w[:, None]))**2+reset_shift*x[None, :]
    k1 = np.exp(logits-logits.max(axis=1, keepdims=True))
    k1 /= k1.sum(axis=1, keepdims=True)
    return build(cells, rect, phases, running=running, reset1=k1)


def independent_edges(model, i, j):
    """Rebuild scalar CTMC transitions from primitive parameters, not solver graph."""
    n1, n2 = len(model.x1), len(model.x2)
    for axis, c, x, n, k, idx in (
        (0, model.cells.first, model.x1, n1, model.phases[0], i),
        (1, model.cells.second, model.x2, n2, model.phases[1], j),
    ):
        if idx < n:
            h = x[1]-x[0]
            d = c.diffusion**2/(2*h*h)
            down, up = d-c.drift/(2*h), d+c.drift/(2*h)
            if min(down, up) < 0:
                down = d+max(-c.drift, 0)/h
                up = d+max(c.drift, 0)/h
            if idx:
                yield ((i-1, j) if axis == 0 else (i, j-1)), down
            if idx < n-1:
                yield ((i+1, j) if axis == 0 else (i, j+1)), up
        elif idx == n:
            weights = model.reset1[j] if axis == 0 else model.reset2[i]
            for dest, weight in enumerate(weights):
                if weight:
                    yield ((dest, j) if axis == 0 else (i, dest)), k*weight/c.refractory
        else:
            yield ((i-1, j) if axis == 0 else (i, j-1)), k/c.refractory


def independent_residual(model, result):
    n1, n2 = len(model.x1), len(model.x2)
    v, p = result.values, result.policy
    cash = model.cash.reshape(3, *model.shape)
    maximum, selected = 0., 0.
    for i in range(model.shape[0]):
        for j in range(model.shape[1]):
            cont = cash[0, i, j]-model.cells.first.discount*v[i, j]
            for dest, rate in independent_edges(model, i, j):
                cont += rate*(v[dest]-v[i, j])
            values = [cont,
                      cash[1, i, j]+v[-1, j]-v[i, j] if i < n1 else -math.inf,
                      cash[2, i, j]+v[i, -1]-v[i, j] if j < n2 else -math.inf]
            maximum = max(maximum, abs(max(values)))
            selected = max(selected, abs(values[int(p[i, j])]))
    return {"qvi": maximum, "selected": selected}


def policy_monte_carlo(model, result, start, *, seed, episodes=700):
    """Independent Gillespie trajectories with exact running-reward integration."""
    rng, samples = random.Random(seed), []
    rho = model.cells.first.discount
    cash = model.cash.reshape(3, *model.shape)
    max_events = 0
    for _ in range(episodes):
        i, j = start
        weight, reward = 1., 0.
        for event in range(20000):
            if weight < 1e-10:
                break
            action = int(result.policy[i, j])
            if action:
                reward += weight*cash[action, i, j]
                if action == 1:
                    i = model.shape[0]-1
                else:
                    j = model.shape[1]-1
                continue
            edges = list(independent_edges(model, i, j))
            total_rate = sum(rate for _, rate in edges)
            elapsed = rng.expovariate(total_rate)
            discount = math.exp(-rho*elapsed)
            reward += weight*cash[0, i, j]*(-math.expm1(-rho*elapsed))/rho
            weight *= discount
            target = rng.random()*total_rate
            for dest, rate in edges:
                target -= rate
                if target <= 0:
                    i, j = dest
                    break
            else:
                i, j = edges[-1][0]
        else:
            raise RuntimeError("Independent sampler event budget exhausted")
        max_events = max(max_events, event)
        samples.append(reward)
    mean = float(np.mean(samples))
    se = float(np.std(samples, ddof=1)/math.sqrt(episodes))
    expected = float(result.values[start])
    return {"start": start, "seed": seed, "episodes": episodes,
            "mean": mean, "stderr": se, "oracle": expected,
            "absolute_error": abs(mean-expected), "maximum_events": max_events,
            "accepted": abs(mean-expected) <= 6*se+.02}


def run(output=None):
    directory = Path(output) if output else Path(__file__).parent/"results"/"oracle001"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    started = time.perf_counter()
    report = {"schema": "hcsn-task-value-oracle-v1", "run": stamp,
              "python": platform.python_version(), "numpy": np.__version__,
              "scipy": scipy.__version__, "failures": [],
              "scope": "finite CTMC reward/reset and directional value derivatives; not neural advantage"}
    try:
        cells, rect, phases = configuration()
        model = build(cells, rect, phases)
        base = solve_policy(model)
        donor = solve_erlang_policy(cells, rect, phases)
        report["donor_recovery"] = {
            "max_value_error": float(np.max(np.abs(base.values-donor.values))),
            "equal_policy": bool(np.array_equal(base.policy, donor.policy))}
        task = task_model()
        answer = solve_policy(task)
        independent = solve_jacobi(task)
        without_running = solve_policy(build(cells, rect, phases, reset1=task.reset1))
        report["task"] = {"howard_iterations": answer.iterations,
                          "jacobi_iterations": independent.iterations,
                          "algorithm_error": float(np.max(np.abs(answer.values-independent.values))),
                          "residuals": independent_residual(task, answer),
                          "policy_changes_from_zero_running_reward": int(np.sum(answer.policy != without_running.policy))}
        directions = []
        for name, field, keyword in (("drift1", "drift", "drift"),
                                     ("diffusion1", "diffusion", "diffusion"),
                                     ("refractory1", "refractory", "refractory"),
                                     ("cost1", "cost", "cost")):
            eps = 2e-6
            plus = TwoCell(replace(cells.first, **{field: getattr(cells.first, field)+eps}), cells.second)
            minus = TwoCell(replace(cells.first, **{field: getattr(cells.first, field)-eps}), cells.second)
            fd = (solve_policy(task_model(plus)).values-solve_policy(task_model(minus)).values)/(2*eps)
            sense = one_sided_gradients(task, answer, direction(task, **{keyword: (1., 0.)}))
            directions.append({"name": name, "epsilon": eps,
                               "max_fd_error": float(np.max(np.abs(fd-sense.right))),
                               "kink_norm": sense.kink_norm, "tie_states": sense.tie_states})
        score = task.x1[None, :]
        dk = task.reset1*(score-(task.reset1*score).sum(axis=1, keepdims=True))
        sense = one_sided_gradients(task, answer, direction(task, reset1=dk))
        eps = 2e-6
        fd = (solve_policy(task_model(reset_shift=eps)).values-
              solve_policy(task_model(reset_shift=-eps)).values)/(2*eps)
        directions.append({"name": "reset_softmax_logit", "epsilon": eps,
                           "max_fd_error": float(np.max(np.abs(fd-sense.right))),
                           "kink_norm": sense.kink_norm, "tie_states": sense.tie_states})
        report["gradients"] = directions
        report["monte_carlo"] = [policy_monte_carlo(task, answer, start, seed=7130+i)
                                 for i, start in enumerate(((8, 8), (9, 4), (10, 10)))]
        np.savez_compressed(directory/f"arrays_{stamp}.npz", values=answer.values,
                            policy=answer.policy, running=task.cash[0].reshape(task.shape),
                            reset1=task.reset1, reset2=task.reset2)
        checks = [report["donor_recovery"]["max_value_error"] < 1e-11,
                  report["donor_recovery"]["equal_policy"],
                  report["task"]["algorithm_error"] < 2e-8,
                  report["task"]["residuals"]["qvi"] < 1e-9,
                  all(row["max_fd_error"] < 2e-5 for row in directions),
                  all(row["accepted"] for row in report["monte_carlo"])]
        if not all(checks):
            report["failures"].append({"acceptance_checks": checks})
    except Exception as exc:
        report["failures"].append({"exception": type(exc).__name__, "message": str(exc)})
    tests = subprocess.run([sys.executable, "-m", "unittest", "-v",
                            "experiments.hcsn_task_value_v1.oracle_tests"],
                           capture_output=True, text=True, check=False)
    (directory/f"tests_{stamp}.log").write_text(tests.stdout+tests.stderr)
    report["unittest_exit_code"] = tests.returncode
    if tests.returncode:
        report["failures"].append({"unittest_exit_code": tests.returncode})
    report["sources_sha256"] = {name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                               for name in ("oracle.py", "oracle_gradients.py", "oracle_tests.py", "oracle_validation.py")}
    report["elapsed_seconds"] = time.perf_counter()-started
    report["passed"] = not report["failures"]
    path = directory/f"report_{stamp}.json"
    path.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"report": str(path), "passed": report["passed"],
                      "failures": report["failures"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
