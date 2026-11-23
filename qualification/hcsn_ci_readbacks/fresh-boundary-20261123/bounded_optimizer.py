"""Find a finite-sample, source-constrained linear purchase edit at a fixed observation price."""
import numpy as np

UNIT = 1_000_000_000


def discover(design, weights, data, free, paid, separation):
    from scipy.optimize import Bounds, LinearConstraint, milp
    # Positive and negative parts of the edit, followed by one purchase bit per query.
    n, k = design.shape
    radius = 0.999
    net = 10 * (paid.astype(int) - free.astype(int)) - 3
    original = design @ weights - 0.30
    big_m = abs(original) + np.max(abs(design), axis=1) * radius + separation
    matrix = [*np.column_stack((design, -design, -np.diag(big_m))), np.r_[np.ones(2*k), np.zeros(n)]]
    lower = [*(separation - big_m - original), 0.0]
    upper = [*(-separation - original), radius]
    for name in sorted(set(data['group'])):
        matrix.append(np.r_[np.zeros(2*k), (data['group'] == name) * net])
        lower.append(0.0)
        upper.append(np.inf)
    objective = np.r_[np.full(2*k, 0.00001), -net]
    bounds = Bounds(np.zeros(2*k+n), np.r_[np.full(2*k, radius), np.ones(n)])
    constraint = LinearConstraint(np.stack(matrix), np.array(lower), np.array(upper))
    result = milp(objective, integrality=np.r_[np.zeros(2*k), np.ones(n)], bounds=bounds,
                  constraints=constraint, options={'time_limit': 90, 'mip_rel_gap': 0})
    if result.x is None:
        raise RuntimeError(result.message)
    return np.rint(UNIT*(result.x[:k]-result.x[k:2*k])).astype(int).tolist()

