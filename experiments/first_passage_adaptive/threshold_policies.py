"""Frozen, same-information policies for the registered renewal task."""

from dataclasses import asdict
import time

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit

from .thresholds import EvaluationCost, renewal_value


CONFIGURATION = {
    "planner_grid_size": 257, "planner_xatol": 1e-10,
    "ordinary_features": "standardized full quadratic of all eight public inputs",
    "ordinary_initial_intercepts": [-2.0, -1.0, 0.0],
    "ordinary_maxiter": 160, "ordinary_ftol": 1e-12,
    "ordinary_gtol": 1e-7, "ordinary_ridge": 1e-5,
    "selection": "highest development analytic expected task utility",
}


def grid_refine(objective, bounds):
    """Search every local grid peak, retaining endpoints and the STOP option."""
    grid = np.linspace(*bounds, CONFIGURATION["planner_grid_size"])
    values = np.array([objective(float(b)) for b in grid])
    candidates = [(float(b), float(v)) for b, v in zip(grid, values)]
    searches = []
    for i in range(1, len(grid)-1):
        if values[i] >= values[i-1] and values[i] >= values[i+1]:
            result = minimize_scalar(lambda b: -objective(b), method="bounded",
                bounds=(grid[i-1], grid[i+1]),
                options={"xatol": CONFIGURATION["planner_xatol"]})
            candidates.append((float(result.x), float(-result.fun)))
            searches.append({"bracket": [float(grid[i-1]), float(grid[i+1])],
                "threshold": float(result.x), "value": float(-result.fun),
                "evaluations": int(result.nfev), "success": bool(result.success)})
    best = max(candidates+[(0.0, 0.0)], key=lambda pair: pair[1])
    return best, {"grid_thresholds": grid.tolist(), "grid_values": values.tolist(),
                  "local_searches": searches}


def fit_fixed(contexts, bounds):
    counter = EvaluationCost()
    start = time.perf_counter()
    objective = lambda b: float(np.mean(renewal_value(b, contexts, counter=counter)))
    (threshold, value), search = grid_refine(objective, bounds)
    return {"threshold": threshold, "training_value": value, "search": search,
        "cost": {**asdict(counter), "wall_seconds": time.perf_counter()-start},
        "trainable_parameter_count": 1}


def feature_matrix(contexts, center=None, scale=None):
    raw = np.array([[c.mu, c.sigma, c.cancel_rate, c.cost, c.horizon,
                     c.budget, c.refractory, c.discount] for c in contexts])
    if center is None:
        center = raw.mean(axis=0)
        scale = raw.std(axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
    center, scale = np.asarray(center), np.asarray(scale)
    z = (raw-center)/scale
    columns = [np.ones(len(contexts)), *z.T]
    columns.extend(z[:, i]*z[:, j] for i in range(8) for j in range(i, 8))
    return np.array(columns).T, center, scale


def ordinary_thresholds(model, contexts, bounds):
    x, _, _ = feature_matrix(contexts, model["center"], model["scale"])
    c = np.array([context.cost for context in contexts])
    return np.clip(c+(bounds[1]-c)*expit(x@np.asarray(model["weights"])), *bounds)


def fit_ordinary(train, development, bounds):
    x, center, scale = feature_matrix(train)
    cost = np.array([c.cost for c in train])
    width = bounds[1]-cost
    if np.any(width <= 0) or np.any(cost < bounds[0]):
        raise ValueError("Registered sigmoid controller requires lower<=cost<upper")
    candidates = []
    all_counter = EvaluationCost()
    start = time.perf_counter()
    for intercept in CONFIGURATION["ordinary_initial_intercepts"]:
        counter = EvaluationCost()
        evaluations = []

        def loss(weights):
            sigmoid = expit(x@weights)
            b = cost+width*sigmoid
            value, db = renewal_value(b, train, derivative=True, counter=counter)
            ridge = CONFIGURATION["ordinary_ridge"]
            reg = weights.copy()
            reg[0] = 0.0
            objective = -value.mean()+ridge*np.dot(reg, reg)
            gradient = -(x.T@(db*width*sigmoid*(1-sigmoid)))/len(train)+2*ridge*reg
            evaluations.append({"objective": float(objective),
                                "task_value": float(value.mean()),
                                "gradient_norm": float(np.linalg.norm(gradient))})
            return float(objective), gradient

        initial = np.zeros(x.shape[1])
        initial[0] = intercept
        result = minimize(loss, initial, jac=True, method="L-BFGS-B", options={
            "maxiter": CONFIGURATION["ordinary_maxiter"],
            "ftol": CONFIGURATION["ordinary_ftol"],
            "gtol": CONFIGURATION["ordinary_gtol"]})
        model = {"weights": result.x.tolist(), "center": center.tolist(),
                 "scale": scale.tolist()}
        dev_b = ordinary_thresholds(model, development, bounds)
        dev_value = float(renewal_value(dev_b, development, counter=counter).mean())
        candidates.append({**model, "initial_intercept": intercept,
            "development_value": dev_value, "optimizer_success": bool(result.success),
            "optimizer_message": str(result.message), "iterations": int(result.nit),
            "evaluations": evaluations, "cost": asdict(counter)})
        for key, value in asdict(counter).items():
            setattr(all_counter, key, getattr(all_counter, key)+value)
    selected = max(range(len(candidates)), key=lambda i: candidates[i]["development_value"])
    model = candidates[selected]
    # Constant rho and its interactions produce zero columns, not fitted capacity.
    active_columns = np.any(np.abs(x) > 1e-14, axis=0)
    return {"weights": model["weights"], "center": model["center"], "scale": model["scale"],
        "selected_candidate": selected, "candidate_searches": candidates,
        "stored_parameter_count": x.shape[1],
        "active_parameter_count": int(active_columns.sum()),
        "feature_rank": int(np.linalg.matrix_rank(x)),
        "cost": {**asdict(all_counter), "wall_seconds": time.perf_counter()-start}}


def plan_context(context, bounds):
    counter = EvaluationCost()
    start = time.perf_counter()
    objective = lambda b: float(renewal_value(b, [context], counter=counter)[0])
    (threshold, value), search = grid_refine(objective, bounds)
    return threshold, {"analytic_value": value, "search": search,
        "cost": {**asdict(counter), "wall_seconds": time.perf_counter()-start}}
