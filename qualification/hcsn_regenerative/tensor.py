"""Bounded differentiable fixed-boundary regeneration, independent of old A/B.

X=log(V/b) follows dX=mu*dt+sigma*dW until the fixed boundary zero.
The reset distance and positive physical refractory duration are fixed. Values,
risk and the killed state kernel all use this generator. Only strict-interior
continuous inputs have derivatives; atoms and numerical configurations do not.
"""

from dataclasses import dataclass
import math

import torch

from .tensor_normal import log_normal_cdf


_SUPPORTED = (torch.float32, torch.float64)


def _as(value, like):
    if isinstance(value, torch.Tensor):
        if value.dtype != like.dtype or value.device != like.device:
            raise ValueError("all continuous tensors must share dtype and device")
        return value
    return torch.as_tensor(value, dtype=like.dtype, device=like.device)


def _finite(name, value):
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError(f"{name} is nonfinite")


def _nonnegative(name, value):
    _finite(name, value)
    if bool((value < 0).any()):
        raise FloatingPointError(f"{name} became negative; numerical domain unresolved")
    return value


def _probability(name, value):
    _nonnegative(name, value)
    tolerance = 3e-6 if value.dtype == torch.float32 else 2e-12
    if bool((value > 1 + tolerance).any()):
        raise FloatingPointError(f"{name} exceeds one")
    return value


@dataclass(frozen=True)
class Transition:
    survivor_bins: torch.Tensor
    hit: torch.Tensor
    upper_tail: torch.Tensor


