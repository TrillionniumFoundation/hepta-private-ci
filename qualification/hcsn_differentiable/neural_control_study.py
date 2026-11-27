"""CPU study: independent Bellman oracle, implicit gradients and policy learning.

Run with --output NEW.json. All thresholds below are fixed before execution.
This evaluates the affine neural control task, not localization/C2 training.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.special import lambertw
import torch

from .neural_control import (PARAMETER_NAMES, boundary_residual, optimal_boundary,
                             policy_value, refractory_value)


TASKS = ((-.15, .35, .2, 1., .25, 1., .4, .3),
         (-.4, .6, .35, 1.2, .4, .7, .3, .5),
         (.1, .25, .15, .8, .1, 1.3, .2, .15))
LIMITS = {"closed_boundary_abs": 1e-10, "implicit_gradient_abs": 2e-6,
          "boundary_grid_cells": 1.1, "reset_value_relative": 2e-4,
          "bellman_residual_abs": 2e-7, "learned_boundary_abs": 3e-5,
          "learned_value_gap": 2e-9, "interface_abs": 1e-10,
          "qvi_residual_abs": 1e-9}


def bellman_oracle(values, spacing, *, lower=-6., upper=20.):
    """Independent sparse policy iteration for the delayed-reset QVI.

Central-difference CTMC rates must be nonnegative. The lower endpoint
intervenes; the upper endpoint uses the affine particular solution. No
closed boundary or optimal value enters the grid or policy iteration.
    """
    mu, sigma, rho, reset, delay, gain, maintenance, cost = values
    n = round((upper - lower) / spacing) + 1
    y = np.linspace(lower, upper, n)
    h = y[1] - y[0]
    down, up = sigma**2 / (2*h*h) - mu / (2*h), sigma**2 / (2*h*h) + mu / (2*h)
    if min(down, up) <= 0:
        raise ValueError("grid does not define nonnegative CTMC rates")
    eta, reward = math.exp(-rho*delay), gain*y-maintenance
    j = int(np.searchsorted(y, reset, side="right") - 1)
    w = (reset-y[j])/h
    reset_row = sparse.csr_matrix(([1-w, w], ([0, 0], [j, j+1])), shape=(1, n))
    continuation = sparse.diags((-down*np.ones(n-1), (rho+up+down)*np.ones(n),
                                 -up*np.ones(n-1)), (-1, 0, 1), format="csr")
    intervention = sparse.eye(n, format="csr") - eta*sparse.vstack([reset_row]*n)
    stop = y < reset
    upper_value = gain*upper/rho + gain*mu/rho**2 - maintenance/rho
    for iteration in range(200):
        matrix = (sparse.diags((~stop).astype(float)) @ continuation
                  + sparse.diags(stop.astype(float)) @ intervention).tolil()
        rhs = np.where(stop, -cost, reward)
        matrix[0] = intervention.getrow(0)
        rhs[0] = -cost
        matrix[-1] = sparse.csr_matrix(([1.], ([0], [n-1])), shape=(1, n))
        rhs[-1] = upper_value
        value = spsolve(matrix.tocsc(), rhs)
        release = -cost + eta*float((reset_row @ value)[0])
        continuing = (reward[1:-1]+down*value[:-2]+up*value[2:])/(rho+up+down)
        advantage = release-continuing
        updated = stop.copy()
        updated[1:-1] = np.where(np.abs(advantage) > 1e-11, advantage > 0, stop[1:-1])
        updated[0], updated[-1] = True, False
        if np.array_equal(updated, stop):
            break
        stop = updated
    else:
        raise ArithmeticError("Bellman policy iteration did not converge")
    residual = np.maximum(reward[1:-1]-(continuation @ value)[1:-1], release-value[1:-1])
    if np.any(np.diff(stop.astype(int)) > 0):
        raise ArithmeticError("computed intervention region is not a lower interval")
    return {"spacing": float(h), "boundary": float(y[np.flatnonzero(stop)[-1]]),
            "reset_value": float((reset_row @ value)[0]), "iterations": iteration+1,
            "bellman_residual_abs": float(np.max(np.abs(residual)))}


def run_study():
    torch.set_num_threads(1)
    started = time.perf_counter()
    cases, failures = [], []
    for number, values in enumerate(TASKS):
        theta = torch.tensor(values, dtype=torch.float64, requires_grad=True)
        boundary = optimal_boundary(theta)
        derivative, = torch.autograd.grad(boundary, theta)
        mu, sigma, rho, reset, delay, gain, maintenance, cost = values
        kappa = (mu+math.sqrt(mu*mu+2*rho*sigma*sigma))/(sigma*sigma)
        slope, eta = gain/rho, math.exp(-rho*delay)
        p_reset = slope*reset+gain*mu/rho**2-maintenance/rho
        big_b = (1-eta)*p_reset/slope+1/kappa+cost/slope
        closed = reset-big_b-float(lambertw(-eta*math.exp(-kappa*big_b)).real)/kappa
        finite_difference = []
        for index in range(8):
            step = 1e-5*max(1., abs(values[index]))
            change = torch.zeros_like(theta)
            change[index] = step
            finite_difference.append(float((optimal_boundary(theta.detach()+change)
                                            - optimal_boundary(theta.detach()-change))/(2*step)))
        detached_b, fixed = boundary.detach(), theta.detach()
        at_reset = float(policy_value(reset, detached_b, fixed))
        at_boundary = policy_value(detached_b, detached_b, fixed)
        matching = float(at_boundary + cost-refractory_value(delay, detached_b, fixed))
        active = detached_b + torch.linspace(.0001, 8., 401, dtype=torch.float64)
        active.requires_grad_()
        value = policy_value(active, detached_b, fixed)
        first, = torch.autograd.grad(value.sum(), active, create_graph=True)
        second, = torch.autograd.grad(first.sum(), active)
        pde = mu*first + sigma*sigma/2*second + gain*active-maintenance-rho*value
        intervention_gap = at_boundary-value
        inactive = detached_b-torch.linspace(.0001, 4., 101, dtype=torch.float64)
        inactive_residual = gain*inactive-maintenance-rho*at_boundary
        qvi_error = max(float(pde.abs().max().detach()), float(intervention_gap.max().detach()),
                        float(inactive_residual.max()))
        grids = [bellman_oracle(values, h) for h in (.04, .02, .01)]
        learning = []
        for initial_gap in (.2, 1., 3.):
            fraction = (initial_gap-1e-4)/(8-1e-4)
            raw = torch.tensor(math.log(fraction/(1-fraction)), dtype=torch.float64, requires_grad=True)
            optimizer = torch.optim.LBFGS([raw], max_iter=100, tolerance_grad=1e-11,
                                         tolerance_change=1e-14, line_search_fn="strong_wolfe")
            calls = 0
            def objective():
                nonlocal calls
                optimizer.zero_grad()
                candidate = fixed[3]-1e-4-(8-1e-4)*raw.sigmoid()
                loss = -policy_value(fixed[3], candidate, fixed)
                loss.backward()
                calls += 1
                return loss
            optimizer.step(objective)
            learned = fixed[3]-1e-4-(8-1e-4)*raw.sigmoid()
            learning.append({"initial_gap": initial_gap, "closure_calls": calls,
                             "boundary": float(learned.detach()),
                             "value_gap": at_reset-float(policy_value(reset, learned, fixed).detach())})
        errors = {"closed_boundary_abs": abs(closed-float(detached_b)),
                  "implicit_gradient_abs": float(np.max(np.abs(derivative.detach().numpy()-finite_difference))),
                  "boundary_grid_cells": abs(grids[-1]["boundary"]-float(detached_b))/grids[-1]["spacing"],
                  "reset_value_relative": abs(grids[-1]["reset_value"]-at_reset)/max(1., abs(at_reset)),
                  "bellman_residual_abs": max(g["bellman_residual_abs"] for g in grids),
                  "learned_boundary_abs": max(abs(r["boundary"]-float(detached_b)) for r in learning),
                  "learned_value_gap": max(abs(r["value_gap"]) for r in learning),
                  "interface_abs": max(abs(matching), abs(float(boundary_residual(detached_b, fixed)))),
                  "qvi_residual_abs": qvi_error}
        failures.extend(f"task {number}: {key}={error} > {LIMITS[key]}"
                        for key, error in errors.items() if error > LIMITS[key])
        cases.append({"task": dict(zip(PARAMETER_NAMES, values)), "boundary": float(detached_b),
                      "reset_value": at_reset, "implicit_gradient": derivative.tolist(),
                      "central_difference": finite_difference, "grids": grids,
                      "learning": learning, "errors": errors})
    package = Path(__file__).parent
    source_hashes = {name: hashlib.sha256((package/name).read_bytes()).hexdigest()
                     for name in ("neural_control.py", "neural_control_study.py", "regenerative.py",
                                  "contract.py", "operator.py")}
    return {"study": "affine retention / delayed fixed-reset optimal release", "limits": LIMITS,
            "source_sha256": source_hashes, "torch": torch.__version__, "threads": 1,
            "wall_seconds": time.perf_counter()-started, "cases": cases,
            "failures": failures, "passed": not failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as target:
        try:
            result = run_study()
        except Exception:
            result = {"passed": False, "failures": [traceback.format_exc()], "wall_seconds": None,
                      "limits": LIMITS, "torch": torch.__version__,
                      "source_sha256": {name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                        for name in ("neural_control.py", "neural_control_study.py")}}
        json.dump(result, target, separators=(",", ":"), allow_nan=False)
        target.write("\n")
    print(json.dumps({"passed": result["passed"], "failures": result["failures"],
                      "wall_seconds": result["wall_seconds"]}, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)
