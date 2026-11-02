"""Internal owned-array projection with unchanged R18 Bellman arithmetic."""

import numpy as np

from ..planner_fastpath_r18_20261101.planner import BatchedPlanner, validate_rows
from ..support_retention_r16_20261101.compression import COLLECT, SPREAD, GROUP


class OwnedPlanner(BatchedPlanner):
    """Reduce transient allocations within the read-only Bellman forest.

    Full projection is an identity view only for newly-owned forest arrays.
    All descendants read their arguments; no result aliases public owner state.
    Each matrix operand retains its R18 shape and reduction order.
    """

    def _project_many(self, arrays):
        if self.projection == "full":
            for p in arrays:
                validate_rows(p, 40, -1e-13)
            return arrays
        expanded = []
        for p in arrays:
            validate_rows(p, 40, 0.)
            packed = p @ COLLECT
            validate_rows(packed, 8, 0.)
            result = packed @ SPREAD
            if np.any((packed[..., GROUP] > 0) & (result == 0)):
                raise ValueError("Positive support is unrepresentable at this floating-point scale")
            expanded.append(result)
        return expanded

    def _posteriors(self, before, emission):
        likelihoods, posteriors = [], []
        for p in before:
            joint = p[:, None, :] * emission.T[None, :, :]
            likelihood = joint.sum(-1)
            # The broadcast divisor is a separate reduction result. Every
            # nonpositive-likelihood row is completely replaced below.
            np.divide(joint, likelihood[..., None], out=joint,
                      where=likelihood[..., None] > 0)
            joint[likelihood <= 0] = self.law.prior
            likelihoods.append(likelihood)
            posteriors.append(joint)
        return likelihoods, self._project_many(posteriors)
