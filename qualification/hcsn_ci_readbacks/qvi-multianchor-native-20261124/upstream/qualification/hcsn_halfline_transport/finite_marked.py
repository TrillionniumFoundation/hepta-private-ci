"""Finite positive-delay renewal from a point, with a vector mark changed on release.

The spatial convolution is the existing fixed_renewal identity. Here each
generation is assembled on the live PyTorch graph before marked projection.
"""
from dataclasses import dataclass
import math

import torch

from qualification.hcsn_differentiable.network import LayerState
from qualification.hcsn_differentiable.operator import (
    _first_hit_logprob, _gauss_legendre_unit, _logcdf, _normal_interval_logprob,
)


def _positive_integral(left, right, log_density):
    """Positive fallback on a resolved physical interval; retain scale and gradients."""
    width = right-left
    if width <= 0:
        raise FloatingPointError("integration window is narrower than FP64 resolution")
    def rule(order):
        nodes, weights = _gauss_legendre_unit(order)
        points = left + width * left.new_tensor(nodes)
        log_terms = log_density(points) + left.new_tensor(weights).log()
        return (width.log() + torch.logsumexp(log_terms, dim=0)).exp()
    coarse, fine = rule(32), rule(64)
    if not torch.isclose(coarse, fine, rtol=2e-11, atol=0):
        raise FloatingPointError("positive integral failed order refinement")
    return fine


def _positive_spatial(x, t, mu, sigma, left, right, weight):
    """Resolve cancellation of the reflected images using their positive density."""
    scale = sigma*t.sqrt()
    mean = x+mu*t
    # Restrict the Gaussian at either end to an 80-log-unit drop from its
    # maximum inside the requested interval. The bounds remain in physical y.
    def reach(offset):
        standardized = offset.clamp_min(0)/scale
        return scale*(160/(torch.hypot(standardized, standardized.new_tensor(math.sqrt(160)))+standardized))
    upper = torch.maximum(left,mean)+reach(left-mean)
    if right is not None:
        upper = torch.minimum(upper,right)
    lower = torch.maximum(left,torch.minimum(upper,mean)-reach(mean-upper))
    def log_density(y):
        log_gaussian = -0.5*((y-mean)/scale).square() - scale.log() - math.log(2*math.pi)/2
        return weight + log_gaussian + (-torch.expm1(-2*x*y/scale.square())).log()
    return _positive_integral(lower,upper,log_density)


def _reflected(x, t, mu, sigma, left, right=None, log_weight=0.0):
    scale = sigma * t.sqrt()
    mean = mu * t
    if right is not None and (right-left)/scale < 1e-4:
        return _positive_spatial(x,t,mu,sigma,left,right,log_weight)
    if right is None:
        free = _logcdf((x + mean - left) / scale)
        image = _logcdf((-x + mean - left) / scale)
    else:
        free = _normal_interval_logprob((left - x - mean) / scale, (right - x - mean) / scale)
        image = _normal_interval_logprob((left + x - mean) / scale, (right + x - mean) / scale)
    log_ratio = (image - 2 * mu * x / sigma.square()) - free
    if not bool(torch.isfinite(log_ratio)) or log_ratio > -1e-4:
        return _positive_spatial(x,t,mu,sigma,left,right,log_weight)
    return (log_weight + free).exp() * (-torch.expm1(log_ratio))


def _density(x, t, mu, sigma, y, log_weight=0.0):
    variance = sigma.square() * t
    gaussian_log = -0.5 * ((y - x - mu*t).square() / variance + (2*math.pi*variance).log())
    return (log_weight + gaussian_log).exp() * (-torch.expm1(-2*x*y/variance))


def _active(z, t, mu, sigma, a, edges, points):
    """a=None is the never-released branch, z is the first-passage distance otherwise."""
    if a is None:
        bins = [_reflected(z,t,mu,sigma,l,r) for l,r in zip(edges[:-1],edges[1:])]
        bins.append(_reflected(z,t,mu,sigma,edges[-1]))
        return torch.stack(bins), _density(z, t, mu, sigma, points)
    weight = -2 * mu * z / sigma.square()

    def interval(left, right):
        def below(lo, hi):
            return _reflected(z + a, t, mu, sigma, lo, hi)

        def above(lo, hi):
            return _reflected(a, t, mu, sigma, lo + z, None if hi is None else hi + z, weight)

        if left >= a:
            return above(left, right)
        if right is not None and right <= a:
            return below(left, right)
        return below(left, a) + above(a, right)

    bins = [interval(left, right) for left, right in zip(edges[:-1], edges[1:])]
    bins.append(interval(edges[-1], None))
    # Mask before evaluation so an unused rapidly growing image cannot poison backward.
    left_mask = points <= a
    density = torch.zeros_like(points)
    density = density.masked_scatter(left_mask, _density(z + a, t, mu, sigma, points[left_mask]))
    density = density.masked_scatter(~left_mask, _density(a, t, mu, sigma, points[~left_mask] + z, weight))
    return torch.stack(bins), density


def _log_hit_density(x, t, mu, sigma):
    variance = sigma.square()*t
    return x.log() - t.log() - (2*math.pi*variance).log()/2 - (x+mu*t).square()/(2*variance)


