"""Differentiable He--Xiong kernels, evaluated in the caller's FP32/FP64 dtype.

All time variables use one consistent time unit.  ``x`` is log(V / b), not V.
F and G include the atom at time zero when x=0; f describes only t>0 density.
Neither a first-event density nor an instantaneous risk feature is a reset rate.
"""

from dataclasses import dataclass, fields
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


def first_passage_survival(x, horizon, mu, sigma, *, validate=True):
    """Survival using a log difference, preserving small values near default."""
    x, horizon, mu, sigma = _inputs(x, horizon, mu, sigma)
    if validate:
        _domain(x, horizon, mu, sigma)
    time = torch.where(horizon > 0, horizon, torch.ones_like(horizon))
    scale = sigma * torch.sqrt(time)
    log_a = torch.special.log_ndtr((x + mu * time) / scale)
    log_b = -2 * mu * x / sigma**2 + torch.special.log_ndtr((-x + mu * time) / scale)
    value = torch.exp(log_a) * (-torch.expm1(log_b - log_a))
    value = torch.where(horizon > 0, value, torch.ones_like(value))
    return torch.where((x == 0) & (horizon == 0), torch.zeros_like(value), value)


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
    boundary_time = torch.where((x == 0) & (time > 0), time, torch.ones_like(time))
    boundary_slope = torch.exp(-torch.log(sigma) - 0.5 * math.log(2 * math.pi)
                               - 1.5 * torch.log(boundary_time)
                               - mu**2 * boundary_time / (2 * sigma**2))
    value = torch.where(x > 0, torch.exp(log_density), x * boundary_slope)
    return torch.where(time > 0, value, torch.zeros_like(value))


def simple_equity_ratio(x, gamma, *, validate=True):
    """Constant-carry NO-ROLLOVER ablation E/V, not full HX equity."""
    x, gamma = _inputs(x, gamma)
    if validate and (not bool(torch.isfinite(x).all()) or not bool(torch.isfinite(gamma).all())
                     or bool((x < 0).any()) or bool((gamma <= 0).any())):
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


def _parameters(par, like=None, validate=True):
    names = [field.name for field in fields(HXParams)]
    values = [getattr(par, name) for name in names]
    converted = _inputs(*(values if like is None else [like] + values))
    p = HXParams(**dict(zip(names, converted if like is None else converted[1:])))
    if validate:
        if any(not bool(torch.isfinite(v).all()) for v in converted):
            raise ValueError("HX parameters and inputs must be finite")
        if any(bool((getattr(p, name) <= 0).any()) for name in ("r", "delta", "sigma", "principal", "maturity")):
            raise ValueError("r, delta, sigma, principal and maturity must be positive")
        if (bool((p.ell < 0).any()) or bool((p.coupon < 0).any())
                or bool(((p.tax < 0) | (p.tax >= 1)).any())
                or bool(((p.recovery < 0) | (p.recovery > 1)).any())):
            raise ValueError("Invalid ell, coupon, tax or recovery")
    return p


