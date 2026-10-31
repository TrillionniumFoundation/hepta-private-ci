"""Stable Gaussian laws and an absorbing constant-drift Brownian cell.

The Brownian image series is an analytic law, evaluated with a finite image
sum. Repeated projection to voltage representatives is still a numerical
approximation. This module does not implement an exact killed OU process.
"""

import math

import torch
from torch import Tensor

from ..round7.dynamics import EventDynamics


KERNEL_VERSION = "r8-brownian-images-v1"


def normal_cdf(z: Tensor) -> Tensor:
    """Normal CDF without cancellation in the negative tail."""
    return 0.5 * torch.erfc(-z / math.sqrt(2.0))


def log_normal_interval(lower: Tensor, upper: Tensor) -> Tensor:
    """log P(lower < Z <= upper), using the nearer normal tail.

    Arguments must be finite. Equal bounds give -inf and zero derivatives.
    The implementation never invents a positive probability floor.
    """
    lower, upper = torch.broadcast_tensors(lower, upper)
    if bool(torch.any(upper < lower)):
        raise ValueError("normal interval bounds are reversed")
    right = lower >= 0
    # Reflect positive intervals so log-CDF differences never subtract two
    # values indistinguishable from log(1). Both expressions remain finite.
    a = torch.where(right, -upper, lower)
    b = torch.where(right, -lower, upper)
    small = torch.special.log_ndtr(a)
    big = torch.special.log_ndtr(b)
    positive = big > small
    difference = torch.where(positive, small - big, -torch.ones_like(big))
    value = big + torch.log(-torch.expm1(difference))
    return torch.where(positive, value, torch.full_like(value, -torch.inf))


def normal_interval(lower: Tensor, upper: Tensor) -> Tensor:
    return torch.exp(log_normal_interval(lower, upper))


def gaussian_propagate(mean, variance, drift, diffusion, dt, *, leak=0.0):
    """Exact unbounded Gaussian propagation, with no grid or tail folding.

    Coefficients are constant during this interval. ``leak=0`` gives Brownian
    motion; nonnegative leak gives the exact affine OU Gaussian transition.
    This closure assumes the input Gaussian and independent process noise.
    """
    mean = torch.as_tensor(mean, dtype=torch.float64)
    args = [torch.as_tensor(x, dtype=mean.dtype, device=mean.device)
            for x in (variance, drift, diffusion, dt, leak)]
    mean, variance, drift, diffusion, dt, leak = torch.broadcast_tensors(mean, *args)
    if bool(torch.any(variance < 0) or torch.any(diffusion < 0)
            or torch.any(dt < 0) or torch.any(leak < 0)):
        raise ValueError("variance, diffusion, duration and leak must be nonnegative")
    positive_leak = leak > 0
    denominator = torch.where(positive_leak, leak, torch.ones_like(leak))
    decay = torch.exp(-leak * dt)
    z = leak * dt
    # The Taylor branch also preserves the true derivative at zero leak.
    a_series = dt * (1 - z / 2 + z.square() / 6 - z**3 / 24 + z**4 / 120)
    b_series = dt * (1 - z + 2 * z.square() / 3 - z**3 / 3 + 2 * z**4 / 15)
    a = torch.where(z.abs() < 1e-5, a_series, -torch.expm1(-z) / denominator)
    b = torch.where(z.abs() < 1e-5, b_series, -torch.expm1(-2 * z) / (2 * denominator))
    return decay * mean + a * drift, decay.square() * variance + diffusion.square() * b


def gaussian_events(mean, variance, lower, upper) -> Tensor:
    """Three endpoint channels in (put, idle, call) order; includes atoms.

    Put is X <= lower, call is X > upper. At a common strike the idle
    channel vanishes and the other channels form a complementary partition.
    """
    mean = torch.as_tensor(mean, dtype=torch.float64)
    args = [torch.as_tensor(x, dtype=mean.dtype, device=mean.device)
            for x in (variance, lower, upper)]
    mean, variance, lower, upper = torch.broadcast_tensors(mean, *args)
    if bool(torch.any(variance < 0) or torch.any(lower > upper)):
        raise ValueError("invalid Gaussian variance or bounds")
    positive = variance > 0
    sd = torch.sqrt(torch.where(positive, variance, torch.ones_like(variance)))
    a, b = (lower - mean) / sd, (upper - mean) / sd
    smooth = torch.stack((normal_cdf(a), normal_interval(a, b), normal_cdf(-b)), -1)
    atom = torch.stack((mean <= lower, (mean > lower) & (mean <= upper), mean > upper), -1)
    return torch.where(positive[..., None], smooth, atom.to(mean.dtype))


