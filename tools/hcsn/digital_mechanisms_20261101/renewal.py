"""A distinct continuous-time finite CTMC, not the historical image-bin kernel.

Fifteen interior voltage nodes, two refractory nodes, and signed boundary jumps.
The same Q supplies forecasts, first-event laws, repeated counts, and sampling.
Future inputs are piecewise constant and must be explicitly specified by caller.
"""
from dataclasses import dataclass, field
import math
from pathlib import Path
import struct

import numpy as np
from scipy.linalg import expm
from scipy.special import ndtr

MASK64 = (1 << 64) - 1
SCHEMA = "renewal-upwind-ctmc-v1"


def generator(physical, symbol=0., reliability=.5, n_grid=15):
    """Positive upwind rates for mu*d/dx + sigma²/2*d²/dx².

    Unlike old midpoint projection, active nodes have spacing 2B/(n+1).
    Boundary jump rates enter refractory. Recovery uses folded Gaussian reset
    (normalized sd .12), preserving baseline physical reset-center semantics.
    """
    keys = ("boundary", "diffusion", "gain", "drift_bias", "reset_plus", "reset_minus", "recovery_rate")
    p = {k: float(physical[k]) for k in keys}
    if (not all(math.isfinite(v) for v in p.values()) or p["boundary"] <= 0
            or p["diffusion"] <= 0 or p["recovery_rate"] <= 0
            or symbol not in (-1, 0, 1) or not math.isfinite(reliability)
            or not 0 <= reliability <= 1 or n_grid < 3 or n_grid % 2 != 1):
        raise ValueError("invalid finite CTMC physical/context parameters")
    b, sigma = p["boundary"], p["diffusion"]
    h = 2*b/(n_grid+1)
    x = np.linspace(-b+h, b-h, n_grid)
    mu = p["drift_bias"] + p["gain"]*symbol*(2*reliability-1)
    down, up = sigma*sigma/(2*h*h)+max(-mu, 0)/h, sigma*sigma/(2*h*h)+max(mu, 0)/h
    q = np.zeros((n_grid+2, n_grid+2))
    for i in range(n_grid):
        q[i, i-1 if i else n_grid] = down
        q[i, i+1 if i+1 < n_grid else n_grid+1] = up
    edges = (x[:-1]+x[1:])/2
    for side, name in enumerate(("reset_minus", "reset_plus")):
        cdf = ndtr((edges-p[name])/(.12*b))
        reset = np.diff(np.r_[0., cdf, 1.])
        q[n_grid+side, :n_grid] = p["recovery_rate"]*reset
    np.fill_diagonal(q, -q.sum(axis=1))
    validate_generator(q, n_grid)
    return q, x


def validate_generator(q, n_grid):
    q = np.asarray(q, dtype=np.float64)
    off = q.copy()
    np.fill_diagonal(off, 0.)
    if (q.shape != (n_grid+2, n_grid+2) or not np.isfinite(q).all()
            or np.any(off < 0) or np.any(np.diag(q) >= 0)
            or np.max(np.abs(q.sum(axis=1))) > 2e-12):
        raise ValueError("invalid generator")
    if np.any(q[n_grid:, n_grid:]-np.diag(np.diag(q[n_grid:, n_grid:]))):
        raise ValueError("refractory must release into active nodes")
    return q


def transition(q, duration):
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("duration must be finite and nonnegative")
    t = expm(np.asarray(q)*duration)
    if np.min(t) < -2e-13 or np.max(np.abs(t.sum(axis=1)-1)) > 2e-11:
        raise ArithmeticError("transition failed stochasticity check; no clipping")
    return t


def forecast(q, initial, horizons, positions, thresholds):
    """Four exhaustive categories per horizon/threshold, including recovery.

    Lower/upper are *current refractory occupancy*, never first-hit probability.
    Constant Q means the specified future input is held constant, not that a
    previously read observation is necessarily injected again by the task.
    """
    p = np.asarray(initial, dtype=float)
    n = len(positions)
    if p.shape != (n+2,) or np.any(p < 0) or not np.isfinite(p).all() or abs(p.sum()-1) > 2e-12:
        raise ValueError("initial distribution required")
    rows = []
    for horizon in horizons:
        future = p @ transition(q, horizon)
        for threshold in thresholds:
            below = float(future[:n][positions <= threshold].sum())
            above = float(future[:n][positions > threshold].sum())
            rows.append(dict(horizon=horizon, threshold=threshold, distribution=future.tolist(),
                             active_below_equal=below, active_above=above,
                             lower_refractory=float(future[n]), upper_refractory=float(future[n+1])))
    return rows


