"""Finite killed first-hit F and Frechet derivatives of the shared generator."""

import numpy as np
from scipy.linalg import expm, expm_frechet

from qualification.hcsn_reset_aligned.mesh import aligned_model


def first_hit_partials(theta, times, geometry):
    """P(tau_lower<=T, tau_lower<tau_upper), before any reset or delay.

    Columns are initial spatial nodes 1..N, including the upper cemetery.
    Initial refractory laws are deliberately unsupported here. The same
    moving-node derivative convention as aligned_flow applies. Discount has
    zero derivative because F is an undiscounted first-excursion probability.
    """
    model, generator_partials = aligned_model(theta, **geometry)
    times = np.asarray(times, dtype=float)
    if (model.spatial.intervals > 64 or times.ndim != 1 or not 1 <= len(times) <= 64 or
            not np.isfinite(times).all() or np.any(times < 0) or np.any(times > 2) or
            np.any(np.diff(times) <= 0)):
        raise ValueError("bounded mesh and increasing finite first-hit horizons in [0,2] required")
    generator = model.spatial.matrix()
    values, jacobians = [], []
    for t in times:
        transition = expm(t*generator)
        jacobian = np.zeros((model.spatial.intervals, 5))
        for j in range(4):
            jacobian[:, j] = expm_frechet(t*generator, t*generator_partials[j],
                                         compute_expm=False)[1:, 0]
        values.append(transition[1:, 0])
        jacobians.append(jacobian)
    values, jacobians = np.stack(values), np.stack(jacobians)
    if not np.isfinite(values).all() or not np.isfinite(jacobians).all():
        raise ArithmeticError("first-hit exponential derivative unresolved")
    return values, jacobians