def _log_normal_tail_integral(lam, u, s):
    """Log of H(lam,u,s), a positive normal-tail divided difference.

    Ten Taylor terms remove the lambda=0 singularity. Negative-tail moments
    use a backward continued fraction, so FP32 never subtracts two large
    nearly equal moments. The ordinary closed form stays entirely in log space.
    """
    lam, u, s = torch.broadcast_tensors(lam, u, s)
    w = u * s
    negative_scale = 1 / torch.where(w < 0, 1 - w, torch.ones_like(w))
    scale = torch.where(w < 0, negative_scale, 1 + w)
    threshold = 0.08 if lam.dtype == torch.float32 else 0.005
    near = lam.abs() * s * scale < threshold
    ll = torch.where(near, torch.ones_like(lam), lam)
    ur = torch.where(near, torch.zeros_like(u), u)
    sr = torch.where(near, torch.ones_like(s), s)
    log_a = torch.special.log_ndtr(ur * sr)
    log_b = (0.5 * ll**2 - ll * ur) * sr**2 + torch.special.log_ndtr((ur - ll) * sr)
    # Guard the unused sign branch, not the mathematical denominator.
    delta = torch.where(ll > 0, log_b - log_a, log_a - log_b)
    regular = torch.where(ll > 0, log_a, log_b) + torch.log(-torch.expm1(delta)) - torch.log(ll.abs())
    if not bool(near.any()):
        return regular
    wn = torch.where(near, w, torch.zeros_like(w))
    low = wn < -2
    wf = torch.where(low, torch.zeros_like(wn), wn)
    cdf = torch.exp(torch.special.log_ndtr(wf))
    j0, j1 = cdf, wf * cdf + torch.exp(-wf**2 / 2) / math.sqrt(2 * math.pi)
    forward = [j1]
    for k in range(2, 11):
        j0, j1 = j1, wf * j1 + (k - 1) * j0
        forward.append(j1)
    log_j1 = torch.log(forward[0])
    ratios = [value / forward[0] for value in forward]
    if bool(low.any()):
        wt = torch.where(low, wn, torch.full_like(wn, -3))
        ratio = 130 / (torch.sqrt(wt**2 + 260) - wt)
        backward = {}
        for k in range(64, 0, -1):
            ratio = k / (ratio - wt)
            if k <= 10:
                backward[k] = ratio
        log_tail_j1 = torch.special.log_ndtr(wt) + torch.log(backward[1])
        log_j1 = torch.where(low, log_tail_j1, log_j1)
        product = torch.ones_like(wn)
        for index in range(10):
            if index > 0:
                product = product * backward[index + 1]
            ratios[index] = torch.where(low, product, ratios[index])
    t = -torch.where(near, lam * s, torch.zeros_like(lam))
    polynomial = torch.ones_like(t)
    for n in range(1, 10):
        polynomial = polynomial + t**n * ratios[n] / math.factorial(n + 1)
    limit = torch.log(s) + log_j1 + torch.log(polynomial)
    return torch.where(near, limit, regular)


def normal_tail_integral(lam, u, s):
    """H(lam,u,s)=integral_0^inf exp(-lam*y) Phi(u*s-y/s)dy."""
    lam, u, s = _inputs(lam, u, s)
    if any(not bool(torch.isfinite(v).all()) for v in (lam, u, s)) or bool((s <= 0).any()):
        raise ValueError("H arguments must be finite and s must be positive")
    return torch.exp(_log_normal_tail_integral(lam, u, s))


def _components(p):
    a = p.mu / p.sigma**2
    z = torch.sqrt(a**2 + 2 * p.r / p.sigma**2)
    zq = torch.sqrt(a**2 + 2 * p.q / p.sigma**2)
    eta = torch.where(a >= 0, 2 * p.r / (p.sigma**2 * torch.where(a >= 0, z + a, torch.ones_like(z))), z - a)
    gamma = torch.where(a < 0, 2 * p.r / (p.sigma**2 * torch.where(a < 0, z - a, torch.ones_like(z))), z + a)
    s = p.sigma * torch.sqrt(p.maturity)
    hf = normal_tail_integral(gamma, a, s) + normal_tail_integral(eta, -a, s)
    diff = -2 * p.ell / (p.sigma**2 * (z + zq))
    hg = normal_tail_integral(z + zq, zq, s) + normal_tail_integral(diff, -zq, s)
    fixed = (1 - p.tax) * p.coupon - torch.expm1(-p.q * p.maturity) * (p.p - p.c / p.q)
    coefficient = torch.exp(-p.q * p.maturity) * (p.p - p.c / p.q)
    numerator = fixed / eta + coefficient * hf + p.c / p.q * hg
    denominator = p.r / eta + p.sigma**2 / 2 + p.recovery / p.maturity * hg
    return a, z, zq, eta, gamma, s, fixed, coefficient, numerator, denominator


