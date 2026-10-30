"""Two-layer sampled renewal SNN with an explicit conditional-moment surrogate.

Forward simulation samples continuous first passages and killed endpoints. The
straight-through backward rule differentiates conditional moments, and is biased
for the composed stochastic network objective. Local gradient checks do not turn
that surrogate into an unbiased gradient of the sampled-network loss.
"""

from dataclasses import dataclass
import math

import numpy as np
import torch
from torch import nn

from ..first_passage_cell.cell import sample_survivor


@dataclass
class Segment:
    voltage: np.ndarray
    refractory: np.ndarray
    count: np.ndarray
    active: np.ndarray
    events: list


def _hitting_time(distance, drive, sigma, rng):
    """Vectorized stable inverse-Gaussian/Lévy law for an upper barrier."""
    x, v, s = np.broadcast_arrays(distance, drive, sigma)
    z = np.maximum(np.abs(rng.standard_normal(x.shape)), np.finfo(float).tiny)
    av = np.abs(v)
    zero = av == 0
    safe = np.where(zero, 1.0, av)
    ly = 2 * np.log(s) + 2 * np.log(z) - math.log(2) - np.log(x) - np.log(safe)
    ld = 2 * np.arcsinh(np.exp(0.5 * (ly - math.log(2))))
    lm = np.log(x) - np.log(safe)
    flip = rng.random(x.shape) > 1 / (1 + np.exp(-ld))
    log_t = np.where(flip, lm + ld, lm - ld)
    log_t = np.where(zero, 2 * (np.log(x) - np.log(s) - np.log(z)), log_t)
    hit = np.exp(log_t)
    probability = np.exp(np.minimum(0.0, 2 * v * x / s**2))
    return np.where(rng.random(x.shape) < probability, hit, np.inf)


def _survivors(x, drive, sigma, duration, rng):
    """Brownian-bridge rejection; exact killed-CDF fallback bounds runtime."""
    result = np.empty_like(x)
    pending = np.arange(len(x))
    for _ in range(32):
        if not len(pending):
            break
        j = pending
        variance = sigma[j] ** 2 * duration[j]
        y = rng.normal(x[j] - drive[j] * duration[j], np.sqrt(variance))
        bridge = -np.expm1(-2 * x[j] * np.maximum(0.0, y) / variance)
        accept = (y > 0) & (rng.random(len(j)) < bridge)
        result[j[accept]] = y[accept]
        pending = j[~accept]
    for j in pending:
        result[j] = sample_survivor(float(x[j]), -float(drive[j]), float(sigma[j]),
                                    float(duration[j]), rng)
    return result


def sample_segment(voltage, pending, drive, sigma, threshold, reset, refractory,
                   duration, rng, *, retain_events=False):
    """Propagate every hit, reset and remaining refractory time in one segment."""
    values = np.broadcast_arrays(voltage, pending, drive, sigma, threshold, reset, refractory)
    shape = values[0].shape
    v, p, d, s, b, r, a = [np.array(z, dtype=float, copy=True).ravel() for z in values]
    if (duration <= 0 or not np.isfinite(values).all() or np.any(s <= 0)
            or np.any(a <= 0) or np.any(r >= b) or np.any(v >= b)
            or np.any(p < 0) or np.any(p > a + 1e-12)):
        raise ValueError("Invalid continuous-spike segment state")
    remaining = np.full_like(v, duration)
    counts = np.zeros_like(v)
    active = np.zeros_like(v)
    events = []
    for _ in range(int(math.ceil(duration / float(a.min()))) + 2):
        hold = np.minimum(p, remaining)
        p -= hold
        remaining -= hold
        idx = np.flatnonzero(remaining > 1e-14)
        if not len(idx):
            break
        times = _hitting_time(b[idx] - v[idx], d[idx], s[idx], rng)
        hit_mask = times <= remaining[idx]
        hit = idx[hit_mask]
        if len(hit):
            h = times[hit_mask]
            active[hit] += h
            remaining[hit] -= h
            counts[hit] += 1
            if retain_events:
                events.extend((int(j), float(duration - remaining[j])) for j in hit)
            v[hit], p[hit] = r[hit], a[hit]
        end = idx[~hit_mask]
        if len(end):
            y = _survivors(b[end] - v[end], d[end], s[end], remaining[end], rng)
            v[end] = b[end] - y
            active[end] += remaining[end]
            remaining[end] = 0.0
    if np.any(remaining > 1e-12):
        raise ArithmeticError("Refractory event bound was exceeded")
    return Segment(*(z.reshape(shape) for z in (v, p, counts, active)), events)


def passage_cdf(distance, drive, sigma, time):
    """Differentiable upper-barrier CDF on the registered interior domain."""
    t = time.clamp_min(1e-12)
    sd = sigma * torch.sqrt(t)
    first = torch.special.log_ndtr((-distance + drive * t) / sd)
    second = 2 * drive * distance / sigma.square() + torch.special.log_ndtr(
        (-distance - drive * t) / sd)
    value = torch.exp(first) + torch.exp(second)
    return torch.where(time > 0, value.clamp(max=1.0), torch.zeros_like(value))


