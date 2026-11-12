"""Exploratory fixed split grading, independent of the frozen common operator.

The point reset remains an exact moving node. This changes the discretization;
it does not close continuum rare-event accuracy or supply a Torch adapter.
"""

from dataclasses import dataclass
import math

import numpy as np

from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_reset_aligned.mesh import ResetAlignedSpatial


@dataclass(frozen=True)
class SplitResetAlignedSpatial(ResetAlignedSpatial):
    right_grading: float | None = None

    def __post_init__(self):
        if self.right_grading is not None and (
                isinstance(self.right_grading, bool) or
                not isinstance(self.right_grading, (int, float)) or
                not math.isfinite(self.right_grading) or not 0 <= self.right_grading <= 6):
            raise ValueError("fixed right grading must be in [0,6] or inherit left grading")
        super().__post_init__()

    @property
    def nodes(self):
        nodes = super().nodes
        if self.right_grading is None:
            return nodes
        right = np.linspace(0., 1., self.intervals-self.left_intervals+1)
        if self.right_grading:
            right = np.expm1(self.right_grading*right)/math.expm1(self.right_grading)
        nodes[self.left_intervals:] = self.reset_location+(self.endpoint-self.reset_location)*right
        nodes[self.left_intervals], nodes[-1] = self.reset_location, self.endpoint
        return nodes


def split_model(theta, *, left_intervals, right_intervals, endpoint=2.,
                grading=2., right_grading=None, delay=.2, active_reward=.4, hit_reward=1.):
    """Return this model and five physical derivatives at fixed moving weights.

    The small derivative formula is intentionally isolated from the qualified
    common implementation; no common source or frozen manifest is modified.
    """
    values = np.asarray(theta, dtype=float)
    if values.shape != (5,) or not np.isfinite(values).all():
        raise ValueError("five finite physical values required")
    if (any(type(x) is not int or x < 2 for x in (left_intervals, right_intervals))
            or left_intervals+right_intervals > 512 or not math.isfinite(grading)
            or not 0 <= grading <= 6):
        raise ValueError("bounded fixed mesh topology and grading required")
    boundary, mu, sigma, absolute_reset, discount = values
    if absolute_reset <= 0:
        raise ValueError("positive absolute reset required")
    reset = math.log(absolute_reset)-boundary
    if not 0 < reset < endpoint:
        raise ValueError("reset must remain strictly between the boundaries")
    spatial = SplitResetAlignedSpatial(left_intervals+right_intervals, endpoint, float(mu),
        float(sigma), grading, reset, left_intervals, right_grading)
    model = JointModel(spatial, reset, delay, float(discount), active_reward, hit_reward)
    nodes = spatial.nodes
    dx = np.r_[nodes[:left_intervals+1]/reset,
               (endpoint-nodes[left_intervals+1:])/(endpoint-reset)]
    dx[0], dx[left_intervals], dx[-1] = 0., 1., 0.
    hl, hr = np.diff(nodes)[:-1], np.diff(nodes)[1:]
    dl, dr = np.diff(dx)[:-1], np.diff(dx)[1:]
    total, dt = hl+hr, dl+dr
    down, up = spatial.rates
    down_r = -mu*dr/(hl*total)-down*(dl/hl+dt/total)
    up_r = mu*dl/(hr*total)-up*(dr/hr+dt/total)
    derivatives = np.zeros((5, len(nodes), len(nodes)))
    indices = np.arange(1, len(nodes)-1)
    for j, low, high in (
        (0, -down_r, -up_r),
        (1, -hr/(hl*total), hl/(hr*total)),
        (2, 2*sigma/(hl*total), 2*sigma/(hr*total)),
        (3, down_r/absolute_reset, up_r/absolute_reset),
    ):
        derivatives[j, indices, indices-1] = low
        derivatives[j, indices, indices+1] = high
        derivatives[j, indices, indices] = -low-high
    return model, derivatives
