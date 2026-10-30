"""Independent loop assembly and SciPy exponentials; no JAX kernel imports."""

import numpy as np
from scipy.linalg import expm, expm_frechet


def augmented(theta):
    mu, sigma, boundary, reset, tau = np.asarray(theta, dtype=float)
    cells, phases, lower = 8, 2, -2.
    spacing = (boundary - lower) / cells
    centers = lower + (np.arange(cells) + .5) * spacing
    weights = np.maximum(1 - abs(centers - reset) / spacing, 0)
    weights /= weights.sum()
    matrix = np.zeros((11, 11))
    diffusion = sigma**2 / (2 * spacing**2)
    for i in range(cells):
        if i:
            rate = diffusion + max(-mu, 0) / spacing
            matrix[i, i - 1] += rate
            matrix[i, i] -= rate
        if i < cells - 1:
            rate = diffusion + max(mu, 0) / spacing
            matrix[i, i + 1] += rate
            matrix[i, i] -= rate
        else:
            rate = 2 * diffusion + max(mu, 0) / spacing
            matrix[i, cells] += rate
            matrix[i, i] -= rate
            matrix[i, -1] = rate
    matrix[cells, cells + 1], matrix[cells, cells] = phases / tau, -phases / tau
    matrix[cells + 1, :cells] = phases / tau * weights
    matrix[cells + 1, cells + 1] = -phases / tau
    return matrix


def exact(theta, duration):
    return expm(augmented(theta) * duration)


def scalar_and_derivatives(theta, probability, duration, terminal):
    """Frechet uses independent centered generator derivatives at smooth points."""
    matrix, initial = augmented(theta), np.r_[probability, 0.]
    transition = expm(matrix * duration)
    gradients, finite_differences = [], []
    for index in range(5):
        direction = np.zeros(5)
        direction[index] = 1e-6
        delta = (augmented(theta + direction) - augmented(theta - direction)) / 2e-6
        gradients.append(initial @ expm_frechet(matrix * duration, delta * duration, compute_expm=False) @ terminal)
        finite_differences.append(initial @ (exact(theta + direction, duration) - exact(theta - direction, duration)) @ terminal / 2e-6)
    return dict(value=float(initial @ transition @ terminal), physical=np.array(gradients),
                centered=np.array(finite_differences), probability=(transition @ terminal)[:10],
                duration=float(initial @ matrix @ transition @ terminal))
