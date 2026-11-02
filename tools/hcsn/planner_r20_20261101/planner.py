"""Batched unchanged predicates with bounded validation-array lifetimes."""

import numpy as np

from ..planner_fastpath_r18_20261101.planner import validate_rows
from ..planner_r19_20261101.planner import OwnedPlanner
from ..support_retention_r16_20261101.compression import COLLECT, SPREAD, GROUP


class BatchOwnedPlanner(OwnedPlanner):
    """Preserve every R18 predicate and C-layout while freeing validation copies.

    Batched predicates avoid R19's repeated Python validation calls. Validation
    concatenations are released before allocating projection outputs, so they
    do not stay live throughout the rest of the helper. All matrix operands
    and posterior normalization retain their original logical shape and order.
    """

    def _project_many(self, arrays):
        merged = (arrays[0].reshape(-1, 40) if len(arrays) == 1 else
                  np.concatenate([p.reshape(-1, 40) for p in arrays], axis=0))
        validate_rows(merged, 40, -1e-13 if self.projection == "full" else 0.)
        del merged
        if self.projection == "full":
            return [np.ascontiguousarray(p) for p in arrays]
        packed = [p @ COLLECT for p in arrays]
        merged_packed = (packed[0].reshape(-1, 8) if len(packed) == 1 else
                         np.concatenate([p.reshape(-1, 8) for p in packed], axis=0))
        validate_rows(merged_packed, 8, 0.)
        del merged_packed
        expanded = [p @ SPREAD for p in packed]
        for p, result in zip(packed, expanded, strict=True):
            if np.any((p[..., GROUP] > 0) & (result == 0)):
                raise ValueError("Positive support is unrepresentable at this floating-point scale")
        return expanded