def hx_boundary(par, *, validate=True):
    """Full rollover free boundary (Eq.12), including the ell=0 limit."""
    p = _parameters(par, validate=validate)
    *_, numerator, denominator = _components(p)
    value = numerator / denominator
    if validate and (not bool(torch.isfinite(value).all()) or bool((value <= 0).any())):
        raise ValueError("HX parameters do not produce a finite positive boundary")
    if validate:
        running = p.delta * value - (1 - p.tax) * p.coupon + p.recovery * value / p.maturity - p.p
        cashflow_scale = p.delta * value + (1 - p.tax) * p.coupon + p.recovery * value / p.maturity + p.p
        tolerance = 32 * torch.finfo(value.dtype).eps * cashflow_scale
        if bool((running > tolerance).any()):
            raise ValueError("Formal HX boundary is locally inadmissible: positive boundary cashflow implies negative nearby equity")
    return value


def hx_debt(x, horizon, par, boundary=None, *, validate=True):
    """Finite-maturity debt d per unit of the stationary maturity ladder."""
    p = _parameters(par, like=x, validate=validate)
    x, horizon, *_ = _inputs(x, horizon, p.r)
    b = hx_boundary(p, validate=validate) if boundary is None else boundary
    if validate and (not bool(torch.isfinite(torch.as_tensor(b)).all()) or bool((torch.as_tensor(b) <= 0).any())):
        raise ValueError("Boundary must be finite and positive")
    survival = first_passage_survival(x, horizon, p.mu, p.sigma, validate=validate)
    g = discounted_first_passage(x, horizon, p.mu, p.sigma, p.q, validate=validate)
    return p.c / p.q * (1 - g) + torch.exp(-p.q * horizon) * (p.p - p.c / p.q) * survival + p.recovery * b / p.maturity * g


def _q_derivatives(u, a, s):
    """Derivatives 0..6 of exp(-(a+u)x) Phi(u*s-x/s) at x=0."""
    w, c = u * s, a + u
    cdf = torch.exp(torch.special.log_ndtr(w))
    phi = torch.exp(-w**2 / 2) / math.sqrt(2 * math.pi)
    hermite = [torch.ones_like(w), w]
    for k in range(2, 6):
        hermite.append(w * hermite[-1] - (k - 1) * hermite[-2])
    result = [cdf]
    for n in range(1, 7):
        derivative = (-c)**n * cdf
        for j in range(1, n + 1):
            derivative = derivative - phi * math.comb(n, j) * (-c)**(n - j) * hermite[j - 1] / s**j
        result.append(derivative)
    return result


