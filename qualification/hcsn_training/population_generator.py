"""Conservative finite-volume transport for the opt-in physical-time B profile.

The two boundary accounts are absorbing first exits. This spatial generator is
an upwind approximation: its matrix exponential is time-consistent for frozen
face drift, but neither the spatial grid nor nonlinear drift freezing is exact.
"""

import math

import torch
from torch.nn import functional as F


def finite_volume_generator(edges, face_drift, sigma):
    """Return a row generator with active bins followed by hit and escape.

    Uniform cell averages use D/h² diffusion between neighbouring centres.
    Absorbing boundary faces are half a cell from the terminal centres, giving
    2D/h² diffusion to their cemetery accounts. Upwind drift is evaluated at
    each face. The last two rows are zero, so all exit mass remains accounted.
    """
    if (edges.ndim != 1 or len(edges) < 3 or face_drift.shape[-1] != len(edges)
            or edges.dtype != face_drift.dtype or edges.device != face_drift.device
            or type(sigma) not in (int, float) or not math.isfinite(sigma) or sigma <= 0):
        raise ValueError("invalid finite-volume grid, face drift or diffusion")
    widths = edges[1:]-edges[:-1]
    width = (edges[-1]-edges[0])/len(widths)
    if (not bool(torch.isfinite(edges).all()) or not bool(torch.isfinite(face_drift).all())
            or not bool(width > 0) or not bool(torch.allclose(widths, width.expand_as(widths)))):
        raise ValueError("finite-volume grid must be finite, uniform and increasing")
    bins, diffusion = len(widths), sigma**2/(2*width**2)
    left = torch.relu(-face_drift[..., :-1])/width+diffusion
    right = torch.relu(face_drift[..., 1:])/width+diffusion
    left = left+F.pad(diffusion.reshape(1), (0, bins-1))
    right = right+F.pad(diffusion.reshape(1), (bins-1, 0))
    transient = (-torch.diag_embed(left+right)+torch.diag_embed(left[..., 1:], offset=-1)
                 + torch.diag_embed(right[..., :-1], offset=1))
    hit = F.pad(left[..., :1], (0, bins-1))
    escape = F.pad(right[..., -1:], (bins-1, 0))
    return F.pad(torch.cat((transient, hit[..., None], escape[..., None]), -1), (0, 0, 0, 2))


def finite_volume_transition(edges, face_drift, sigma, dt):
    """Return active-to-active, hit and escape probabilities without renormalizing."""
    if type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0:
        raise ValueError("finite positive transition duration required")
    bins = len(edges)-1
    transition = torch.matrix_exp(finite_volume_generator(edges, face_drift, sigma)*dt)
    return transition[..., :bins, :bins], transition[..., :bins, bins], transition[..., :bins, bins+1]
