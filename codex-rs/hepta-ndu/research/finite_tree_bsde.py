"""Research-only scalar binomial-martingale FBSDE; no production owner/API.

A finite discretization, not a continuous-time existence/uniqueness certificate.
At a chance node use conditional expectation, never the best noise realization.
The exact same terminal critic and frozen action sequence define every interval.
NDU deterministic profile: U[k] = instant[k] + discount[k] * U[k+1].
The stochastic profile uses f=-cost-rho*Y-eta*Z**2/2 and DeltaM=+/-sqrt(dt).
Noise amplitude is an explicit experimental model assumption, not calibrated
real-world uncertainty. A residual certifies only this finite supplied model.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

import torch


@dataclass(frozen=True)
class Profile:
    horizon: float = 0.3
    sigma: float = 0.05
    coupling: float = 0.05
    rho: float = 0.1
    risk: float = 0.1
    cost: float = 0.02
    iterations: int = 24
    tolerance: float = 1e-5
    damping: float = 0.75

    def validate(self) -> None:
        numbers = (self.horizon, self.sigma, self.coupling, self.rho,
                   self.risk, self.cost, self.tolerance, self.damping)
        if not all(math.isfinite(x) for x in numbers):
            raise ValueError("nonfinite numerical profile")
        if not (0 < self.horizon <= 1 and 0 <= self.sigma <= 1
                and 0 <= self.coupling <= 1 and 0 <= self.rho <= 1
                and 0 <= self.risk <= 1 and 0 <= self.cost <= 1
                and 0 < self.tolerance <= 0.01 and 0 < self.damping <= 1
                and type(self.iterations) is int and 1 <= self.iterations <= 64):
            raise ValueError("unregistered bounded numerical profile")


def recursive_utility(instant: list[float], discount: list[float], terminal: float) -> list[float]:
    """Unprojected real-valued reference to the native recursive.rs profile.

    This does NOT claim signed-Q32 parity or authenticate an outcome observer.
    """
    if (not 1 <= len(instant) == len(discount) <= 512
            or any(not math.isfinite(x) for x in (*instant, *discount, terminal))
            or any(not 0 <= x <= 1 for x in discount)):
        raise ValueError("invalid recursive path")
    values = [0.0] * len(instant) + [float(terminal)]
    for k in range(len(instant) - 1, -1, -1):
        values[k] = instant[k] + discount[k] * values[k + 1]
    return values


def conditional_z(increments: torch.Tensor, future: torch.Tensor,
                  weights: torch.Tensor) -> tuple[torch.Tensor, float]:
    """Centered Z Sigma=B, not B/dt for arbitrary increment covariance.

    Observations are conditional samples at ONE node. Pooled trajectory
    regression is not substituted for conditional identification.
    """
    m, y, p = increments.double(), future.double(), weights.double()
    if (m.ndim != 2 or y.shape != (len(m),) or p.shape != y.shape
            or len(m) < 2 or not 1 <= m.shape[1] <= 8
            or not all(torch.isfinite(x).all() for x in (m, y, p))
            or (p <= 0).any() or abs(float(p.sum()) - 1) > 1e-10):
        raise ValueError("invalid conditional scenario law")
    mc = m - (p[:, None] * m).sum(0)
    yc = y - (p * y).sum()
    cov = mc.T @ (p[:, None] * mc)
    eigen = torch.linalg.eigvalsh(cov)
    if float(eigen.min()) <= 1e-12 or float(eigen.max() / eigen.min()) > 1e6:
        raise ValueError("unsupported singular/ill-conditioned covariance")
    cross = (p[:, None] * mc * yc[:, None]).sum(0)
    z = torch.linalg.solve(cov, cross)
    return z, float(torch.max(torch.abs(cov @ z - cross)))


@dataclass(frozen=True)
class Solve:
    value: float
    iterations: int
    nodes: int
    forward_residual: float
    backward_residual: float
    terminal_residual: float
    iteration_delta: float
    converged: bool
    wrong_boundary_control: bool
    z_max: float


def _backward(children: list[float], dt: float, p: Profile) -> tuple[float, float]:
    mean = sum(children) / 2
    # The two declared equiprobable +/-sqrt(dt) innovations span this node.
    z = (children[1] - children[0]) / (2 * math.sqrt(dt))
    value = (mean - p.cost * dt - 0.5 * p.risk * z * z * dt) / (1 + p.rho * dt)
    return value, z


@torch.no_grad()
def solve_path(actions: torch.Tensor, initial: torch.Tensor,
               transition: Callable[[torch.Tensor, torch.Tensor], torch.Tensor],
               terminal: Callable[[torch.Tensor], torch.Tensor],
               profile: Profile, charge: Callable[[str, int], None], *,
               wrong_boundary: bool = False) -> Solve:
    """Forward states / backward values on one action path's chance tree.

    Each Picard sweep reuses the declared conditional scenario law. The wrong
    control replaces each interior continuation by a fresh local terminal
    estimate. It is allowed as a negative experiment, NEVER as a valid solution.
    Work is charged before callbacks; budget failures propagate to the census.
    """
    profile.validate()
    if (actions.ndim != 2 or not 1 <= len(actions) <= 4
            or initial.ndim != 1 or actions.shape[1] != initial.numel()
            or not torch.isfinite(actions).all() or not torch.isfinite(initial).all()):
        raise ValueError("bounded finite action path required")
    depth, dt = len(actions), profile.horizon / len(actions)
    total, first_leaf = 2 ** (depth + 1) - 1, 2 ** depth - 1
    direction = torch.ones_like(initial) / math.sqrt(initial.numel())
    old = [0.0] * total
    last_delta = float("inf")

    def predict(h: torch.Tensor) -> float:
        charge("critic", 1)
        value = float(terminal(h))
        if not math.isfinite(value):
            raise ValueError("nonfinite terminal continuation")
        return value

    def forward(values: list[float]) -> list[torch.Tensor]:
        states = [initial.clone()]
        for n in range(first_leaf):
            k = (n + 1).bit_length() - 1
            charge("transition", 1)
            drift = transition(states[n], actions[k]) - states[n]
            for sign in (-1, 1):
                h = (states[n] + dt * drift + profile.coupling * values[n] * dt * direction
                     + profile.sigma * sign * math.sqrt(dt) * direction)
                if not torch.isfinite(h).all():
                    raise ValueError("nonfinite forward state")
                states.append(h)
        return states

    def backward(states: list[torch.Tensor], broken: bool) -> tuple[list[float], float]:
        values, zmax = [0.0] * total, 0.0
        for n in range(first_leaf, total):
            values[n] = predict(states[n])
        for n in range(first_leaf - 1, -1, -1):
            children = [2 * n + 1, 2 * n + 2]
            future = ([predict(states[c]) for c in children]
                      if broken and children[0] < first_leaf else [values[c] for c in children])
            charge("backward", 1)
            values[n], z = _backward(future, dt, profile)
            zmax = max(zmax, abs(z))
        if not all(math.isfinite(x) for x in values):
            raise ValueError("nonfinite backward value")
        return values, zmax

    for iteration in range(1, profile.iterations + 1):
        states = forward(old)
        proposed, _ = backward(states, wrong_boundary)
        if profile.coupling == 0:
            # Forward states are independent of backward values: exact finite
            # backward induction, no iterative convergence claim is needed.
            old, last_delta = proposed, 0.0
            break
        last_delta = max(abs(a - b) for a, b in zip(old, proposed))
        old = [(1 - profile.damping) * a + profile.damping * b
               for a, b in zip(old, proposed)]
        if last_delta <= profile.tolerance:
            break
    # A separate final forward pass ensures the residual uses the values returned.
    states = forward(old)
    correct, zmax = backward(states, False)
    backward_error = max(abs(old[n] - _backward([old[2*n+1], old[2*n+2]], dt, profile)[0])
                         for n in range(first_leaf))
    terminal_error = max(abs(old[n] - correct[n]) for n in range(first_leaf, total))
    # Check the actually stored states, not a terminal-only equality.
    fwd = 0.0
    for n in range(first_leaf):
        k = (n + 1).bit_length() - 1
        charge("transition", 1)
        drift = transition(states[n], actions[k]) - states[n]
        for offset, sign in enumerate((-1, 1), 1):
            expected = (states[n] + dt * drift + profile.coupling * old[n] * dt * direction
                        + profile.sigma * sign * math.sqrt(dt) * direction)
            fwd = max(fwd, float(torch.max(torch.abs(states[2*n+offset] - expected))))
    converged = max(fwd, backward_error, terminal_error, last_delta) <= profile.tolerance
    return Solve(old[0], iteration, total, fwd, backward_error, terminal_error,
                 last_delta, converged, wrong_boundary, zmax)
