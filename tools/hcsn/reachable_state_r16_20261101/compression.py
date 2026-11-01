"""Support-preserving grouped compression of the frozen R15 joint belief.

This module changes the belief representation, never the generator, emissions,
reward, observation prices, or hidden world.  The lifted result still has 40
entries.  Reduced storage is implemented; reduced-dimensional propagation and
planning are not, so this module makes no inference-speed claim.
"""

from dataclasses import dataclass

import numpy as np


GROUPS = {
    "block2": (tuple(range(8)), (8, 9)),
    "block4": ((0, 1, 2), (3, 4, 5), (6, 7), (8, 9)),
    "block5": ((0, 1), (2, 3), (4, 5), (6, 7), (8, 9)),
}


class ProjectionPrecisionError(FloatingPointError):
    """The mathematical positive support cannot be represented in float64."""


@dataclass(frozen=True)
class CompressedBelief:
    """Phase masses and conditional content probabilities in each phase group.

    Arrays are read-only.  The grouping is an explicit part of the state format.
    The content conditional of an empty group is the all-zero vector.
    """

    mode: str
    phase: np.ndarray
    conditional: np.ndarray

    @property
    def nbytes(self):
        return self.phase.nbytes + self.conditional.nbytes


def encode(p, mode="block2"):
    """Encode a nonnegative, normalized (..., 40) belief without smoothing."""
    if mode not in GROUPS:
        raise ValueError("Unknown grouped projection")
    p = np.asarray(p, dtype=np.float64)
    if (p.ndim < 1 or p.shape[-1] != 40 or not np.isfinite(p).all()
            or np.any(p < 0)
            or not np.allclose(p.sum(-1), 1., rtol=0, atol=2e-11)):
        raise ValueError("Expected a nonnegative normalized 40-state belief")
    joint = p.reshape(*p.shape[:-1], 10, 4)
    phase = joint.sum(-1)
    conditional = np.zeros((*p.shape[:-1], len(GROUPS[mode]), 4))
    for group_index, indices in enumerate(GROUPS[mode]):
        content = joint[..., indices, :].sum(-2)
        mass = content.sum(-1, keepdims=True)
        with np.errstate(under="ignore"):
            np.divide(content, mass, out=conditional[..., group_index, :],
                      where=mass > 0)
    # Multiplication is deliberately checked now, before an encoded checkpoint
    # can claim to preserve a support that its float64 lift would erase.
    for group_index, indices in enumerate(GROUPS[mode]):
        with np.errstate(under="ignore"):
            lifted = (phase[..., indices, None]
                      * conditional[..., group_index, None, :])
        if np.any((joint[..., indices, :] > 0) & (lifted == 0)):
            raise ProjectionPrecisionError(
                "Grouped projection underflows a positive input coordinate")
    phase.setflags(write=False)
    conditional.setflags(write=False)
    return CompressedBelief(mode, phase, conditional)


def decode(state):
    """Lift a validated compressed state to a 40-entry float64 belief."""
    if not isinstance(state, CompressedBelief) or state.mode not in GROUPS:
        raise ValueError("Unknown compressed belief format")
    phase = np.asarray(state.phase, dtype=np.float64)
    conditional = np.asarray(state.conditional, dtype=np.float64)
    if (phase.ndim < 1 or phase.shape[-1] != 10
            or conditional.shape != (*phase.shape[:-1], len(GROUPS[state.mode]), 4)
            or not np.isfinite(phase).all() or not np.isfinite(conditional).all()
            or np.any(phase < 0) or np.any(conditional < 0)
            or not np.allclose(phase.sum(-1), 1., rtol=0, atol=2e-11)):
        raise ValueError("Invalid compressed belief arrays")
    result = np.zeros((*phase.shape[:-1], 10, 4))
    for group_index, indices in enumerate(GROUPS[state.mode]):
        mass = phase[..., indices].sum(-1)
        distribution = conditional[..., group_index, :]
        if (np.any((mass == 0)[..., None] & (distribution != 0))
                or np.any((mass > 0)
                          & (np.abs(distribution.sum(-1) - 1.) > 2e-11))):
            raise ValueError("Invalid conditional content probabilities")
        with np.errstate(under="ignore"):
            lifted = phase[..., indices, None] * distribution[..., None, :]
        # Check the represented Cartesian support, including newly admitted
        # combinations, rather than silently dropping subnormal coordinates.
        if np.any((phase[..., indices, None] > 0)
                  & (distribution[..., None, :] > 0) & (lifted == 0)):
            raise ProjectionPrecisionError(
                "Compressed Cartesian support is not representable in float64")
        result[..., indices, :] = lifted
    return result.reshape(*phase.shape[:-1], 40)


def project(p, mode="block2"):
    """Return C(p)[i,c] = p[i,.] p[group(i),c] / p[group(i),.]."""
    return decode(encode(p, mode))


def metadata(mode):
    """Explicit state size, intrinsic dimension, and computation scope."""
    groups = GROUPS[mode]
    return dict(mode=mode, groups=[list(x) for x in groups],
                stored_float64_per_address=10 + 4 * len(groups),
                degrees_of_freedom_interior=9 + 3 * len(groups),
                lifted_float64_per_address=40,
                preserves_phase_marginal=True,
                preserves_group_content_marginal=True,
                preserves_r15_current_emission_likelihoods=True,
                propagates_and_plans_in_lifted_40_states=True)


class ProjectionLaw:
    """Add named projections to an existing frozen R15 Law by delegation.

    ``identity`` and ``operator_identity`` are delegated unchanged.  Callers must
    record the projection mode separately, as R15 BeliefMemory checkpoints do.
    No projection is applied unless explicitly requested by the caller.
    """

    def __init__(self, law):
        self.base = law

    def __getattr__(self, name):
        return getattr(self.base, name)

    def project(self, p, mode="full"):
        if mode in GROUPS:
            return project(p, mode)
        return self.base.project(p, mode)
