"""Auditable diffusion, optimal stopping, and renewal operators.

These numerical reference operators do not certify learning or hardware efficacy.
"""

from .hitting import (
    HitReadout,
    hit_probability_and_gradient,
    hit_readout,
    hit_sensitivities,
)
from .roots import DiffusionRoots, stable_roots

__all__ = [
    "DiffusionRoots",
    "HitReadout",
    "hit_probability_and_gradient",
    "hit_readout",
    "hit_sensitivities",
    "stable_roots",
]
