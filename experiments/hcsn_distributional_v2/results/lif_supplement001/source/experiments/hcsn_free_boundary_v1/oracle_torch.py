"""Differentiable bridge for the stationary scalar oracle.

Only the boundary uses a custom implicit backward. First-passage outputs are
for one interval with frozen coefficients and an absorbing upper boundary.
They do not silently include repeated resets or a changing neural state.
"""

import torch


def kappa(mu, sigma, rho):
    """Stable positive characteristic root for sigma > 0, rho > 0."""
    omega = torch.sqrt(mu.square() + 2 * rho * sigma.square())
    positive = 2 * rho / (omega + mu.clamp_min(0))
    negative = (omega - mu) / sigma.square()
    return torch.where(mu >= 0, positive, negative)


class _ImplicitBoundary(torch.autograd.Function):
    @staticmethod
    def forward(ctx, mu, sigma, rho, K, r, tau):
        if not all(torch.isfinite(t).all().item() for t in (mu, sigma, rho, K, r, tau)):
            raise ValueError("Boundary parameters must be finite.")
        if not ((sigma > 0).all() and (rho > 0).all() and (r < K).all() and (tau >= 0).all()):
            raise ValueError("Require sigma > 0, rho > 0, r < K, tau >= 0.")
        ctx.output_dtype = mu.dtype
        mu64, sigma64, rho64, K64, r64, tau64 = [t.to(torch.float64) for t in (mu, sigma, rho, K, r, tau)]
        kap = kappa(mu64, sigma64, rho64)
        a = rho64 * tau64 + kap * (K64 - r64)
        lo, hi = torch.zeros_like(a), torch.ones_like(a)
        start = torch.sqrt(2 * a)
        y = start / (1 + start)
        for _ in range(32):
            exponent = -a - y
            f = y + torch.expm1(exponent)
            derivative = -torch.expm1(exponent)
            hi = torch.where(f > 0, y, hi)
            lo = torch.where(f < 0, y, lo)
            proposed = y - f / derivative
            proposed = torch.where((proposed > lo) & (proposed < hi), proposed, (lo + hi) / 2)
            y = torch.where(f == 0, y, proposed)
        q = torch.exp(-a - y)
        one_minus_q = -torch.expm1(-a - y)
        ctx.save_for_backward(mu64, sigma64, rho64, K64, r64, tau64, kap, y, q, one_minus_q)
        return (K64 + y / kap).to(ctx.output_dtype)

    @staticmethod
    def backward(ctx, grad_output):
        mu, sigma, rho, K, r, tau, kap, y, q, one_minus_q = ctx.saved_tensors
        omega = torch.sqrt(mu.square() + 2 * rho * sigma.square())
        jacobian = kap * one_minus_q
        displacement = y / kap
        sensitivity = displacement - q * (displacement + K - r)
        kap_mu = -kap / omega
        kap_sigma = -sigma * kap.square() / omega
        kap_rho = 1 / omega
        derivatives = (-sensitivity * kap_mu / jacobian,
                       -sensitivity * kap_sigma / jacobian,
                       (-sensitivity * kap_rho + tau * q) / jacobian,
                       kap / jacobian, -kap * q / jacobian, rho * q / jacobian)
        return tuple((grad_output.to(torch.float64) * d).to(ctx.output_dtype) for d in derivatives)


def free_boundary(mu, sigma, rho, K, r, tau):
    """Return b with implicit gradients in all six broadcast parameters.

    This custom backward supports first derivatives; higher-order derivatives
    through the detached root are not implemented or certified.
    """
    return _ImplicitBoundary.apply(*torch.broadcast_tensors(mu, sigma, rho, K, r, tau))


def analytic_value(x, mu, sigma, rho, K, r, tau, boundary=None):
    """Optimal stationary value (the supplied boundary must be optimal)."""
    b = free_boundary(mu, sigma, rho, K, r, tau) if boundary is None else boundary
    kap = kappa(mu, sigma, rho)
    displacement = x - b
    continuation = torch.exp(kap * displacement.clamp_max(0)) / kap
    return torch.where(displacement < 0, continuation, displacement + 1 / kap)


def first_passage_terms(distance, mu, sigma, horizon):
    """Return (cdf, survival, image_mass) for the first upper crossing.

    distance = b - x. If distance <= 0 there is an initial-hit atom. If
    horizon = 0 and distance > 0 the state survives. For subthreshold x,
    the killed first moment equals (x+mu*t)*survival-2*distance*image_mass.
    Adding reset*cdf is an interval-end reset approximation, not a regenerative
    propagator: it does not allocate the random time remaining after the hit.
    """
    distance, mu, sigma, horizon = torch.broadcast_tensors(distance, mu, sigma, horizon)
    if not ((sigma > 0).all() and (horizon >= 0).all()):
        raise ValueError("Positive sigma and nonnegative horizon required.")
    safe_horizon = torch.where(horizon > 0, horizon, torch.ones_like(horizon))
    safe_distance = distance.clamp_min(0)
    scale = sigma * safe_horizon.sqrt()
    z1 = (mu * safe_horizon - safe_distance) / scale
    z2 = (-mu * safe_horizon - safe_distance) / scale
    log_image = 2 * mu * safe_distance / sigma.square() + torch.special.log_ndtr(z2)
    image = torch.exp(log_image.clamp_max(0))
    cdf = (torch.special.ndtr(z1) + image).clamp(0, 1)
    log_left = torch.special.log_ndtr(-z1)
    survival = (torch.exp(log_left) * (-torch.expm1((log_image - log_left).clamp_max(0)))).clamp(0, 1)
    live_interval = (distance > 0) & (horizon > 0)
    cdf = torch.where(live_interval, cdf, (distance <= 0).to(cdf.dtype))
    survival = torch.where(live_interval, survival, (distance > 0).to(cdf.dtype))
    image = torch.where(live_interval, image, torch.zeros_like(image))
    return cdf, survival, image


def first_passage_density(distance, mu, sigma, time):
    distance, mu, sigma, time = torch.broadcast_tensors(distance, mu, sigma, time)
    if not ((sigma > 0).all() and (time >= 0).all()):
        raise ValueError("Positive sigma and nonnegative time required.")
    safe_time = torch.where(time > 0, time, torch.ones_like(time))
    safe_distance = torch.where(distance > 0, distance, torch.ones_like(distance))
    log_f = (safe_distance.log() - sigma.log()
             - 0.5 * torch.log(torch.as_tensor(2 * torch.pi, device=time.device, dtype=time.dtype))
             - 1.5 * safe_time.log()
             - (safe_distance - mu * safe_time).square() / (2 * sigma.square() * safe_time))
    return torch.where((time > 0) & (distance > 0), log_f.exp(), torch.zeros_like(log_f))