def _hit_window(x, low, high, mu, sigma):
    if high <= 0:
        return x * 0
    upper = _first_hit_logprob(x, high, mu, sigma)
    if low <= 0:
        return upper.exp()
    def positive():
        return _positive_integral(low, high, lambda time: _log_hit_density(x,time,mu,sigma))
    if high-low < high*1e-5:
        return positive()
    if upper <= -math.log(2):
        lower = _first_hit_logprob(x, low, mu, sigma)
        if lower-upper > -1e-5:
            return positive()
        return upper.exp() * (-torch.expm1(lower-upper))
    # Condition finite hit times on eventual passage to avoid subtracting
    # the permanent escape probability at positive drift.
    if mu > 0:
        return (-2*mu*x/sigma.square()).exp() * _hit_window(x, low, high, -mu, sigma)
    zero = x.new_zeros(())
    early = _reflected(x, low, mu, sigma, zero)
    late = _reflected(x, high, mu, sigma, zero)
    if early > 0 and early-late < early*1e-5:
        return positive()
    return early-late


@dataclass(frozen=True)
class FiniteMarkedRenewal:
    state: LayerState
    active_by_release: torch.Tensor
    density_by_release: torch.Tensor
    phase_by_hit: torch.Tensor
    event_probability_by_hit: torch.Tensor
    event_rate_by_hit: torch.Tensor
    marks: torch.Tensor

    @property
    def marked_cumulative_hits(self):
        return self.event_probability_by_hit @ self.marks[:len(self.phase_by_hit)]

    @property
    def marked_event_rate(self):
        return self.event_rate_by_hit @ self.marks[:len(self.phase_by_hit)]

    @property
    def density_content(self):
        return self.density_by_release.T @ self.marks[:len(self.active_by_release)]


def finite_marked_state(x, mu, sigma, a, d, horizon, mark, reset_map,
                        edges, phase_fractions, points, *, max_hits=4096):
    """Return the complete point-source state at T, for d>0 and fixed bin geometry.

    marks[n] is the column-vector content after n releases. Hit n emits
    marks[n-1] and holds that mark throughout its refractory period. A point
    density at the reset surface uses the lower-side branch. State projection
    preserves bin-integrated probability and signed content.
    """
    vals = (x, mu, sigma, a, d, horizon, mark, reset_map, edges, phase_fractions, points)
    if any(not isinstance(v, torch.Tensor) or v.dtype != torch.float64 or
           v.device != x.device or not bool(torch.isfinite(v).all()) for v in vals):
        raise ValueError("all inputs must be finite FP64 tensors on one device")
    if any(v.ndim for v in vals[:6]) or min(x, sigma, a, d, horizon) <= 0:
        raise ValueError("x, sigma, a, d and horizon must be positive scalars and mu scalar")
    if mark.ndim != 1 or not mark.numel() or reset_map.shape != (len(mark), len(mark)):
        raise ValueError("mark and its square linear release map must have compatible dimensions")
    for grid in (edges, phase_fractions):
        if grid.ndim != 1 or len(grid) < 2 or grid.requires_grad or grid[0] != 0 or not (grid.diff() > 0).all():
            raise ValueError("fixed grid edges must increase from zero")
    if phase_fractions[-1] != 1 or points.ndim != 1 or bool((points < 0).any()):
        raise ValueError("phase fractions must end at one and density probes must be a nonnegative vector")
    if type(max_hits) is not int or max_hits < 1:
        raise ValueError("max_hits must be a positive resource limit")
    active, probes = _active(x, horizon, mu, sigma, None, edges, points)
    active_rows, density_rows, marks = [active], [probes], [mark]
    phase_rows, hit_probs, rates = [], [], []
    n = 1
    while (n-1)*d < horizon:
        if n > max_hits:
            raise ValueError("required hit generations exceed max_hits")
        z = x + (n-1)*a
        hit_time = horizon - (n-1)*d
        release_time = horizon - n*d
        hit_probs.append(_first_hit_logprob(z, hit_time, mu, sigma).exp())
        rates.append(_log_hit_density(z,hit_time,mu,sigma).exp())
        deadlines = [release_time, *(release_time + d*f for f in phase_fractions[1:-1]), hit_time]
        phase_rows.append(torch.stack([_hit_window(z, l, r, mu, sigma) for l, r in zip(deadlines, deadlines[1:])]))
        if release_time > 0:
            active, probes = _active(z, release_time, mu, sigma, a, edges, points)
            active_rows.append(active)
            density_rows.append(probes)
            marks.append(reset_map @ marks[-1])
        n += 1
    active, phases, densities = map(torch.stack, (active_rows, phase_rows, density_rows))
    marks, hit_probs, rates = map(torch.stack, (marks, hit_probs, rates))
    probability = torch.cat((active.sum(0), phases.sum(0)))
    content = torch.cat((active.T @ marks[:len(active)], phases.T @ marks[:len(phases)]))
    if any(not bool(torch.isfinite(v).all()) or bool((v < 0).any()) for v in (active, phases, densities, hit_probs, rates)):
        raise FloatingPointError("renewal probability or density is numerically unresolved")
    if not bool(torch.isfinite(content).all()) or abs(probability.sum()-1) > 3e-11:
        raise FloatingPointError("unresolved content or total mass")
    result = FiniteMarkedRenewal(LayerState(probability[None], content[None]), active, densities, phases, hit_probs, rates, marks)
    outputs = (marks, result.marked_cumulative_hits, result.marked_event_rate, result.density_content)
    if any(not bool(torch.isfinite(v).all()) for v in outputs):
        raise FloatingPointError("a signed marked output is outside the FP64 domain")
    return result
