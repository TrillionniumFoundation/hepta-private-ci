"""Graded-node v2 geometry for the unchanged joint probability/content DDE.

This new candidate overrides every uniform-node assumption. It inherits the
actual flux-history delay/reset integrator, not any prior numerical admission.
"""

from dataclasses import dataclass
import math

import numpy as np

from qualification.hcsn_joint_dde.model import JointModel
from .spatial import GradedSpatialGenerator


@dataclass(frozen=True)
class GradedJointModel(JointModel):
    def __post_init__(self):
        if not isinstance(self.spatial, GradedSpatialGenerator):
            raise ValueError("graded spatial generator required")
        for name in ("reset", "delay", "discount", "active_reward", "hit_reward"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("finite fixed model parameters required")
        nodes = self.spatial.nodes
        if (
            not nodes[1] <= self.reset <= nodes[-2]
            or not 0 < self.delay <= 2
            or not 0.001 <= self.discount <= 4
            or self.active_reward < 0
            or self.hit_reward < 0
        ):
            raise ValueError("graded reset stencil/domain invalid")

    def ingredients(self):
        matrix = self.spatial.matrix()
        nodes = self.spatial.nodes
        left = min(
            int(np.searchsorted(nodes, self.reset, side="right")) - 1, len(nodes) - 2
        )
        fraction = (self.reset - nodes[left]) / (nodes[left + 1] - nodes[left])
        reset = np.zeros(len(nodes))
        reset[left], reset[left + 1] = 1 - fraction, fraction
        return matrix[1:-1, 1:-1], matrix[1:-1, 0], matrix[1:-1, -1], reset[1:-1]

    def perpetual(self):
        phi = self.spatial.discounted_lower_hit(self.discount)
        reset_phi = float(np.interp(self.reset, self.spatial.nodes, phi))
        base = self.active_reward / self.discount
        eta = math.exp(-self.discount * self.delay)
        reset_value = (base * (1 - reset_phi) + self.hit_reward * reset_phi) / (
            1 - eta * reset_phi
        )
        return base + phi * (self.hit_reward + eta * reset_value - base), reset_value
