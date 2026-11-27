"""Differentiable finite CTMC with exact deterministic-delay release laws.

The finite spatial generator is an explicit approximation to a diffusion.
Within that model each frozen-input segment uses a matrix exponential. Pending
release laws, including signed marks and their event-time reset distributions,
are state: no history replay, uniform age deposit or totals-only reconstruction.
Logical time/delay are fixed Fractions; tensor gradients include the generator,
reset, initial state, rewards and discount, but not logical event scheduling.
"""

from dataclasses import dataclass, replace
from fractions import Fraction

import torch


@dataclass(frozen=True)
class Physics:
    generator: torch.Tensor
    lower: torch.Tensor
    upper: torch.Tensor
    reset: torch.Tensor
    reward: torch.Tensor
    escape_reward: torch.Tensor
    spike_reward: torch.Tensor
    discount: torch.Tensor
    delay: Fraction = Fraction(1, 5)

    def __post_init__(self):
        q = self.generator
        n = q.shape[0]
        values = (q, self.lower, self.upper, self.reset, self.reward,
                  self.escape_reward, self.spike_reward, self.discount)
        if q.shape != (n, n) or not 1 <= n <= 64:
            raise ValueError("finite square spatial generator of order 1..64 required")
        if any(v.dtype != q.dtype or v.device != q.device for v in values):
            raise ValueError("physics tensors must share dtype and device")
        if q.dtype not in (torch.float32, torch.float64) or any(
                not bool(torch.isfinite(v).all()) for v in values):
            raise ValueError("finite FP32/FP64 physics required")
        if any(v.shape != (n,) for v in values[1:5]) or any(
                v.ndim != 0 for v in values[5:]):
            raise ValueError("physics shape mismatch")
        tolerance = 2e-6 if q.dtype == torch.float32 else 2e-13
        off = q - torch.diag(torch.diag(q))
        if bool((off < 0).any()) or any(bool((v < 0).any())
                for v in (self.lower, self.upper, self.reset)):
            raise ValueError("negative CTMC rate/reset")
        if not torch.allclose(q.sum(1) + self.lower + self.upper,
                              torch.zeros_like(self.lower), atol=tolerance, rtol=0):
            raise ValueError("generator does not conserve probability")
        if not torch.allclose(self.reset.sum(), q.new_tensor(1.),
                              atol=tolerance, rtol=0):
            raise ValueError("reset must sum to one")
        if bool(self.discount < 0) or not isinstance(self.delay, Fraction) or self.delay <= 0:
            raise ValueError("nonnegative discount and positive rational delay required")


@dataclass(frozen=True)
class Flux:
    start: Fraction
    end: Fraction
    alpha: torch.Tensor
    generator: torch.Tensor
    output: torch.Tensor
    reset: torch.Tensor


@dataclass(frozen=True)
class Atom:
    time: Fraction
    mass: torch.Tensor
    reset: torch.Tensor


@dataclass(frozen=True)
class State:
    time: Fraction
    active: torch.Tensor
    upper: torch.Tensor
    hits: torch.Tensor
    discounted_hits: torch.Tensor
    occupation: torch.Tensor
    value: torch.Tensor
    discount_factor: torch.Tensor
    pending: tuple = ()

    def tensors(self):
        yield from (self.active, self.upper, self.hits, self.discounted_hits,
                    self.occupation, self.value, self.discount_factor)
        for packet in self.pending:
            if isinstance(packet, Flux):
                yield from (packet.alpha, packet.generator, packet.output, packet.reset)
            else:
                yield from (packet.mass, packet.reset)

    def tensor_bytes(self):
        """Logical tensor payload, including repeats; excludes autograd/allocator overhead."""
        return sum(t.numel() * t.element_size() for t in self.tensors())


@dataclass
class Work:
    max_dimension: int = 256
    max_packets: int = 256
    max_exponentials: int = 2048
    exponentials: int = 0
    largest_dimension: int = 0

    def check_packets(self, state):
        if any(type(value) is not int or value < 1 for value in
               (self.max_dimension, self.max_packets, self.max_exponentials)):
            raise ValueError("positive integer work limits required")
        if len(state.pending) > self.max_packets:
            raise RuntimeError("declared pending-packet budget exhausted")

    def exponential(self, matrix):
        if matrix.shape[0] > self.max_dimension or self.exponentials >= self.max_exponentials:
            raise RuntimeError("declared matrix-exponential work budget exhausted")
        self.exponentials += 1
        self.largest_dimension = max(self.largest_dimension, matrix.shape[0])
        result = torch.matrix_exp(matrix)
        if not bool(torch.isfinite(result).all()):
            raise FloatingPointError("unresolved matrix exponential")
        return result


def initial(active):
    """Channel zero is probability; subsequent channels are signed content mass."""
    if (active.ndim != 2 or active.shape[0] < 1 or active.shape[1] < 1
            or active.dtype not in (torch.float32, torch.float64)
            or not bool(torch.isfinite(active).all()) or bool((active[0] < 0).any())):
        raise ValueError("finite channel-by-space state required")
    z = active.new_zeros(active.shape[0])
    return State(Fraction(0), active, z, z, z, z, z, active.new_ones(()))


def _integrals(generator, weights, duration, work):
    n, k = weights.shape
    augmented = torch.cat((torch.cat((generator, weights), dim=1),
                           generator.new_zeros(k, n + k)), dim=0)
    result = work.exponential(augmented * duration)
    return result[:n, :n], result[:n, n:]


