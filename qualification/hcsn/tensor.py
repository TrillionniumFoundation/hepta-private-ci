"""Differentiable He--Xiong kernels, evaluated in the caller's FP32/FP64 dtype.

All time variables use one consistent time unit.  ``x`` is log(V / b), not V.
F and G include the atom at time zero when x=0; f describes only t>0 density.
Neither a first-event density nor an instantaneous risk feature is a reset rate.
"""

from dataclasses import dataclass
import math

import torch


@dataclass(frozen=True)
class HXParams:
    r: object = 0.05
    delta: object = 0.02
    sigma: object = 0.20
    coupon: object = 5.0
    principal: object = 100.0
    maturity: object = 1.0
    tax: object = 0.25
    recovery: object = 0.60
    ell: object = 0.01

    @property
    def q(self):
        return self.r + self.ell

    @property
    def mu(self):
        return self.r - self.delta - self.sigma**2 / 2

    @property
    def c(self):
        return self.coupon / self.maturity

    @property
    def p(self):
        return self.principal / self.maturity


def _inputs(*values):
    tensors = [v for v in values if isinstance(v, torch.Tensor)]
    dtype = tensors[0].dtype if tensors else torch.float64
    device = tensors[0].device if tensors else torch.device("cpu")
    for t in tensors:
        if t.device != device:
            raise ValueError("All kernel tensors must be on one device")
        dtype = torch.promote_types(dtype, t.dtype)
    if dtype not in (torch.float32, torch.float64):
        raise ValueError("The analytical kernel requires FP32 or FP64")
    return tuple(torch.as_tensor(v, dtype=dtype, device=device) for v in values)


def _domain(x, time, mu, sigma, discount=None):
    values = (x, time, mu, sigma) if discount is None else (x, time, mu, sigma, discount)
    if any(not bool(torch.isfinite(v).all()) for v in values):
        raise ValueError("Kernel arguments must be finite")
    if bool((x < 0).any()) or bool((time < 0).any()) or bool((sigma <= 0).any()):
        raise ValueError("Require log-margin >= 0, time >= 0 and sigma > 0")
    if discount is not None and bool((discount < 0).any()):
        raise ValueError("Require discount >= 0")


def _exp_phi(exponent, argument):
    return torch.exp(exponent + torch.special.log_ndtr(argument))


def first_passage_cdf(x, horizon, mu, sigma, *, validate=True):
    """P(tau_0 <= horizon), including tau_0=0 at the absorbing boundary."""
    x, horizon, mu, sigma = _inputs(x, horizon, mu, sigma)
    if validate:
        _domain(x, horizon, mu, sigma)
    time = torch.where(horizon > 0, horizon, torch.ones_like(horizon))
    scale = sigma * torch.sqrt(time)
    first = torch.special.log_ndtr((-x - mu * time) / scale)
    reflected = -2 * mu * x / sigma**2 + torch.special.log_ndtr((-x + mu * time) / scale)
    value = torch.exp(torch.logaddexp(first, reflected))
    value = torch.where(horizon > 0, value, torch.zeros_like(value))
    return torch.where((x == 0) & (horizon == 0), torch.ones_like(value), value)


def discounted_first_passage(x, horizon, mu, sigma, discount, *, validate=True):
    """E[exp(-discount*tau_0) 1(tau_0<=horizon)], including discount=mu=0.

    The even Taylor expansion at chi^2=mu^2+2*q*sigma^2=0 prevents the
    artificial 0*infinity autodiff singularity from differentiating sqrt(0).
    Terms through chi^4 are used only when chi*(x/sigma^2+sqrt(T)/sigma)<.001.
    """
    x, horizon, mu, sigma, discount = _inputs(x, horizon, mu, sigma, discount)
    if validate:
        _domain(x, horizon, mu, sigma, discount)
    time = torch.where(horizon > 0, horizon, torch.ones_like(horizon))
    scale = sigma * torch.sqrt(time)
    variance = mu**2 + 2 * discount * sigma**2
    a, beta = x / sigma**2, torch.sqrt(time) / sigma
    near = variance * (a + beta)**2 < 1e-6
    chi = torch.sqrt(torch.where(near, torch.ones_like(variance), variance))
    first = (-mu + chi) * x / sigma**2 + torch.special.log_ndtr((-x - chi * time) / scale)
    second = (-mu - chi) * x / sigma**2 + torch.special.log_ndtr((-x + chi * time) / scale)
    regular = torch.exp(torch.logaddexp(first, second))
    aa = torch.where(near, a, torch.zeros_like(a))
    bb = torch.where(near, beta, torch.ones_like(beta))
    dd = -aa / bb
    phi = torch.exp(-dd**2 / 2) / math.sqrt(2 * math.pi)
    cdf = torch.special.ndtr(dd)
    var = torch.where(near, variance, torch.zeros_like(variance))
    even = 2 * cdf + var * (aa**2 * cdf - aa * bb * phi)
    even = even + var**2 / 12 * (aa**4 * cdf + (aa * bb**3 - aa**3 * bb) * phi)
    limit = torch.exp(-torch.where(near, mu, torch.zeros_like(mu)) * aa) * even
    value = torch.where(near, limit, regular)
    value = torch.where(horizon > 0, value, torch.zeros_like(value))
    return torch.where((x == 0) & (horizon == 0), torch.ones_like(value), value)


def first_passage_density(time, x, mu, sigma, *, validate=True):
    """Ordinary density for t>0,x>0; zero excludes the boundary Dirac atom."""
    time, x, mu, sigma = _inputs(time, x, mu, sigma)
    if validate:
        _domain(x, time, mu, sigma)
    tt = torch.where(time > 0, time, torch.ones_like(time))
    xx = torch.where(x > 0, x, torch.ones_like(x))
    log_density = torch.log(xx) - torch.log(sigma) - 0.5 * math.log(2 * math.pi)
    log_density = log_density - 1.5 * torch.log(tt) - (xx + mu * tt)**2 / (2 * sigma**2 * tt)
    return torch.where((time > 0) & (x > 0), torch.exp(log_density), torch.zeros_like(log_density))


def simple_equity_ratio(x, gamma, *, validate=True):
    """Constant-carry NO-ROLLOVER ablation E/V, not full HX equity."""
    x, gamma = _inputs(x, gamma)
    if validate and (bool((x < 0).any()) or bool((gamma <= 0).any())):
        raise ValueError("Require x >= 0 and gamma > 0")
    # Cancel the linear terms symbolically near the smooth-pasting boundary.
    near = ((gamma + 1) * x).abs() < 1e-3
    xx = torch.where(near, x, torch.zeros_like(x))
    series = torch.zeros_like(xx + gamma)
    for n in range(2, 8):
        coefficient = ((-1.0)**n) * ((gamma + 1)**n - (gamma + 1)) / (gamma * math.factorial(n))
        series = series + coefficient * xx**n
    regular = -(1 + 1 / gamma) * torch.expm1(-x) + torch.expm1(-(gamma + 1) * x) / gamma
    return torch.where(near, series, regular)