def probit_events(mean, variance, lower, upper) -> Tensor:
    """Explicit Gaussian/probit comparator with the identical event partition."""
    mean = torch.as_tensor(mean, dtype=torch.float64)
    variance = torch.as_tensor(variance, dtype=mean.dtype, device=mean.device)
    lower = torch.as_tensor(lower, dtype=mean.dtype, device=mean.device)
    upper = torch.as_tensor(upper, dtype=mean.dtype, device=mean.device)
    if bool(torch.any(variance <= 0) or torch.any(lower > upper)):
        raise ValueError("probit comparator requires positive variance and ordered bounds")
    scale = torch.sqrt(variance)
    put_score, call_score = (lower - mean) / scale, (mean - upper) / scale
    return torch.stack((normal_cdf(put_score), normal_interval(put_score, -call_score),
                        normal_cdf(call_score)), -1)


def recovery_probability(rate: Tensor, dt: float) -> Tensor:
    """Endpoint observation of an exponential release clock, q(dt)."""
    if dt < 0 or bool(torch.any(rate < 0)):
        raise ValueError("recovery rate and duration must be nonnegative")
    return -torch.expm1(-rate * dt)


def _image_indices(reference: Tensor, terms: int) -> Tensor:
    if not isinstance(terms, int) or terms < 1:
        raise ValueError("image_terms must be a positive integer")
    return torch.arange(-terms, terms + 1, dtype=reference.dtype, device=reference.device)


def _lower_exit(x: Tensor, drift: Tensor, sigma: Tensor, dt: float,
                width: Tensor, terms: int) -> Tensor:
    # Integrating the image boundary flux gives signed first-hitting CDFs.
    k = _image_indices(x, terms)
    d = x[..., None] + 2 * width * k
    distance = d.abs()
    scale = sigma * math.sqrt(dt)
    mu = drift[..., None]
    a = (-distance - mu * dt) / scale
    b = (-distance + mu * dt) / scale
    log_f = torch.logaddexp(torch.special.log_ndtr(a),
                           -2 * mu * distance / sigma.square() + torch.special.log_ndtr(b))
    weighted = torch.exp(mu * (distance - x[..., None]) / sigma.square() + log_f)
    return (d.sign() * weighted).sum(-1)


def brownian_first_exit(x: Tensor, drift: Tensor, sigma: Tensor, dt: float,
                        boundary: Tensor, *, image_terms: int = 12) -> Tensor:
    """First exit at (+b,-b), from interior x, before dt; no reset yet."""
    x, drift = torch.broadcast_tensors(x, drift)
    if dt <= 0 or bool(torch.any(sigma <= 0) or torch.any(boundary <= 0)
                       or torch.any(x.abs() >= boundary)):
        raise ValueError("positive dt/sigma/boundary and strictly interior starts required")
    lower = _lower_exit(x + boundary, drift, sigma, dt, 2 * boundary, image_terms)
    upper = _lower_exit(boundary - x, -drift, sigma, dt, 2 * boundary, image_terms)
    return torch.stack((upper, lower), -1)


def brownian_killed_bins(x: Tensor, edges: Tensor, drift: Tensor, sigma: Tensor,
                         dt: float, boundary: Tensor, *, image_terms: int = 12) -> Tensor:
    """P(X_dt in each bin, no earlier exit), not a conditional distribution.

    x and drift broadcast to any source shape; the result appends the bin
    dimension. Bins must cover [-b,b]. Divide by survival mass only when a
    conditional survivor distribution is explicitly wanted.
    """
    x, drift = torch.broadcast_tensors(x, drift)
    if dt <= 0 or bool(torch.any(sigma <= 0) or torch.any(boundary <= 0)
                       or torch.any(x.abs() >= boundary)):
        raise ValueError("positive dt/sigma/boundary and strictly interior starts required")
    if edges.ndim != 1 or len(edges) < 2 or bool(torch.any(edges[1:] <= edges[:-1])):
        raise ValueError("strictly ordered one-dimensional bin edges required")
    if not torch.allclose(edges[[0, -1]], torch.stack((-boundary, boundary)), rtol=0, atol=1e-12):
        raise ValueError("killed bins must partition [-boundary,boundary]")
    k = _image_indices(x, image_terms)
    length = 2 * boundary
    shifted_x = x[..., None, None] + boundary
    mu = drift[..., None, None]
    shift = 2 * k * length
    a = edges[:-1, None] + boundary
    b = edges[1:, None] + boundary
    scale = sigma * math.sqrt(dt)
    mean1 = shifted_x - shift + mu * dt
    mean2 = -shifted_x - shift + mu * dt
    log1 = -mu * shift / sigma.square() + log_normal_interval((a - mean1) / scale, (b - mean1) / scale)
    log2 = -2 * mu * (shifted_x + k * length) / sigma.square() + log_normal_interval((a - mean2) / scale, (b - mean2) / scale)
    return (torch.exp(log1) - torch.exp(log2)).sum(-1)


