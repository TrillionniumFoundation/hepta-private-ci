"""Reset-aligned moving mesh: a point reset stays a point, without smoothing.

Two fixed-topology graded segments meet at r=log(Vr)-B. The mesh moves with
reset/boundary. Fixed nodal masses therefore move in physical space; this is
not a derivative of an externally fixed physical prior unless its migration
Jacobian is also supplied. Delay and relative upper endpoint remain fixed.
"""

from dataclasses import dataclass
import math

import numpy as np

from qualification.hcsn_joint_dde.graded import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel


@dataclass(frozen=True)
class ResetAlignedSpatial(GradedSpatialGenerator):
    reset_location: float = .5
    left_intervals: int = 4

    def __post_init__(self):
        if (type(self.left_intervals) is not int or self.left_intervals < 2 or
                self.intervals-self.left_intervals < 2 or
                not math.isfinite(self.reset_location) or
                not 0 < self.reset_location < self.endpoint):
            raise ValueError("interior point reset and two fixed mesh segments required")
        super().__post_init__()

    @property
    def nodes(self):
        left = np.linspace(0., 1., self.left_intervals+1)
        right = np.linspace(0., 1., self.intervals-self.left_intervals+1)
        if self.grading:
            left = np.expm1(self.grading*left)/math.expm1(self.grading)
            right = np.expm1(self.grading*right)/math.expm1(self.grading)
        reset = self.reset_location
        nodes = np.r_[reset*left, reset+(self.endpoint-reset)*right[1:]]
        nodes[0], nodes[self.left_intervals], nodes[-1] = 0., reset, self.endpoint
        return nodes


def aligned_model(theta, *, left_intervals, right_intervals, endpoint=2.,
                  grading=2., delay=.2, active_reward=.4, hit_reward=1.):
    """Construct model and analytic derivatives of its ACTUAL generator."""
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
    spatial = ResetAlignedSpatial(left_intervals+right_intervals, endpoint, float(mu),
        float(sigma), grading, reset, left_intervals)
    nodes = spatial.nodes
    dx = np.r_[nodes[:left_intervals+1]/reset,
               (endpoint-nodes[left_intervals+1:])/(endpoint-reset)]
    dx[0], dx[left_intervals], dx[-1] = 0., 1., 0.
    model = JointModel(spatial, reset, delay, float(discount), active_reward, hit_reward)
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
