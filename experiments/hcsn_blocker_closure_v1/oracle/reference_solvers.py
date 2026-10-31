"""Independent LP and value-iteration references; no policy solver import."""

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix


def linear_program(problem):
    n = len(problem.grid)
    rows = [problem.generator-problem.rho*np.eye(n)]
    bounds = [-problem.running]
    obstacle = problem.delay_discount*np.tile(problem.reset, (n, 1))-np.eye(n)
    for reward in problem.rewards:
        rows.append(obstacle)
        bounds.append(-reward)
    result = linprog(np.ones(n)/n, A_ub=np.vstack(rows), b_ub=np.concatenate(bounds),
                     bounds=[(None, None)]*n, method="highs",
                     options={"dual_feasibility_tolerance": 1e-9,
                              "primal_feasibility_tolerance": 1e-9})
    if not result.success:
        raise RuntimeError(result.message)
    return dict(value=result.x, objective=float(result.fun), iterations=int(result.nit),
                max_inequality_violation=float(max(0, (np.vstack(rows)@result.x-np.concatenate(bounds)).max())))


def value_iteration(problem, tolerance=2e-9, max_iterations=1000000):
    rate = max(float(-np.diag(problem.generator).min()), 1e-12)
    beta = rate/(rate+problem.rho)
    transition = csr_matrix(np.eye(len(problem.grid))+problem.generator/rate)
    gamma = max(beta, problem.delay_discount)
    value = np.zeros(len(problem.grid))
    for iteration in range(max_iterations):
        keep = problem.running/(rate+problem.rho)+beta*(transition@value)
        fire = problem.rewards.max(0)+problem.delay_discount*(problem.reset@value)
        updated = np.maximum(keep, fire)
        bound = float(np.max(np.abs(updated-value)))/(1-gamma)
        value = updated
        if bound <= tolerance:
            return dict(value=value, iterations=iteration+1, successive_difference_bound=bound)
    raise RuntimeError("Reference value iteration did not converge")
