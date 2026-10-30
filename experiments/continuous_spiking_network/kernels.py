"""Brownian first-passage kernels with frozen coefficients within each interval.

These are exact for one constant upper barrier and a scalar Brownian motion.
They do not solve a moving-boundary or a continuously coupled feedback process.
"""

import math

import torch
from torch import Tensor


def first_passage_terms(
    distance: Tensor, drift: Tensor, diffusion: Tensor, horizon: Tensor
) -> dict[str, Tensor]:
    """Return P(tau <= t), survival, and the reflected-density mass.

    ``distance`` is the upper barrier minus the initial state; ``diffusion``
    is the standard deviation per square root of time, not its variance.
    A nonpositive distance means an immediate event, including at t=0.
    """
    distance, drift, diffusion, horizon = torch.broadcast_tensors(
        distance, drift, diffusion, horizon
    )
    if bool((diffusion <= 0).any()) or bool((horizon < 0).any()):
        raise ValueError("diffusion must be positive and horizon nonnegative")
    tiny = torch.finfo(distance.dtype).tiny
    d = distance.clamp_min(tiny)
    t = horizon.clamp_min(torch.finfo(horizon.dtype).eps)
    scale = diffusion * t.sqrt()
    z = (drift * t - d) / scale
    reflected_z = (-drift * t - d) / scale
    # exp(2*mu*d/sigma^2)*Phi(reflected_z) would overflow before multiplication.
    # The erfcx identity also avoids cancellation of two large exponents.
    log_image_mills = (
        -math.log(2.0)
        - 0.5 * z.square()
        + torch.special.erfcx((-reflected_z / math.sqrt(2.0)).clamp_min(0)).log()
    )
    log_image_direct = 2 * drift * d / diffusion.square() + torch.special.log_ndtr(
        reflected_z
    )
    log_image = torch.where(reflected_z <= 0, log_image_mills, log_image_direct)
    log_cdf = torch.logaddexp(torch.special.log_ndtr(z), log_image).clamp_max(0)
    active = (distance > 0) & (horizon > 0)
    cdf = torch.where(active, log_cdf.exp(), (distance <= 0).to(distance.dtype))
    survival = torch.where(
        active, -torch.expm1(log_cdf), (distance > 0).to(distance.dtype)
    )
    image = torch.where(active, log_image.exp(), torch.zeros_like(distance))
    return {"cdf": cdf, "survival": survival, "image_mass": image}


def first_passage_cdf(
    distance: Tensor, drift: Tensor, diffusion: Tensor, horizon: Tensor
) -> Tensor:
    return first_passage_terms(distance, drift, diffusion, horizon)["cdf"]


def first_passage_density(
    distance: Tensor, drift: Tensor, diffusion: Tensor, horizon: Tensor
) -> Tensor:
    """Inverse-Gaussian first-passage density, possibly with defective mass."""
    distance, drift, diffusion, horizon = torch.broadcast_tensors(
        distance, drift, diffusion, horizon
    )
    if bool((diffusion <= 0).any()) or bool((horizon < 0).any()):
        raise ValueError("diffusion must be positive and horizon nonnegative")
    tiny = torch.finfo(distance.dtype).tiny
    d = distance.clamp_min(tiny)
    t = horizon.clamp_min(torch.finfo(horizon.dtype).eps)
    log_density = (
        d.log()
        - diffusion.log()
        - 1.5 * t.log()
        - 0.5 * math.log(2 * math.pi)
        - (d - drift * t).square() / (2 * diffusion.square() * t)
    )
    return torch.where(
        (distance > 0) & (horizon > 0), log_density.exp(), torch.zeros_like(d)
    )


def reset_at_interval_end_mean(
    state: Tensor,
    boundary: Tensor,
    drift: Tensor,
    diffusion: Tensor,
    horizon: Tensor,
    reset: float = 0.0,
) -> tuple[Tensor, dict[str, Tensor]]:
    """Exact killed-process first moment with hit mass reset at interval end.

    This is not an exact continuously restarting process: repeated within-step
    events and post-hit evolution are intentionally excluded by this contract.
    """
    distance = boundary - state
    terms = first_passage_terms(distance, drift, diffusion, horizon)
    mean = (
        (state + drift * horizon) * terms["survival"]
        - 2 * distance.clamp_min(0) * terms["image_mass"]
        + reset * terms["cdf"]
    )
    return mean, terms
