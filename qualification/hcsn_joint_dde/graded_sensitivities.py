"""Actual-node physical derivatives for the explicitly selected graded v2 model.

No uniform-grid qualification is inherited. Nodes, stretch, delay and the
initial relative law are fixed; only B/mu/sigma/Vr/q are differentiated.
"""

import numpy as np

from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.sensitivities import (
    _solve_variational,
    _check_sensitivity_shape,
)


def solve_graded_partials(model, query_times, active, content, phase=(), **options):
    """Evolve the graded candidate's own physical variational DDE."""
    if (
        type(model) is not GradedJointModel
        or type(model.spatial) is not GradedSpatialGenerator
    ):
        raise ValueError("exact graded-v2 model/geometry required")
    _check_sensitivity_shape(model, content)
    nodes = model.spatial.nodes
    gaps = np.diff(nodes)
    left, right = gaps[:-1], gaps[1:]
    full = np.zeros((5, len(nodes), len(nodes)))
    indices = np.arange(1, len(nodes) - 1)
    down_mu = -right / (left * (left + right))
    up_mu = left / (right * (left + right))
    down_sigma = 2 * model.spatial.sigma / (left * (left + right))
    up_sigma = 2 * model.spatial.sigma / (right * (left + right))
    for j, lower, upper in ((1, down_mu, up_mu), (2, down_sigma, up_sigma)):
        full[j, indices, indices - 1] = lower
        full[j, indices, indices + 1] = upper
        full[j, indices, indices] = -(lower + upper)
    if not np.all(np.isfinite(full)):
        raise ValueError("nonfinite graded generator partials")
    return _solve_variational(
        model, query_times, active, content, phase, nodes=nodes, full=full, **options
    )
