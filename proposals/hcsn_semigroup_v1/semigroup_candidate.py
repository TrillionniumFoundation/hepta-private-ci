"""Research-only finite-volume generator comparator for killed log diffusion.

Not an HCSN production kernel: no regenerative refractory state, observation
updates, content or differentiable trainable parameters. The far right boundary
is reflecting; the underlying continuum first-passage reference lives on
(0, infinity). Report their mismatch rather than treating this as a proof of
full-domain accuracy or a fix for the archived QPR pressure failures.
"""

from dataclasses import dataclass
import math

import torch


@dataclass(frozen=True)
class GeneratorTrial:
    q: torch.Tensor  # substochastic generator, transient active centers
    absorption: torch.Tensor  # nonnegative per-state left-boundary exit rate
    centers: torch.Tensor  # midpoint distances from the absorbing boundary


def bernoulli_flux(z: float) -> float:
    """Positive exponentially fitted Bernoulli function z/(exp(z)-1)."""
    if not math.isfinite(z):
        raise ValueError("finite Péclet number required")
    if abs(z) < 1e-6:
        return 1.0 - z / 2.0 + z * z / 12.0 - z**4 / 720.0
    if z > 50.0:
        return z * math.exp(-z) / -math.expm1(-z)
    if z < -50.0:
        return -z / -math.expm1(z)
    return z / math.expm1(z)


def generator_trial(active_cells: int, endpoint: float, mu: float, sigma: float) -> GeneratorTrial:
    """Positive finite-volume rates with absorbing left, reflecting right.

    The generator is independent of any requested time step. For fixed Q,
    exp(Q*t) composes as a semigroup, unlike repeated QPR reprojection.
    """
    if (type(active_cells) is not int or not 4 <= active_cells <= 256
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   for v in (endpoint, mu, sigma))
            or not 0 < endpoint <= 8 or not -2 <= mu <= 2 or not .05 <= sigma <= 2):
        raise ValueError("fixed FP64 research grid and diffusion parameters required")
    diffusivity = sigma**2 / 2.0
    spacing = endpoint / active_cells
    pe = mu * spacing / diffusivity
    up = diffusivity / spacing**2 * bernoulli_flux(-pe)
    down = diffusivity / spacing**2 * bernoulli_flux(pe)
    absorption = 2.0 * diffusivity / spacing**2 * bernoulli_flux(pe / 2.0)
    if not all(math.isfinite(v) and v >= 0 for v in (up, down, absorption)):
        raise FloatingPointError("unresolved nonnegative finite generator rates")
    q = torch.zeros((active_cells, active_cells), dtype=torch.float64)
    k = torch.zeros(active_cells, dtype=torch.float64)
    k[0] = absorption
    for i in range(active_cells):
        if i < active_cells - 1:
            q[i, i + 1] = up
            q[i, i] -= up
        if i > 0:
            q[i, i - 1] = down
            q[i, i] -= down
        else:
            q[0, 0] -= absorption
    centers = (torch.arange(active_cells, dtype=torch.float64) + 0.5) * spacing
    return GeneratorTrial(q, k, centers)


def discounted_hit_transform(trial: GeneratorTrial, discount: float) -> torch.Tensor:
    """Exact resolvent of the finite-state CTMC, not the continuum law."""
    if (type(discount) not in (int, float) or not math.isfinite(discount)
            or discount <= 0):
        raise ValueError("fixed positive discount required")
    n = trial.centers.numel()
    result = torch.linalg.solve(
        discount * torch.eye(n, dtype=torch.float64) - trial.q,
        trial.absorption,
    )
    if not bool(torch.isfinite(result).all()) or bool((result < 0).any()) or bool((result > 1 + 1e-10).any()):
        raise FloatingPointError("discounted hitting transform not qualified")
    return result


def continuum_hit_transform(distance: torch.Tensor, mu: float, sigma: float, discount: float) -> torch.Tensor:
    """Independent infinite-half-line Brownian first-hit Laplace transform.

    The negative-mu root is rationalized to avoid cancellation near zero
    discount. This is a fixed-parameter analytic comparator, not a gradient.
    """
    root = math.sqrt(mu * mu + 2 * discount * sigma * sigma)
    beta = 2 * discount / (root - mu) if mu < 0 else (root + mu) / sigma**2
    return torch.exp(-beta * distance)


def probe(active_cells: int = 128) -> dict:
    """Measure five prescribed drift regimes; interior and far-field separate."""
    rows = []
    for mu in (-0.8, -0.12, 0.0, 0.12, 0.8):
        trial = generator_trial(active_cells, 4.8, mu, 0.35)
        observed = discounted_hit_transform(trial, 0.15)
        reference = continuum_hit_transform(trial.centers, mu, 0.35, 0.15)
        error = (observed - reference).abs()
        rows.append({
            "mu": mu,
            "interior_max_absolute_error_x_lt_2": float(error[trial.centers < 2].max()),
            "full_grid_max_absolute_error": float(error.max()),
            "subgenerator_row_balance": float((trial.q.sum(-1) + trial.absorption).abs().max()),
            "min_laplace": float(observed.min()),
            "max_laplace": float(observed.max()),
        })
    trial = generator_trial(16, 2.0, -0.12, 0.35)
    transition = torch.matrix_exp(0.001 * trial.q)
    direct = torch.matrix_exp(0.002 * trial.q)
    return {
        "schema": "hcsn-sg-generator-comparator-v1",
        "model": "finite-volume active killed diffusion, reflecting artificial upper boundary",
        "reference": "infinite-half-line constant-drift discounted first passage",
        "active_cells": active_cells,
        "endpoint": 4.8,
        "sigma": 0.35,
        "discount": 0.15,
        "rows": rows,
        "semigroup_16cell_2x_0p001_max_abs": float((transition @ transition - direct).abs().max()),
        "production_admission": False,
        "whole_training_domain_admission": False,
        "scientific_benefit_established": False,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(probe(), sort_keys=True, indent=2, allow_nan=False))
