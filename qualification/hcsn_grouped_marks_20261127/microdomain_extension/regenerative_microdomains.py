"""Expected repeated first-hit events for independently diffusing, jointly reset microdomains."""
import math
from typing import NamedTuple

import torch
from torch import Tensor


class CountInterval(NamedTuple):
    lower: Tensor
    upper: Tensor
    per_event_lower: Tensor
    per_event_upper: Tensor


def _finite_horizon_cdf(distance: Tensor, times: Tensor, copies: int, drift: float, volatility: float):
    """CDF for the first of the independent paths. Times must be positive."""
    x = distance.clamp_min(0.)
    scale = volatility * times.sqrt()
    mean_motion = drift * times
    log_f = torch.logaddexp(torch.special.log_ndtr((-x - mean_motion)/scale),
                            -2*drift*x/(volatility**2) + torch.special.log_ndtr((mean_motion-x)/scale)).clamp_max(0.)
    single = torch.exp(log_f)
    if copies == 1:
        cdf = single
    else:
        safe = torch.where(single < .5, single, 0.)
        cdf = torch.where(single < .5, -torch.expm1(copies*torch.log1p(-safe)),
                          1-(-torch.expm1(log_f)).pow(copies))
    return torch.where(distance > 0, cdf, 1.)


def _floor_wait_mass(distance: Tensor, times: Tensor, copies: int, drift: float, volatility: float):
    """P(floor(wait/delta)=j), retaining precisely the bins that can affect the horizon."""
    cumulative = _finite_horizon_cdf(distance, times, copies, drift, volatility)
    return torch.diff(cumulative, prepend=cumulative.new_zeros(1))


def _prefix_convolution(first: Tensor, second: Tensor, size: int):
    """Linear convolution prefix; zero-pad before the FFT to exclude wrap-around."""
    length = 1 << (len(first) + len(second) - 2).bit_length()
    return torch.fft.irfft(torch.fft.rfft(first,n=length) * torch.fft.rfft(second,n=length),
                           n=length)[:size]


def repeated_count_bounds(distance: Tensor, reset: Tensor, copies: int, drift: float, volatility: float,
                          horizon: float, refractory: float, bins: int) -> CountInterval:
    """Coupled floor/ceil bounds for a fixed-wall count; refractory must be on the time grid.

    Each hit resets all paths and they wait for a common positive absolute refractory interval
    before restarting from reset. Return the expected count and order-wise event probabilities
    as bounds in exact arithmetic. Float64 FFTs introduce ordinary numerical rounding.
    """
    if any(v.numel()!=1 or v.ndim!=0 or v.dtype != torch.float64 or not torch.isfinite(v)
           for v in (distance, reset)) or distance.device != reset.device:
        raise ValueError('distance and reset must be finite scalar float64 tensors on one device')
    if float(reset.detach())<=0 or type(copies) is not int or copies<1 or type(bins) is not int or bins<1:
        raise ValueError('reset, copy count and bin count must be positive')
    if not all(math.isfinite(p) for p in (volatility,drift,horizon,refractory)) or min(volatility,horizon,refractory)<=0:
        raise ValueError('use finite drift and positive volatility, horizon and absolute refractory time')
    delta = horizon/bins
    refractory_bins = round(refractory/delta)
    if refractory_bins < 1 or not math.isclose(refractory, refractory_bins*delta, rel_tol=1e-12,abs_tol=0.):
        raise ValueError('refractory time must be a positive integer number of grid steps')
    times = torch.arange(1,bins+2,dtype=distance.dtype,device=distance.device)*delta
    initial = _floor_wait_mass(distance,times,copies,drift,volatility)
    reset_wait = _floor_wait_mass(reset,times,copies,drift,volatility)
    first_prob = _finite_horizon_cdf(distance,times[bins-1],copies,drift,volatility)
    lower,upper=[first_prob],[first_prob]
    # Live first waiting times and all reset waits are continuous; an initially stopped unit releases at t=0.
    live_initial = int(float(distance.detach())>0)
    for k in range(2, bins//refractory_bins+2):
        remaining = bins-(k-1)*refractory_bins
        initial = _prefix_convolution(initial, reset_wait, remaining+1)
        ceil_shift = live_initial + k-1
        upper.append(initial.sum())
        lower.append(initial[:remaining-ceil_shift+1].sum() if remaining>=ceil_shift else initial.new_zeros(()))
    lo,hi=torch.stack(lower),torch.stack(upper)
    return CountInterval(lo.sum(),hi.sum(),lo,hi)


def repeated_content_release(bounds: CountInterval, fraction: Tensor) -> tuple[Tensor, Tensor]:
    """Bound the expected fraction of a fixed value written after N partial-release events.

    Per event, h <- (1-fraction)*h + fraction*value. The value and fraction stay fixed
    within the evaluated horizon. The case fraction=1 recovers the first-hit port.
    """
    if (fraction.ndim!=0 or fraction.dtype!=bounds.lower.dtype or fraction.device!=bounds.lower.device
            or not torch.isfinite(fraction) or float(fraction.detach())<0 or float(fraction.detach())>1):
        raise ValueError('the per-event fraction must be a scalar in [0,1] on the count device and dtype')
    # Explicit recurrence handles zero and one cleanly, including the derivative at either endpoint.
    retention = torch.ones_like(fraction)
    weights = []
    for _ in range(len(bounds.per_event_lower)):
        weights.append(fraction*retention)
        retention = retention*(1-fraction)
    weights = torch.stack(weights)
    return (weights@bounds.per_event_lower, weights@bounds.per_event_upper)
