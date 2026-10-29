"""Stable differentiable scalar kernels for the new 2026-10-29 study.

These kernels are a new implementation, not recovered 2026-10-28 source.
The Call is the normalized residual C/(K+C), not a second independently
exercisable perpetual option. The Put is P/K, not a default probability.
"""

import math

import torch


PHI_SERIES_RADIUS = 1.0
PHI_SERIES_DEGREE = 18
CALL_SERIES_RADIUS = 0.25
OPERATOR_MODES = ("analytic", "matched_c1", "sigmoid")


def _phi(z: torch.Tensor, order: int) -> torch.Tensor:
    """Evaluate sum z**j/(j+order)! near zero; guard both where branches."""
    small = z.abs() <= PHI_SERIES_RADIUS
    series_z = torch.where(small, z, torch.zeros_like(z))
    polynomial = torch.full_like(z, 1.0 / math.factorial(PHI_SERIES_DEGREE + order))
    for j in range(PHI_SERIES_DEGREE - 1, -1, -1):
        polynomial = polynomial * series_z + 1.0 / math.factorial(j + order)
    quotient_z = torch.where(small, torch.ones_like(z), z)
    numerator = torch.expm1(quotient_z)
    if order == 2:
        numerator = numerator - quotient_z
    quotient = numerator / quotient_z.pow(order)
    return torch.where(small, polynomial, quotient)


def phi1(z: torch.Tensor) -> torch.Tensor:
    """(exp(z)-1)/z with value 1 and derivative 1/2 at zero."""
    return _phi(z, 1)


def phi2(z: torch.Tensor) -> torch.Tensor:
    """(exp(z)-1-z)/z**2 with value 1/2 and derivative 1/6 at zero."""
    return _phi(z, 2)


def call_put(
    x: torch.Tensor, kappa: torch.Tensor, mode: str = "analytic"
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return (normalized Call, normalized Put) for positive kappa.

    Inputs broadcast. The declared flow domain has .25 <= kappa <= 4 and
    bounded finite x. Positive and negative branch arguments are guarded
    before exp/division so inactive branches cannot poison autograd.
    Analytic and matched_c1 are C1, generally not C2, at x=0.
    """
    if mode not in OPERATOR_MODES:
        raise ValueError(f"Unknown operator mode: {mode}")
    if mode == "sigmoid":
        return torch.sigmoid(kappa * x), torch.sigmoid(-kappa * x)

    positive = x > 0
    xp = torch.where(positive, x, torch.zeros_like(x))
    xm = torch.where(positive, torch.zeros_like(x), x)
    beta = kappa / (1.0 + kappa)

    if mode == "matched_c1":
        # Same boundary values, first slopes, Call right curvature and ranges.
        u = torch.sqrt(kappa / 2.0) * xp
        call = (u / torch.hypot(u, torch.ones_like(u))).square()
        put_positive = 1.0 / ((1.0 + kappa) * (1.0 + kappa * xp))
        put_negative = 1.0 - beta / (1.0 - xm)
        return call, torch.where(positive, put_positive, put_negative)

    near = positive & (xp <= CALL_SERIES_RADIUS) & (kappa * xp <= CALL_SERIES_RADIUS)
    # Divide D by exp(x); all exponents are nonpositive, including inactive
    # positions. This avoids overflow at large positive margins.
    xf = torch.where(positive & ~near, xp, torch.ones_like(xp))
    call_far = 1.0 - (1.0 + kappa) * torch.exp(-xf) / (
        kappa + torch.exp(-(kappa + 1.0) * xf)
    )
    # CPU eager execution can omit an entirely inactive Taylor branch. A GPU
    # always uses the tensor path to avoid a host synchronization per substep.
    if x.device.type == "cpu" and not bool(near.any()):
        call = torch.where(positive, call_far, torch.zeros_like(x))
    else:
        xn = torch.where(near, xp, torch.zeros_like(xp))
        # Stack both arguments to share the same polynomial evaluation. Linear
        # terms cancel symbolically, not by subtracting floating values.
        pair = phi2(torch.stack((xn, -kappa * xn)))
        numerator = xn.square() * (kappa * pair[0] + kappa.square() * pair[1])
        denominator = kappa * torch.exp(xn) + torch.exp(-kappa * xn)
        call_near = numerator / denominator
        call = torch.where(
            positive, torch.where(near, call_near, call_far), torch.zeros_like(x)
        )
    put_positive = torch.exp(-kappa * xp) / (1.0 + kappa)
    put_negative = 1.0 - beta * torch.exp(xm)
    return call, torch.where(positive, put_positive, put_negative)