def first_hit(q, initial_active, duration):
    """Survival and signed first-hit CDF; initial distribution must be active."""
    n = len(initial_active)
    if (np.shape(q) != (n+2, n+2) or not np.isfinite(initial_active).all()
            or np.any(np.asarray(initial_active) < 0) or abs(sum(initial_active)-1) > 2e-12):
        raise ValueError("normalized active initial law required")
    killed = np.zeros_like(q)
    killed[:n] = q[:n]
    out = np.r_[initial_active, 0., 0.] @ transition(killed, duration)
    return dict(survival=float(out[:n].sum()), lower=float(out[n]), upper=float(out[n+1]))


def expected_events(q, initial, duration):
    """Expected signed event *counts* including renewals, using Markov reward."""
    n = len(q)-2
    if (not math.isfinite(duration) or duration < 0 or np.shape(initial) != (n+2,)
            or not np.isfinite(initial).all() or np.any(np.asarray(initial) < 0)
            or abs(sum(initial)-1) > 2e-12):
        raise ValueError("valid duration and initial distribution required")
    augmented = np.zeros((n+4, n+4))
    augmented[:n+2, :n+2] = q
    augmented[:n, n+2:] = q[:n, n:]
    return np.asarray(initial) @ expm(augmented*duration)[:n+2, n+2:]


def fingerprint(payload):
    """FNV64 replay corruption checksum; not a cryptographic/authenticity claim."""
    value = 14695981039346656037
    for byte in payload:
        value = ((value ^ byte)*1099511628211) & MASK64
    return value


def export_native(path, q):
    q = validate_generator(q, len(q)-2)
    bits = [struct.unpack("<Q", struct.pack("<d", v))[0] for v in q.flat]
    text = f"HCNR1 {len(q)} {len(q)-2}\n" + " ".join(f"{v:016x}" for v in bits) + "\n"
    with Path(path).open("xb") as stream:
        stream.write(text.encode())
    return f"{fingerprint(text.encode()):016x}"


@dataclass
class Sampler:
    """Gillespie path with pending jump retained across observation cuts."""
    q: np.ndarray
    state: int
    rng: int
    time: float = 0.
    pending: tuple | None = None
    events: list = field(default_factory=list)
    jumps: int = 0

    def __post_init__(self):
        self.q = validate_generator(self.q, len(self.q)-2).copy()
        if not 0 <= self.state < len(self.q) or not 0 < self.rng <= MASK64:
            raise ValueError("invalid state/seed")

    def uniform(self):
        x = self.rng
        x ^= x >> 12
        x ^= (x << 25) & MASK64
        x ^= x >> 27
        self.rng = x & MASK64
        word = (self.rng*2685821657736338717) & MASK64
        return ((word >> 12)+.5)/(1 << 52)

    def advance(self, until):
        if not math.isfinite(until) or until < self.time:
            raise ValueError("time must be finite and monotone")
        start_events = len(self.events)
        while True:
            if self.pending is None:
                rate = -self.q[self.state, self.state]
                at = self.time-math.log(self.uniform())/rate
                u, cumulative = self.uniform()*rate, 0.
                target = None
                for j in range(len(self.q)):
                    if j != self.state:
                        cumulative += self.q[self.state, j]
                        if u < cumulative:
                            target = j
                            break
                if target is None or not math.isfinite(at) or at <= self.time:
                    raise ArithmeticError("invalid Gillespie draw")
                self.pending = (at, target)
            at, target = self.pending
            if at > until:
                self.time = until
                return self.events[start_events:]
            old = self.state
            self.time, self.state, self.pending = at, target, None
            self.jumps += 1
            if self.jumps > 10000000:
                raise RuntimeError("bounded jump budget exhausted")
            if old < len(self.q)-2 and target >= len(self.q)-2:
                self.events.append((at, -1 if target == len(self.q)-2 else 1))

    def change_generator(self, q):
        """An external context change invalidates the old conditional hazard.

        Exponential memorylessness permits a fresh draw at current time. This
        changes path coupling across *different input schedules*, not the law.
        Calling this on unchanged Q preserves pending draws and path identity.
        """
        q = validate_generator(q, len(self.q)-2)
        if not np.array_equal(q, self.q):
            self.q, self.pending = q.copy(), None