class BrownianEventDynamics(EventDynamics):
    """R7-shaped cell with a new, explicitly constant-drift process contract.

    The R7 raw_leak parameter is retained only for compatible parameter-copy
    experiments. It is frozen and has no effect. All compared modes must use
    this same Brownian process. ``continuous`` remains a projected Gaussian
    state; use gaussian_propagate for an unbounded analytic control.
    """

    kernel_version = KERNEL_VERSION

    def __init__(self, mode, n_grid=15, *, image_terms=12, reference_dt=1.0):
        super().__init__(mode, n_grid)
        if reference_dt <= 0:
            raise ValueError("reference_dt must be positive")
        self.image_terms = image_terms
        self.reference_dt = reference_dt
        self.raw_leak.requires_grad_(False)

    def physical_parameters(self):
        physical = super().physical_parameters()
        physical["leak"] = self.raw_leak * 0.0
        physical["recovery_rate"] = -torch.log1p(-physical["recovery_probability"]) / self.reference_dt
        return physical

    def reset_distributions(self):
        centers = 0.75 * torch.tanh(torch.stack((self.raw_reset_plus, self.raw_reset_minus)))
        z = (self.normalised_edges[None, 1:-1] - centers[:, None]) / self.reset_sd_normalised
        probabilities = torch.cat((normal_cdf(z[:, :1]), normal_interval(z[:, :-1], z[:, 1:]),
                                   normal_cdf(-z[:, -1:])), -1)
        return probabilities[0], probabilities[1]

    def transition_matrix(self, drive: Tensor, dt: float = 1.0):
        drive, dt = self._drive(drive), self._check_dt(dt)
        p = self.physical_parameters()
        x, mu = torch.broadcast_tensors(self.active_grid()[None, :], drive[:, None])
        edges = p["boundary"] * self.normalised_edges
        if self.mode == "first_passage":
            active = brownian_killed_bins(x, edges, mu, p["diffusion"], dt, p["boundary"], image_terms=self.image_terms)
            events = brownian_first_exit(x, mu, p["diffusion"], dt, p["boundary"], image_terms=self.image_terms)
        else:
            mean = x + mu * dt
            z = (edges[None, None, :] - mean[..., None]) / (p["diffusion"] * math.sqrt(dt))
            if self.mode == "continuous":
                active = torch.cat((normal_cdf(z[..., 1:2]), normal_interval(z[..., 1:-2], z[..., 2:-1]),
                                    normal_cdf(-z[..., -2:-1])), -1)
                events = x.new_zeros(*x.shape, 2)
            else:
                active = normal_interval(z[..., :-1], z[..., 1:])
                events = torch.stack((normal_cdf(-z[..., -1]), normal_cdf(z[..., 0])), -1)
        # Only roundoff-scale negative cancellation is removed. No row is
        # renormalized; conservation and series-order error remain auditable.
        if bool(torch.any(active.detach() < -2e-11) or torch.any(events.detach() < -2e-11)):
            raise ArithmeticError("image series produced materially negative probability")
        active, events = active.clamp_min(0), events.clamp_min(0)
        active_rows = torch.cat((active, events), -1)
        if self.mode == "continuous":
            ref_rows = x.new_zeros(2, self.n_states)
            ref_rows[0, -2], ref_rows[1, -1] = 1.0, 1.0
        else:
            q = recovery_probability(p["recovery_rate"], dt)
            reset = torch.stack(self.reset_distributions())
            ref_rows = torch.cat((q * reset, (1 - q) * torch.eye(2, dtype=x.dtype, device=x.device)), -1)
        transition = torch.cat((active_rows, ref_rows[None].expand(len(drive), -1, -1)), 1)
        rewards = torch.cat((events, x.new_zeros(len(drive), 2, 2)), 1)
        if not bool(torch.isfinite(transition.detach()).all()):
            raise ArithmeticError("nonfinite transition probabilities")
        if float((transition.detach().sum(-1) - 1).abs().max()) > 2e-10:
            raise ArithmeticError("image-series mass defect exceeds 2e-10; increase order or restrict regime")
        return transition, rewards
