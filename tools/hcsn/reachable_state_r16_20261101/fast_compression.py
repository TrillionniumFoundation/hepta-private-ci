"""Vectorized implementation of the existing grouped projection contract.

This is the same mathematical approximation as compression.py. It validates
the input once, constructs group sums in one reduction, and gathers each
phase's conditional content vector. It does not implement reduced-state
propagation, change Q, or bypass precision failures.
"""

import numpy as np

from .compression import GROUPS, ProjectionLaw, ProjectionPrecisionError


LAYOUT = {name: (np.array([group[0] for group in groups]),
                 np.repeat(np.arange(len(groups)), [len(group) for group in groups]))
          for name, groups in GROUPS.items()}


def fast_project(p, mode="block2"):
    if mode not in LAYOUT:
        raise ValueError("Unknown grouped projection")
    p = np.asarray(p, dtype=np.float64)
    if p.ndim < 1 or p.shape[-1] != 40:
        raise ValueError("Expected a nonnegative normalized 40-state belief")
    joint = p.reshape(*p.shape[:-1], 10, 4)
    phase = joint.sum(-1)
    if (not np.isfinite(p).all() or np.any(p < 0)
            or np.any(abs(p.sum(-1) - 1.) > 2e-11)
            or np.any(abs(phase.sum(-1) - 1.) > 2e-11)):
        raise ValueError("Expected a nonnegative normalized 40-state belief")
    starts, group_for_phase = LAYOUT[mode]
    content = np.add.reduceat(joint, starts, axis=-2)
    mass = content.sum(-1, keepdims=True)
    with np.errstate(under="ignore"):
        conditional = np.divide(content, mass, out=np.zeros_like(content), where=mass > 0)
        per_phase = conditional[..., group_for_phase, :]
        result = phase[..., :, None] * per_phase
    # Preserve both original support and the represented Cartesian support,
    # including the old decode() rejection of underflow in newly added pairs.
    positive = (joint > 0) | ((phase[..., :, None] > 0) & (per_phase > 0))
    if np.any(positive & (result == 0)):
        raise ProjectionPrecisionError("Grouped projection support is not representable in float64")
    return result.reshape(p.shape)


class FastProjectionLaw(ProjectionLaw):
    def project(self, p, mode="full"):
        return fast_project(p, mode) if mode in GROUPS else self.base.project(p, mode)