def renewal_moments(voltage, pending, drive, sigma, threshold, reset, refractory,
                    duration, *, order=8, refractory_floor=0.04):
    """Conditional moments from finite renewal sums and Gauss–Legendre quadrature.

    Count is analytic. Active time and remaining refractory expectation use the
    stated quadrature. Identical drift/diffusion within the segment is required.
    """
    horizon = (duration - pending).clamp_min(0.0)
    count = int(math.ceil(duration / refractory_floor)) + 1
    n = torch.arange(count, dtype=voltage.dtype, device=voltage.device)
    x = (threshold - voltage)[..., None] + n * (threshold - reset)[..., None]
    upper = (horizon[..., None] - n * refractory[..., None]).clamp_min(0)
    lower = (upper - refractory[..., None]).clamp_min(0)
    f = passage_cdf(x, drive[..., None], sigma[..., None], upper)
    nodes, weights = np.polynomial.legendre.leggauss(order)
    nodes = torch.as_tensor(nodes, dtype=voltage.dtype, device=voltage.device)
    weights = torch.as_tensor(weights, dtype=voltage.dtype, device=voltage.device)
    half = (upper - lower) / 2
    times = ((upper + lower) / 2)[..., None] + half[..., None] * nodes
    cdf = passage_cdf(x[..., None], drive[..., None, None], sigma[..., None, None], times)
    lost = (half * (cdf * weights).sum(-1)).sum(-1)
    number = f.sum(-1)
    active = horizon - lost
    end_voltage = voltage + drive * active + (reset - threshold) * number
    end_pending = (pending - duration).clamp_min(0) + refractory * number - lost
    return {"count": number, "active": active, "voltage": end_voltage,
            "refractory": end_pending}


def _straight_through(sample, expectation):
    observed = torch.as_tensor(sample, dtype=expectation.dtype, device=expectation.device)
    return observed + expectation - expectation.detach()


