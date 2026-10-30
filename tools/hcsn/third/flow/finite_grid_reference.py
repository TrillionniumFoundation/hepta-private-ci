"""Independent assembly of the documented PR4255 finite generator.

Source: e0c7da64463627ebc1a383bd267af7dc96753dc1,
experiments/hcsn_distributional_v2/distribution_kernel.py,
SHA256 07195028877b4eb24f1bb1b53f1337019daf7bdabbdecbcd059f89079ba23de6.
Safety distance reverses that source's pressure coordinate. The reflecting
lower pressure wall becomes a reflecting upper safety-distance wall.
"""

import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import expm_multiply


def point_weights(centers, location, spacing):
    if not centers[0] <= location <= centers[-1]:
        raise ValueError("Initial/reset position must lie within grid centers")
    weights = np.maximum(1 - np.abs(centers - location) / spacing, 0)
    return weights / weights.sum()


def finite_grid_statistics(initial, reset, nu, sigma, refractory_mean, duration,
                           cells, upper_wall, stages=2):
    """Finite CTMC state and integrated emission count, via sparse exponential.

    This independently implements the source's rates, not its uniformization
    algorithm. Time propagation is accurate to the exponential routine's
    floating-point error; spatial/reflection and interpolation errors remain.
    """
    if cells < 2 or stages < 1 or min(sigma, refractory_mean, upper_wall) <= 0:
        raise ValueError("Positive noise/wait/wall and at least two cells required")
    spacing = upper_wall / cells
    centers = (np.arange(cells) + 0.5) * spacing
    reset_weights = point_weights(centers, reset, spacing)
    size = cells + stages
    generator = np.zeros((size + 1, size + 1))
    diffusion = sigma**2 / (2 * spacing**2)
    toward = diffusion + max(-nu, 0) / spacing
    away = diffusion + max(nu, 0) / spacing
    exit_rate = 2 * diffusion + max(-nu, 0) / spacing
    for source in range(cells):
        if source:
            generator[source - 1, source] += toward
            generator[source, source] -= toward
        else:
            generator[cells, source] += exit_rate
            generator[source, source] -= exit_rate
            generator[-1, source] = exit_rate
        if source < cells - 1:
            generator[source + 1, source] += away
            generator[source, source] -= away
    phase_rate = stages / refractory_mean
    for phase in range(stages):
        source = cells + phase
        generator[source, source] -= phase_rate
        if phase < stages - 1:
            generator[source + 1, source] += phase_rate
        else:
            generator[:cells, source] += phase_rate * reset_weights
    initial_state = np.zeros(size + 1)
    initial_state[:cells] = point_weights(centers, initial, spacing)
    matrix = csc_matrix(generator * duration)
    final = expm_multiply(matrix, initial_state, traceA=float(matrix.diagonal().sum()))
    probability = final[:-1]
    return dict(expected_events=float(final[-1]),
                active_mass=float(probability[:cells].sum()),
                refractory_mass=float(probability[cells:].sum()),
                mass_error=float(abs(probability.sum() - 1)),
                minimum_probability=float(probability.min()),
                wall_cell_mass=float(probability[cells - 1]),
                generator_mass_residual=float(np.max(abs(generator[:-1, :-1].sum(0)))),
                cells=cells, upper_wall=upper_wall, spacing=spacing,
                stages=stages, propagation="scipy.sparse.linalg.expm_multiply")
