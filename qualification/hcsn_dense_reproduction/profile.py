"""New-identity reconstruction of two fixed near-dense profiles.

No file is attributed to the lost v3 execution. Far upper escape remains
permanently active and nonreturning. No gradient qualification is inherited.
"""

from dataclasses import dataclass
import math
import numpy as np
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from .controlled_core import JointModel as ControlledJointModel


@dataclass(frozen=True)
class NearDenseGenerator(GradedSpatialGenerator):
    near_intervals: int = 800
    near_endpoint: float = 0.5

    def __post_init__(self):
        if (type(self.near_intervals) is not int
                or not 1 <= self.near_intervals < self.intervals
                or isinstance(self.near_endpoint, bool)
                or not isinstance(self.near_endpoint, (int, float))
                or not math.isfinite(self.near_endpoint)
                or not 0 < self.near_endpoint < self.endpoint
                or not self.stretch > 0):
            raise ValueError("bounded near/far geometry required")
        super().__post_init__()

    @property
    def nodes(self):
        near = np.linspace(0.0, self.near_endpoint, self.near_intervals + 1)
        far_unit = np.linspace(0.0, 1.0, self.intervals - self.near_intervals + 1)
        far = self.near_endpoint + (self.endpoint - self.near_endpoint) * (
            np.expm1(self.stretch * far_unit) / math.expm1(self.stretch))
        result = np.r_[near, far[1:]]
        result[-1] = self.endpoint
        result.setflags(write=False)
        return result


@dataclass(frozen=True)
class ControlledModel(GradedJointModel):
    # This private copy changes only accepted atol, from 1e-14 to 1e-18.
    solve = ControlledJointModel.solve