def refractory(state, work=None):
    """Total mass and each signed mark still waiting for their exact release times."""
    work = Work() if work is None else work
    work.check_packets(state)
    total = state.upper.new_zeros(state.upper.shape)
    for p in state.pending:
        if isinstance(p, Atom):
            if p.time > state.time:
                total = total + p.mass
            continue
        start = max(state.time, p.start)
        if start >= p.end:
            continue
        alpha = p.alpha @ work.exponential(p.generator * float(start - p.start))
        _, integral = _integrals(p.generator, p.output[:, None], float(p.end - start), work)
        total = total + (alpha @ integral).squeeze(1)
    if not bool(torch.isfinite(total).all()):
        raise FloatingPointError("unresolved refractory mass")
    return total


def intervene(state, physics, fraction, work=None):
    """Release an explicitly supplied swept fraction of each finite spatial cell.

    The caller owns its boundary-to-cell overlap rule. This consumes exactly
    the same fractions of probability and signed content and retains an atom
    at the event-time reset target after the fixed delay. It does not silently
    interpret a changing static threshold as a moving diffusion boundary.
    """
    work = Work() if work is None else work
    work.check_packets(state)
    if len(state.pending) >= work.max_packets:
        raise RuntimeError("declared pending-packet budget exhausted")
    if fraction.shape != physics.lower.shape or not bool(torch.isfinite(fraction).all()) or bool(
            ((fraction < 0) | (fraction > 1)).any()):
        raise ValueError("finite swept fractions in [0,1] required")
    mass = state.active @ fraction
    discounted = state.discount_factor * mass
    result = replace(state, active=state.active * (1 - fraction), hits=state.hits + mass,
                     discounted_hits=state.discounted_hits + discounted,
                     value=state.value + physics.spike_reward * discounted,
                     pending=state.pending + (Atom(state.time + physics.delay, mass, physics.reset.clone()),))
    if any(not bool(torch.isfinite(t).all()) for t in result.tensors()):
        raise FloatingPointError("unresolved intervention state")
    return result


def advance(state, physics, target, work=None):
    """Advance complete current state under one frozen-input spatial generator.

    Physics may change between calls on the same spatial grid. Pending flux
    generators/reset targets stay those recorded at emission. Upper exits are
    permanently active and nonreturning, with their declared escape reward.
    """
    if not isinstance(target, Fraction) or target < state.time:
        raise ValueError("nondecreasing rational target required")
    work = Work() if work is None else work
    work.check_packets(state)
    n = physics.lower.numel()
    if state.active.ndim != 2 or state.active.shape[1] != n:
        raise ValueError("state/grid mismatch")
    if any(t.dtype != physics.generator.dtype or t.device != physics.generator.device
           or not bool(torch.isfinite(t).all()) for t in state.tensors()):
        raise ValueError("state tensors must be finite and compatible with physics")
    while True:
        active, remaining = state.active, []
        for p in state.pending:
            if isinstance(p, Atom) and p.time <= state.time:
                if p.time < state.time:
                    raise ValueError("overdue release atom")
                active = active + p.mass[:, None] * p.reset
            elif isinstance(p, Atom) or p.end > state.time:
                remaining.append(p)
        state = replace(state, active=active, pending=tuple(remaining))
        if state.time == target:
            if any(not bool(torch.isfinite(t).all()) for t in state.tensors()):
                raise FloatingPointError("unresolved current state")
            return state
        if len(remaining) >= work.max_packets:
            raise RuntimeError("declared pending-packet budget exhausted")
        stop = min(target, state.time + physics.delay)
        sources = []
        for p in remaining:
            knots = (p.time,) if isinstance(p, Atom) else (p.start, p.end)
            for knot in knots:
                if state.time < knot < stop:
                    stop = knot
            if isinstance(p, Flux) and p.start <= state.time < p.end:
                sources.append(p)
        q = physics.generator
        base = torch.cat((torch.cat((q, physics.upper[:, None]), 1), q.new_zeros(1, n + 1)), 0)
        dimension = n + 1 + sum(p.generator.shape[0] for p in sources)
        if dimension + 3 > work.max_dimension:
            raise RuntimeError("declared augmented-state budget exhausted")
        alpha = [torch.cat((state.active, state.upper[:, None]), 1)]
        if sources:
            for p in sources:
                alpha.append(p.alpha @ work.exponential(p.generator * float(state.time - p.start)))
            driving = torch.cat([p.output[:, None] * torch.cat((p.reset, q.new_zeros(1)))[None, :]
                                 for p in sources], 0)
            generator = torch.cat((torch.cat((base, q.new_zeros(n + 1, dimension - n - 1)), 1),
                                   torch.cat((driving, torch.block_diag(*[p.generator for p in sources])), 1)), 0)
        else:
            generator = base
        alpha = torch.cat(alpha, 1)
        lower = torch.cat((physics.lower, q.new_zeros(dimension - n)))
        occupation = torch.cat((q.new_ones(n + 1), q.new_zeros(dimension - n - 1)))
        reward = torch.cat((physics.reward, physics.escape_reward.reshape(1), q.new_zeros(dimension - n - 1)))
        duration = float(stop - state.time)
        transition, integral = _integrals(generator, torch.stack((lower, occupation), 1), duration, work)
        current = alpha @ transition
        increments = alpha @ integral
        _, discounted = _integrals(generator - physics.discount * torch.eye(dimension, dtype=q.dtype, device=q.device),
                                    torch.stack((lower, reward), 1), duration, work)
        credits = state.discount_factor * (alpha @ discounted)
        packet = Flux(state.time + physics.delay, stop + physics.delay, alpha,
                      generator, lower, physics.reset.clone())
        state = State(stop, current[:, :n], current[:, n], state.hits + increments[:, 0],
                      state.discounted_hits + credits[:, 0], state.occupation + increments[:, 1],
                      state.value + credits[:, 1] + physics.spike_reward * credits[:, 0],
                      state.discount_factor * torch.exp(-physics.discount * duration),
                      tuple(remaining) + (packet,))