@dataclass(frozen=True)
class TensorDiffusion:
    """FP32/FP64 generator with mu in [-2,2], sigma in [.05,4], q in [.01,4].

    Positive discount is deliberate; q=0 remains outside this candidate.
    Short-time occupation uses a positive quadrature fallback with its own
    resolution checks. Horizon is [0,8]. Parameters and x/T broadcast;
    successor bins occupy the last axis. Bounds alone do not certify accuracy.
    """

    mu: torch.Tensor
    sigma: torch.Tensor
    discount: torch.Tensor

    def __post_init__(self):
        like = next((v for v in (self.mu, self.sigma, self.discount)
                     if isinstance(v, torch.Tensor)), torch.tensor(0., dtype=torch.float64))
        if like.dtype not in _SUPPORTED:
            raise ValueError("only torch.float32 and torch.float64 are qualified candidates")
        for name in ("mu", "sigma", "discount"):
            value = _as(getattr(self, name), like)
            _finite(name, value)
            object.__setattr__(self, name, value)
        if (bool((self.mu.abs() > 2).any()) or bool(((self.sigma < .05) | (self.sigma > 4)).any())
                or bool(((self.discount < .01) | (self.discount > 4)).any())):
            raise ValueError("outside declared bounded tensor parameter domain")

    def inputs(self, x, horizon):
        x, t, mu, sigma, q = torch.broadcast_tensors(
            _as(x, self.mu), _as(horizon, self.mu), self.mu, self.sigma, self.discount)
        _finite("x", x)
        _finite("horizon", t)
        if bool((x < 0).any()) or bool(((t < 0) | (t > 8)).any()):
            raise ValueError("x must be nonnegative and horizon in [0,8]")
        if ((x.requires_grad or t.requires_grad)
                and bool(((x == 0) | (t == 0)).any())):
            raise ValueError("exact boundary/zero-time atoms have no qualified autodiff")
        return x, t, mu, sigma, q

    def _hit(self, x, t, mu, sigma, q=None, *, return_error=False):
        if q is None:
            result = self._raw_hit(x, t, mu, sigma)
            return (result, torch.zeros_like(result)) if return_error else result
        from .tensor_short import discounted_hit, short_mask
        x, t, mu, sigma, q = torch.broadcast_tensors(x, t, mu, sigma, q)
        mask = short_mask(x, t, q)
        # Do not retain an unstable, unselected short-time analytic graph.
        raw_x = torch.where(mask, torch.ones_like(x), x)
        raw_t = torch.where(mask, torch.ones_like(t), t)
        result = self._raw_hit(raw_x, raw_t, mu, sigma, q)
        error = torch.zeros_like(result)
        if bool(mask.any()):
            fine, estimate = discounted_hit(x[mask], t[mask], mu[mask], sigma[mask], q[mask])
            result = result.masked_scatter(mask, fine)
            error = error.masked_scatter(mask, estimate)
        return (result, error) if return_error else result

    def _raw_hit(self, x, t, mu, sigma, q=None):
        regular = (x > 0) & (t > 0)
        xx = torch.where(regular, x, torch.ones_like(x))
        tt = torch.where(regular, t, torch.ones_like(t))
        scale = sigma * torch.sqrt(tt)
        if q is None:
            l1 = log_normal_cdf((-xx - mu*tt)/scale)
            l2 = -2*mu*xx/sigma.square() + log_normal_cdf((-xx + mu*tt)/scale)
        else:
            chi = torch.sqrt(mu.square() + 2*q*sigma.square())
            # Rationalize the small root. Subtracting |mu| from chi loses
            # FP32 digits, which occupation subsequently amplifies by 1/q.
            root_minus = torch.where(mu > 0, 2*q/(chi+mu), (chi-mu)/sigma.square())
            root_plus = torch.where(mu < 0, 2*q/(chi-mu), (chi+mu)/sigma.square())
            l1 = root_minus*xx + log_normal_cdf((-xx-chi*tt)/scale)
            l2 = -root_plus*xx + log_normal_cdf((-xx+chi*tt)/scale)
        log_result = torch.logaddexp(l1, l2)
        _finite("log first hit (unresolved finite-input scale)", log_result)
        result = torch.exp(log_result)
        return torch.where(x == 0, torch.ones_like(result),
                           torch.where(t == 0, torch.zeros_like(result), result))

    def hit_probability(self, x, horizon):
        x, t, mu, sigma, _ = self.inputs(x, horizon)
        return _probability("first hit", self._hit(x, t, mu, sigma))

    def discounted_hit(self, x, horizon):
        x, t, mu, sigma, q = self.inputs(x, horizon)
        return _probability("discounted hit", self._hit(x, t, mu, sigma, q))

    def _tail(self, x, t, mu, sigma, edge):
        regular = (x > 0) & (t > 0)
        xx = torch.where(regular, x, torch.ones_like(x))
        tt = torch.where(regular, t, torch.ones_like(t))
        zz = torch.where(torch.isfinite(edge), edge, torch.zeros_like(edge))
        scale = sigma * torch.sqrt(tt)
        la = log_normal_cdf((xx+mu*tt-zz)/scale)
        lb = -2*mu*xx/sigma.square() + log_normal_cdf((-xx+mu*tt-zz)/scale)
        value = torch.exp(la) * (-torch.expm1(lb-la))
        value = torch.where(t == 0, (x >= edge).to(x.dtype), value)
        return torch.where((x == 0) | ~torch.isfinite(edge), torch.zeros_like(value), value)

    def survival(self, x, horizon):
        x, t, mu, sigma, _ = self.inputs(x, horizon)
        return _probability("survival", self._tail(x, t, mu, sigma, torch.zeros_like(x)))

    def density(self, time, x):
        x, t, mu, sigma, _ = self.inputs(x, time)
        regular = (x > 0) & (t > 0)
        xx = torch.where(regular, x, torch.ones_like(x))
        tt = torch.where(regular, t, torch.ones_like(t))
        log_density = (torch.log(xx)-torch.log(sigma)-.5*math.log(2*math.pi)
                       -1.5*torch.log(tt)-(xx+mu*tt).square()/(2*sigma.square()*tt))
        return _nonnegative("density", torch.where(regular, torch.exp(log_density), torch.zeros_like(x)))

    def transition(self, x, horizon, edges):
        x, t, mu, sigma, _ = self.inputs(x, horizon)
        edge = _as(edges, self.mu)
        if (edge.requires_grad or edge.ndim != 1 or edge.numel() < 2 or bool(edge[0] != 0)
                or not bool(torch.isfinite(edge[:-1]).all()) or bool(torch.isnan(edge[-1]))
                or not bool((torch.diff(edge) > 0).all())):
            raise ValueError("edges are fixed, strictly increasing from zero; only last may be infinite")
        tails = self._tail(x[..., None], t[..., None], mu[..., None], sigma[..., None], edge)
        bins = _nonnegative("survivor bins", tails[..., :-1]-tails[..., 1:])
        tail = _nonnegative("upper tail", tails[..., -1])
        hit = self.hit_probability(x, t)
        residual = 1-hit-bins.sum(-1)-tail
        tolerance = 2e-5 if x.dtype == torch.float32 else 2e-10
        if bool((residual.abs() > tolerance).any()):
            raise FloatingPointError("killed-kernel mass is unresolved")
        return Transition(bins, hit, tail)


@dataclass(frozen=True)
class TensorReset:
    """Fixed reset distance and physical refractory duration; no trainable grid."""

    margin: float
    refractory: float
    hit_reward: float = 1.

    def __post_init__(self):
        for name in ("margin", "refractory", "hit_reward"):
            value = getattr(self, name)
            if isinstance(value, (bool, torch.Tensor)) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("reset parameters are fixed finite real hyperparameters")
        if not 0 < self.margin <= 8 or not 0 < self.refractory <= 8:
            raise ValueError("reset margin and physical refractory must be in (0,8]")


def _terms(reset, horizon, max_terms):
    if isinstance(max_terms, bool) or not isinstance(max_terms, int) or not 1 <= max_terms <= 1024:
        raise ValueError("max_terms must be a fixed integer in [1,1024]")
    # Exactly finite, because no more hits can occur before their refractory
    # delays. The cutoff is fixed by the declared maximum requested horizon.
    terms = int(math.floor(float(horizon.detach().max().cpu()) / reset.refractory)) + 1
    if terms > max_terms:
        raise ValueError("max_terms does not cover the physical horizon")
    return terms


