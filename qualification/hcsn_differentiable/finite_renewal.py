"""Finite analytic renewal sums for one initially active continuum point.

For the SAME fixed Brownian drift/diffusion on every active cycle, first-hit
laws compose in distance. Event n occurs at (n-1)*d + tau[x+(n-1)*x_r].
The finite sums below distinguish first-hit F/G from repeated-event M/J/H.
They contain no QPR projection, observation conditioning, or content update.

FP64 and first-order AD inherit operator.py's physical parameter contract.
T and d are fixed real data, with 0<d<=2, 0<x<=8 and at most 4096 terms.
T=0 is supported explicitly. For T>0, rho*min(T,d)>=1e-6 is required;
additional cancellation/positivity checks may reject inputs. These checks
are diagnostics, not a certified error bound over the entire input domain.
No clipping, normalization, quadrature fallback, or silent repair is applied.
"""

from dataclasses import dataclass
from fractions import Fraction
import math

import torch

from .operator import _check_parameters, _finite, _first_hit, _tensor
from .regenerative import _policy


@dataclass(frozen=True)
class FiniteRenewalValue:
    first_hit_probability: torch.Tensor  # F(T,x), always a single-cycle CDF
    discounted_first_hit: torch.Tensor  # G_rho(T,x), not survival
    expected_events: torch.Tensor  # M(T), may exceed one
    event_rate: torch.Tensor  # J(T)=dM/dT, not M(T)/T
    discounted_events: torch.Tensor  # H_rho(T), not first-hit G
    active_probability: torch.Tensor
    discounted_active_time: torch.Tensor
    discounted_refractory_time: torch.Tensor
    value: torch.Tensor  # finite-horizon U_T, terminal payoff once
    renewal_terms: int
    cancellation_ratio: float  # diagnostic only; one when no event terms


def finite_renewal_value(distance, params, *, horizon, refractory,
                         active_reward=0.4, hit_reward=1.0, terminal_reward=0.2):
    """Evaluate the fixed trigger/delay/reset policy, starting active at x>0.

    M(T)=sum F(T-k*d,x+k*x_r), H(T)=sum exp(-rho*k*d)*G(T-k*d,x+k*x_r).
    A path is refractory iff an event occurred in (T-d,T], so its probability
    is M(T)-M(T-d). Its discounted occupation is
    [H(T)-exp(-rho*d)*H(T-d)-exp(-rho*T)*(M(T)-M(T-d))]/rho.
    The implementation groups nearby CDF differences and uses expm1 for the
    full-delay contribution, avoiding subtraction of two large cumulative M.
    Rewards are constant, and refractory reward is zero. This is neither E,
    an endogenous boundary optimum, nor the value of a filtered neural net.
    """
    xr = _check_parameters(params)
    _policy(refractory, active_reward, hit_reward, True)
    if (isinstance(horizon, (bool, torch.Tensor)) or not isinstance(horizon, (int, float))
            or not math.isfinite(horizon) or horizon < 0):
        raise ValueError("horizon must be fixed nonnegative finite real data")
    if not 0 < refractory <= 2:
        raise ValueError("finite renewal requires 0<refractory<=2")
    if (isinstance(terminal_reward, (bool, torch.Tensor))
            or not isinstance(terminal_reward, (int, float))
            or not math.isfinite(terminal_reward) or terminal_reward < 0):
        raise ValueError("terminal_reward must be a fixed nonnegative finite real")
    x = _tensor(distance, params.mu)
    _finite("distance", x)
    if isinstance(distance, bool) or x.ndim != 0 or not bool(0 < x <= 8):
        raise ValueError("finite renewal distance must be a scalar in (0,8]")
    end, delay = Fraction(str(horizon)), Fraction(str(refractory))
    count = int(end // delay) + 1
    if count > 4096:
        raise ValueError("finite renewal exceeds the 4096-term budget")
    if horizon == 0:
        zero = (x + sum(params.tensors())) * 0
        one = zero + 1
        return FiniteRenewalValue(zero, zero, zero, zero, zero, one,
                                  zero, zero, zero + terminal_reward, 0, 1.0)
    if bool(params.discount * min(horizon, refractory) < 1e-6):
        raise FloatingPointError("rho*min(T,d)<1e-6: occupation cancellation is unqualified")
    offsets = params.mu.new_tensor([float(k * delay) for k in range(count)])
    times = params.mu.new_tensor([float(end - k * delay) for k in range(count)])
    previous_times = params.mu.new_tensor([float(end - (k + 1) * delay) for k in range(count)])
    distances = x + torch.arange(count, dtype=x.dtype, device=x.device) * xr
    first = _first_hit(distances, times, params.mu, params.sigma)
    previous_first = _first_hit(distances, previous_times, params.mu, params.sigma)
    discounted = _first_hit(distances, times, params.mu, params.sigma, params.discount)
    previous_discounted = _first_hit(distances, previous_times, params.mu, params.sigma, params.discount)
    weights = torch.exp(-params.discount * offsets)
    events = first.sum()
    discounted_events = (weights * discounted).sum()
    # Evaluate f only at positive deadlines, with a safe unselected branch.
    positive = times > 0
    safe_times = torch.where(positive, times, torch.ones_like(times))
    log_density = (torch.log(distances) - torch.log(params.sigma) - 0.5 * math.log(2 * math.pi)
                   - 1.5 * torch.log(safe_times)
                   - (distances + params.mu * safe_times).square() / (2 * params.sigma.square() * safe_times))
    rate = torch.where(positive, torch.exp(log_density), torch.zeros_like(times)).sum()
    recent_events = (first - previous_first).sum()
    recent_discounted = (weights * (discounted - previous_discounted)).sum()
    previous_mass = (weights * previous_discounted).sum()
    at_end = torch.exp(-params.discount * horizon)
    full_wait_numerator = -torch.expm1(-params.discount * refractory) * previous_mass
    recent_terminal = at_end * recent_events
    numerator = full_wait_numerator + recent_discounted - recent_terminal
    scale = full_wait_numerator.abs() + recent_discounted.abs() + recent_terminal.abs()
    ratio = float((numerator.abs() / scale).detach()) if bool(scale > 0) else 1.0
    if not math.isfinite(ratio) or ratio < 1e-7:
        raise FloatingPointError("discounted refractory occupation lost numerical resolution")
    refractory_time = numerator / params.discount
    total_time = -torch.expm1(-params.discount * horizon) / params.discount
    active_time = total_time - refractory_time
    active = 1 - recent_events
    quantities = torch.stack((first[0], discounted[0], events, rate, discounted_events,
                              active, active_time, refractory_time))
    _finite("finite renewal quantities", quantities)
    if bool((quantities < 0).any()) or bool(active > 1) or bool(first[0] > 1):
        raise FloatingPointError("finite renewal positivity/probability is unresolved")
    if bool(discounted[0] > first[0]) or bool(discounted_events > events):
        raise FloatingPointError("discounted event mass exceeds ordinary event count")
    if bool(active_time / total_time < 1e-7):
        raise FloatingPointError("discounted active occupation lost numerical resolution")
    value = active_reward * active_time + hit_reward * discounted_events + terminal_reward * at_end * active
    _finite("finite renewal value", value)
    return FiniteRenewalValue(first[0], discounted[0], events, rate, discounted_events,
                              active, active_time, refractory_time, value, count, ratio)