class RenewalNetwork(nn.Module):
    """55 active coefficients, two physical layers, one-segment synaptic delay."""

    def __init__(self, *, kind="first_passage", seed=0, dtype=torch.float64):
        super().__init__()
        if kind not in {"first_passage", "lif"}:
            raise ValueError("Unknown spike dynamics")
        self.kind = kind
        generator = torch.Generator().manual_seed(seed)
        self.w1 = nn.Parameter(torch.randn(2, 3, generator=generator, dtype=dtype) * 0.7)
        self.w2 = nn.Parameter(torch.eye(3, dtype=dtype) * 0.8 +
                               torch.randn(3, 3, generator=generator, dtype=dtype) * 0.2)
        self.bias = nn.Parameter(torch.full((2, 3), 1.4, dtype=dtype))
        self.raw_sigma = nn.Parameter(torch.full((2, 3), -0.8, dtype=dtype))
        self.raw_threshold = nn.Parameter(torch.full((2, 3), -0.8, dtype=dtype))
        self.raw_reset = nn.Parameter(torch.zeros(2, 3, dtype=dtype))
        self.raw_refractory = nn.Parameter(torch.full((2, 3), -1.1, dtype=dtype))
        self.raw_decay = nn.Parameter(torch.zeros(2, 3, dtype=dtype))
        self.readout = nn.Parameter(torch.randn(3, generator=generator, dtype=dtype) * 0.3)
        self.output_bias = nn.Parameter(torch.zeros((), dtype=dtype))

    def physical(self):
        return {"sigma": 0.08 + 0.32 * torch.sigmoid(self.raw_sigma),
                "threshold": 0.5 + 0.9 * torch.sigmoid(self.raw_threshold),
                "reset": 0.2 * torch.tanh(self.raw_reset),
                "refractory": 0.04 + 0.14 * torch.sigmoid(self.raw_refractory),
                "decay": 0.3 + 1.2 * torch.sigmoid(self.raw_decay)}

    def _lif(self, v, p, drive, pars, dt, rng):
        """Euler LIF comparator, 20 substeps, hard events and surrogate gradients."""
        h = dt / 20
        counts, active = torch.zeros_like(v), torch.zeros_like(v)
        for _ in range(20):
            soft_available = torch.sigmoid(-80 * p)
            available = (p.detach() <= 0).to(v.dtype) + soft_available - soft_available.detach()
            noise = torch.as_tensor(rng.standard_normal(v.shape), dtype=v.dtype)
            proposal = v + available * ((drive - v) * h + pars["sigma"] * math.sqrt(h) * noise)
            distance = proposal - pars["threshold"]
            smooth = torch.sigmoid(10 * distance)
            hard = (distance.detach() >= 0).to(v.dtype) * available
            fired = hard + available * (smooth - smooth.detach())
            v = proposal * (1 - fired) + pars["reset"] * fired
            # Smooth refractory release only changes the backward rule.
            remaining = (p - h).clamp_min(0)
            p = remaining * (1 - fired) + pars["refractory"] * fired
            counts = counts + fired
            active = active + available * h
        return v, p, counts, active

    def forward(self, inputs, *, noise_seed, capture=False):
        if inputs.ndim != 3 or inputs.shape[2] != 2:
            raise ValueError("Expected batch by time by two inputs")
        rng = np.random.default_rng(noise_seed)
        batch = inputs.shape[0]
        voltage = [inputs.new_zeros(batch, 3) for _ in range(2)]
        pending = [inputs.new_zeros(batch, 3) for _ in range(2)]
        trace = [inputs.new_zeros(batch, 3) for _ in range(2)]
        pars = self.physical()
        logs = []
        dt = 0.25
        for step in range(inputs.shape[1]):
            old_first = trace[0]
            for layer in range(2):
                signal = inputs[:, step] if layer == 0 else old_first
                weights = self.w1 if layer == 0 else self.w2
                drive = 6 * torch.tanh((signal @ weights + self.bias[layer]) / 6)
                coeff = {name: val[layer].expand(batch, 3) for name, val in pars.items()}
                if self.kind == "first_passage":
                    moments = None
                    if torch.is_grad_enabled():
                        moments = renewal_moments(voltage[layer], pending[layer], drive,
                                                  coeff["sigma"], coeff["threshold"], coeff["reset"],
                                                  coeff["refractory"], dt)
                    args = (voltage[layer], pending[layer], drive, coeff["sigma"],
                            coeff["threshold"], coeff["reset"], coeff["refractory"])
                    segment = sample_segment(*(z.detach().numpy() for z in args), dt, rng,
                                             retain_events=capture)
                    if moments is None:
                        v, p, count, active = [torch.as_tensor(z, dtype=inputs.dtype) for z in
                                               (segment.voltage, segment.refractory,
                                                segment.count, segment.active)]
                    else:
                        v = _straight_through(segment.voltage, moments["voltage"])
                        p = _straight_through(segment.refractory, moments["refractory"])
                        count = _straight_through(segment.count, moments["count"])
                        active = _straight_through(segment.active, moments["active"])
                else:
                    v, p, count, active = self._lif(voltage[layer], pending[layer], drive, coeff, dt, rng)
                    segment = None
                decay = torch.exp(-dt / coeff["decay"])
                trace[layer] = trace[layer] * decay + count * (1 - decay) / dt
                voltage[layer], pending[layer] = v, p
                if capture:
                    logs.append({"step": step, "layer": layer, "count": count.detach().numpy(),
                                 "active": active.detach().numpy(), "voltage": v.detach().numpy(),
                                 "refractory": p.detach().numpy(),
                                 "events": [] if segment is None else segment.events})
        logits = trace[1] @ self.readout + self.output_bias
        return (logits, logs) if capture else logits


class RecurrentNetwork(nn.Module):
    """55-parameter two-layer leaky tanh RNN with learned gains and time scales."""

    def __init__(self, *, seed=0, dtype=torch.float64):
        super().__init__()
        generator = torch.Generator().manual_seed(seed)
        self.w1 = nn.Parameter(torch.randn(2, 3, generator=generator, dtype=dtype) * 0.7)
        self.w2 = nn.Parameter(torch.randn(3, 3, generator=generator, dtype=dtype) * 0.5)
        self.recurrent = nn.Parameter(torch.randn(2, 3, 3, generator=generator, dtype=dtype) * 0.4)
        self.bias = nn.Parameter(torch.zeros(2, 3, dtype=dtype))
        self.raw_gain = nn.Parameter(torch.zeros(2, 3, dtype=dtype))
        self.raw_decay = nn.Parameter(torch.zeros(2, 3, dtype=dtype))
        self.readout = nn.Parameter(torch.randn(3, generator=generator, dtype=dtype) * 0.3)
        self.output_bias = nn.Parameter(torch.zeros((), dtype=dtype))

    def forward(self, inputs, *, noise_seed=None, capture=False):
        state = [inputs.new_zeros(inputs.shape[0], 3) for _ in range(2)]
        decay = torch.exp(-0.25 / (0.3 + 1.2 * torch.sigmoid(self.raw_decay)))
        gain = 0.5 + torch.sigmoid(self.raw_gain)
        for t in range(inputs.shape[1]):
            old_first = state[0]
            for layer in range(2):
                signal = inputs[:, t] if layer == 0 else old_first
                weights = self.w1 if layer == 0 else self.w2
                candidate = torch.tanh(gain[layer] * (signal @ weights +
                                       state[layer] @ self.recurrent[layer] + self.bias[layer]))
                state[layer] = decay[layer] * state[layer] + (1 - decay[layer]) * candidate
        value = state[1] @ self.readout + self.output_bias
        return (value, []) if capture else value