def _positive_time_hit(process, x, remaining, discounted=False, *, return_error=False):
    positive = remaining > 0
    safe_time = torch.where(positive, remaining, torch.ones_like(remaining))
    x, safe_time, mu, sigma, q = process.inputs(x, safe_time)
    hit, error = process._hit(x, safe_time, mu, sigma, q if discounted else None, return_error=True)
    # At a zero remaining deadline x=0 retains its initial atom.
    mask = positive | ((remaining == 0) & (x == 0))
    result = torch.where(mask, hit, torch.zeros_like(hit))
    error = torch.where(mask, error, torch.zeros_like(error))
    return (result, error) if return_error else result


@dataclass(frozen=True)
class ValueReceipt:
    single_cycle: torch.Tensor
    regenerative: torch.Tensor
    expected_discounted_hits: torch.Tensor
    active_probability: torch.Tensor
    active_time: torch.Tensor
    renewal_tail_bound: float
    value_tail_bound: float
    quadrature_error: torch.Tensor
    terms: int


def finite_horizon_value(process, reset, x, horizon, *, active_reward=0., terminal_reward=0., max_terms=64):
    """Finite renewal law with a positive short-time occupation fallback.

    J(a,T)=(G(a,T)-exp(-q*T)F(a,T))/q integrates exp(-qt)F(a,t).
    One-cycle E uses S; regenerative U uses the same release/hit laws. Positive
    q is a declared domain restriction, not a numerical regularizer. For
    q*T<1e-3, occupation and discounted-hit corrections use fixed 64/128
    positive quadrature. quadrature_error records an observed output-space
    difference estimate for E/U, not a certified continuum error bound.
    """
    from .tensor_short import occupation, release_occupation
    x, t, mu, sigma, q = process.inputs(x, horizon)
    terms = _terms(reset, t, max_terms)
    c, h = _as(active_reward, x), _as(terminal_reward, x)
    _finite("active_reward", c)
    _finite("terminal_reward", h)
    f, s = process.hit_probability(x, t), process.survival(x, t)
    g, g_error = process._hit(x, t, mu, sigma, q, return_error=True)
    _probability("discounted hit", g)
    if bool((g > f).any()):
        raise FloatingPointError("discounted hit exceeds first hit; small-time precision unresolved")
    total_time = -torch.expm1(-q*t)/q
    one_time = total_time-(g-torch.exp(-q*t)*f)/q
    one_time = torch.where(x == 0, torch.zeros_like(one_time), one_time)
    one_time, one_error = occupation(process, x, t, one_time)
    _nonnegative("single-cycle occupation", one_time)
    active, active_time, count = s, one_time, torch.zeros_like(x)
    active_error, count_error = one_error, torch.zeros_like(x)
    for n in range(1, terms+1):
        distance = x+(n-1)*reset.margin
        hit_remaining = t-(n-1)*reset.refractory
        hit, hit_error = _positive_time_hit(process,distance,hit_remaining,True,return_error=True)
        hit_discount = torch.exp(-q*((n-1)*reset.refractory))
        count, count_error = count+hit_discount*hit, count_error+hit_discount*hit_error
        remaining = t-n*reset.refractory
        f0 = _positive_time_hit(process,distance,remaining)
        f1 = _positive_time_hit(process,distance+reset.margin,remaining)
        g0 = _positive_time_hit(process,distance,remaining,True)
        g1 = _positive_time_hit(process,distance+reset.margin,remaining,True)
        active = active+f0-f1
        release_time = ((g0-g1)-torch.exp(-q*remaining)*(f0-f1))/q
        # J(0,R) is exactly (1-exp(-qR))/q, including R immediately after
        # release. Do not obtain this atom contribution by subtracting ones.
        atom_time = -torch.expm1(-q*remaining)/q-(g1-torch.exp(-q*remaining)*f1)/q
        release_time = torch.where((distance == 0) & (remaining > 0), atom_time, release_time)
        release_time, release_error = release_occupation(process,distance,remaining,reset.margin,release_time)
        release_discount = torch.exp(-q*(n*reset.refractory))
        active_time = active_time+release_discount*release_time
        active_error = active_error+release_discount*release_error
    single = c*one_time+reset.hit_reward*g+h*torch.exp(-q*t)*s
    regenerative = c*active_time+reset.hit_reward*count+h*torch.exp(-q*t)*active
    for name,value in (("single",single),("regenerative",regenerative),("active_time",active_time),("count",count)):
        _finite(name,value)
    _probability("active probability",active)
    _nonnegative("regenerative occupation",active_time)
    tolerance = 5e-5 if x.dtype == torch.float32 else 5e-10
    if bool((active_time < -tolerance).any()) or bool((active_time > total_time+tolerance).any()):
        raise FloatingPointError("occupation cancellation is unresolved")
    quadrature_error = torch.maximum(c.abs()*one_error+abs(reset.hit_reward)*g_error,
                                    c.abs()*active_error+abs(reset.hit_reward)*count_error).detach()
    return ValueReceipt(single,regenerative,count,active,active_time,0.,0.,quadrature_error,terms)


def regenerative_transition(process, reset, x, horizon, edges, **kwargs):
    """Return the independent tensor renewal successor (see tensor_state)."""
    from .tensor_state import regenerative_transition as transition
    return transition(process, reset, x, horizon, edges, **kwargs)
