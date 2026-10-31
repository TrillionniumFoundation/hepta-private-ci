"""Finite CTMC alternatives with an explicit continuum-resolution diagnostic.

Scharfetter--Gummel preserves the exponential equilibrium ratio for constant
drift; it does NOT remove low-noise coarse-mesh artificial diffusion.
"""

import math

import numpy as np
from scipy.linalg import expm
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import expm_multiply
from scipy.special import exprel

from .event_kernel import DomainError


class ResolutionError(ValueError):
    """The finite generator has not met the requested local moment accuracy."""


def rates(drift, sigma, spacing, scheme="fitted"):
    drift = np.asarray(drift, dtype=float)
    if (not np.all(np.isfinite(drift)) or not math.isfinite(sigma + spacing)
            or sigma <= 0 or spacing <= 0):
        raise DomainError("Finite drift and positive noise/spacing required")
    diffusion = sigma**2 / (2 * spacing**2)
    if scheme == "upwind":
        up = diffusion + np.maximum(drift, 0) / spacing
        down = diffusion + np.maximum(-drift, 0) / spacing
    elif scheme == "fitted":
        peclet = 2 * drift * spacing / sigma**2
        # B(z)=z/expm1(z)=1/exprel(z); handles zero and the large-z limit.
        with np.errstate(over="ignore"):
            up, down = diffusion / exprel(-peclet), diffusion / exprel(peclet)
    else:
        raise DomainError("scheme must be 'upwind' or 'fitted'")
    if not np.all(np.isfinite(up + down)):
        raise DomainError("Unrepresentable finite-generator rates")
    effective_variance = spacing**2 * (up + down)
    return dict(up=up, down=down, represented_drift=spacing * (up - down),
                effective_variance=effective_variance,
                extra_variance_ratio=effective_variance / sigma**2 - 1,
                mesh_peclet=2 * np.abs(drift) * spacing / sigma**2)


def require_local_resolution(diagnostics, maximum_extra_variance_ratio=0.05):
    """Necessary local-moment gate; passing is not a first-passage certificate."""
    if not math.isfinite(maximum_extra_variance_ratio) or maximum_extra_variance_ratio <= 0:
        raise DomainError("A positive finite resolution budget is required")
    measured = float(np.max(diagnostics["extra_variance_ratio"]))
    if measured > maximum_extra_variance_ratio:
        raise ResolutionError(f"Extra variance ratio {measured:.8g} exceeds {maximum_extra_variance_ratio:.8g}")
    return dict(passed=True, maximum_extra_variance_ratio=measured,
                scope="interior local moments only; independent first-passage validation still required")


def absorbing_generator(drift, sigma, boundary=1.0, n_grid=15, *, leak=0.0, scheme="fitted"):
    """Row-source nearest-neighbor CTMC on (-b,b), followed by plus/minus sinks."""
    if (type(n_grid) is not int or n_grid < 5 or n_grid % 2 != 1 or n_grid > 8191
            or not math.isfinite(boundary + leak) or boundary <= 0 or leak < 0):
        raise DomainError("Odd grid in [5,8191], positive boundary and nonnegative leak required")
    h = 2 * boundary / (n_grid + 1)
    x = -boundary + h * np.arange(1, n_grid + 1)
    diagnostics = rates(drift - leak * x, sigma, h, scheme)
    up, down = diagnostics["up"], diagnostics["down"]
    source = np.arange(n_grid)
    plus = np.where(source + 1 < n_grid, source + 1, n_grid)
    minus = np.where(source > 0, source - 1, n_grid + 1)
    matrix = coo_matrix((np.concatenate((up, down, -up-down)),
        (np.tile(source, 3), np.concatenate((plus, minus, source)))),
        shape=(n_grid + 2, n_grid + 2)).tocsr()
    return dict(matrix=matrix, nodes=x, spacing=h, diagnostics=diagnostics,
                scheme=scheme, continuum_claim=False)


def first_exit(flow, duration):
    """First absorption from the exact zero node in the stated finite CTMC."""
    if not math.isfinite(duration) or duration < 0:
        raise DomainError("Nonnegative finite physical duration required")
    n = len(flow["nodes"])
    initial = np.zeros(n + 2)
    initial[n // 2] = 1
    probability = expm_multiply(duration * flow["matrix"].T, initial)
    if np.min(probability) < -2e-13 or abs(probability.sum() - 1) > 1e-9:
        raise ArithmeticError("Finite semigroup violates its numerical probability budget")
    return dict(plus=float(probability[n]), minus=float(probability[n+1]),
                survival=float(probability[:n].sum()), mass_error=float(probability.sum()-1))


def erlang_recovery(mean_seconds, phases, duration):
    """Physical-time phase chain plus a ready sink; can recover inside any tick."""
    if (type(phases) is not int or not 1 <= phases <= 64
            or not math.isfinite(mean_seconds + duration) or mean_seconds <= 0 or duration < 0):
        raise DomainError("Positive mean seconds, 1..64 phases and nonnegative duration required")
    rate = phases / mean_seconds
    q = np.zeros((phases + 1, phases + 1))
    for i in range(phases):
        q[i, i], q[i, i+1] = -rate, rate
    return expm(duration * q)


def recovery_discount(mean_seconds, phases, discount):
    """Laplace transform of the actual Erlang recovery duration."""
    if (type(phases) is not int or phases < 1 or phases > 64
            or not math.isfinite(mean_seconds + discount) or mean_seconds <= 0 or discount < 0):
        raise DomainError("Positive mean, 1..64 phases and nonnegative discount required")
    return math.exp(-phases * math.log1p(discount * mean_seconds / phases))


def hazard_from_reference_release(probability, reference_seconds):
    """Match one reference-window release probability, not the legacy tick law."""
    if not 0 < probability < 1 or not math.isfinite(reference_seconds) or reference_seconds <= 0:
        raise DomainError("Probability in (0,1) and positive reference seconds required")
    return -math.log1p(-probability) / reference_seconds