def hx_equity(x, par, boundary=None, *, validate=True):
    """A7-equivalent closed resolvent with an eighth-order boundary expansion.

    The expansion solves the same equity ODE coefficient by coefficient; no
    clamp or epsilon modifies the continuation value. A supplied boundary is
    treated as fixed, and its generally nonzero marginal value is retained.
    """
    p = _parameters(par, like=x, validate=validate)
    x, *_ = _inputs(x, p.r)
    if validate and bool((x < 0).any()):
        raise ValueError("HX continuation equity requires x >= 0")
    a, z, zq, eta, gamma, s, fixed, coefficient, numerator, denominator = _components(p)
    b = numerator / denominator if boundary is None else boundary
    if validate and (not bool(torch.isfinite(torch.as_tensor(b)).all()) or bool((torch.as_tensor(b) <= 0).any())):
        raise ValueError("Boundary must be finite and positive")
    boundary_running = p.delta * b - (1 - p.tax) * p.coupon + p.recovery * b / p.maturity - p.p
    if validate and boundary is None:
        cashflow_scale = p.delta * b + (1 - p.tax) * p.coupon + p.recovery * b / p.maturity + p.p
        tolerance = 32 * torch.finfo(x.dtype).eps * cashflow_scale
        if bool((boundary_running > tolerance).any()):
            raise ValueError("Formal HX boundary is locally inadmissible: negative equity near default")
    # Bound all exponential/CDF scales before using the order-eight ODE
    # expansion. The former 0.12 cutoff left FP32 cancellation at x=.01
    # for short maturities; the 0.5 interval is checked against quadrature.
    small = x * (1 + a.abs() + zq + 1 / s + eta) < 0.5
    xr = torch.where(small, torch.full_like(x, 0.5), x)

    def resolvent(u):
        def log_difference(upper, lower):
            return upper + torch.log(-torch.expm1(lower - upper))
        left = log_difference(_log_normal_tail_integral(u - z, u, s),
                              _log_normal_tail_integral(z + u, u, s)) - gamma * xr
        shifted = u - xr / s**2
        right = log_difference(_log_normal_tail_integral(u - z, shifted, s),
                               _log_normal_tail_integral(z + u, shifted, s)) - (a + u) * xr
        return torch.exp(left) * (-torch.expm1(right - left)) / (p.sigma**2 * z)

    rf = resolvent(a) + resolvent(-a)
    rg = resolvent(zq) + resolvent(-zq)
    regular = b * (torch.expm1(xr) - torch.expm1(-gamma * xr))
    regular = regular + fixed * torch.expm1(-gamma * xr) / p.r - coefficient * rf
    regular = regular + (p.recovery * b / p.maturity - p.c / p.q) * rg
    if not bool(small.any()):
        if validate and (not bool(torch.isfinite(regular).all()) or
                         bool((regular < -64 * torch.finfo(x.dtype).eps * (p.principal + b * torch.exp(x))).any())):
            raise ValueError("Requested continuation value is nonfinite or economically inadmissible")
        return regular
    xx = torch.where(small, x, torch.zeros_like(x))
    f1, f2 = _q_derivatives(a, a, s), _q_derivatives(-a, a, s)
    g1, g2 = _q_derivatives(zq, a, s), _q_derivatives(-zq, a, s)
    slope = torch.zeros_like(numerator) if boundary is None else 2 / p.sigma**2 * (b * denominator - numerator)
    ec = [torch.zeros_like(slope), slope]
    recovery_coefficient = p.recovery * b / p.maturity - p.c / p.q
    for n in range(7):
        if n == 0:
            running = p.delta * b - (1 - p.tax) * p.coupon + p.recovery * b / p.maturity - p.p
        else:
            running = (p.delta * b - coefficient * (f1[n] + f2[n]) + recovery_coefficient * (g1[n] + g2[n])) / math.factorial(n)
        ec.append((p.r * ec[n] - p.mu * (n + 1) * ec[n + 1] - running)
                  / (p.sigma**2 / 2 * (n + 2) * (n + 1)))
    series = sum(value * xx**n for n, value in enumerate(ec))
    value = torch.where(small, series, regular)
    if validate and (not bool(torch.isfinite(value).all()) or
                     bool((value < -64 * torch.finfo(x.dtype).eps * (p.principal + b * torch.exp(x))).any())):
        raise ValueError("Requested continuation value is nonfinite or economically inadmissible")
    return value


def evaluate(value, par, horizon, *, validate=True):
    """(V,theta,T) -> b,E_HX,F,G,f plus the explicit initial-boundary atom."""
    p = _parameters(par, like=value, validate=validate)
    value, horizon, *_ = _inputs(value, horizon, p.r)
    b = hx_boundary(p, validate=validate)
    x = torch.log1p((value - b) / b)
    if validate:
        _domain(x, horizon, p.mu, p.sigma, p.q)
    return {"b": b, "E_HX": hx_equity(x, p, validate=validate),
            "F": first_passage_cdf(x, horizon, p.mu, p.sigma, validate=validate),
            "G": discounted_first_passage(x, horizon, p.mu, p.sigma, p.q, validate=validate),
            "f": first_passage_density(horizon, x, p.mu, p.sigma, validate=validate),
            "first_passage_atom": (x == 0).to(value.dtype)}
