"""Finite rectangular robust utility and two explicit entropic BSDE examples.

Utilities are maximized. Nature minimizes conditional utility independently at
each public history/action. This is not a general coupled FBSDE solver.
"""

from dataclasses import dataclass
import math
from types import MappingProxyType

import numpy as np


def _nonnegative_scalar(value, name):
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        raise ValueError(f"{name} must be a finite nonnegative scalar")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"invalid {name}") from error
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return result


def validate_probabilities(probabilities):
    """Copy a law, or rows of laws; reject rather than repair invalid inputs."""
    rows = np.asarray(probabilities, dtype=np.float64)
    if rows.ndim not in (1, 2) or rows.shape[-1] == 0 or rows.size == 0:
        raise ValueError("one nonempty probability law or a matrix of laws required")
    if not np.isfinite(rows).all() or np.any(rows < 0):
        raise ValueError("probabilities must be finite and nonnegative")
    totals = rows.astype(np.longdouble).sum(axis=-1)
    if np.any(np.abs(totals - 1) > np.longdouble("1e-12")):
        raise ValueError("each probability law must sum to one")
    result = rows.copy()
    result.flags.writeable = False
    return result


def entropic_ce(values, probabilities, gamma):
    """Return -log E[exp(-gamma*utility)]/gamma over the last value axis.

Zero-mass outcomes are excluded; gamma=0 is expectation. Extended-precision
intermediates avoid overflow of gamma*value and cancellation between a large
anchor and its correction for finite float64 inputs. Results are float64.
"""
    gamma = _nonnegative_scalar(gamma, "gamma")
    p = validate_probabilities(probabilities)
    values = np.asarray(values, dtype=np.float64)
    if p.ndim != 1 or values.ndim == 0 or values.shape[-1] != p.size:
        raise ValueError("values' final axis must match one probability law")
    if not np.isfinite(values).all():
        raise ValueError("utilities must be finite")
    support = p > 0
    p = p[support].astype(np.longdouble)
    p = p / p.sum()
    x = values[..., support].astype(np.longdouble)
    mean = (x * p).sum(axis=-1)
    if gamma == 0:
        result = mean
    else:
        eta = np.longdouble(gamma)
        centered = -eta * (x - mean[..., None])
        if np.all(np.abs(centered) < np.longdouble("1e-3")):
            result = mean - np.log1p((p * np.expm1(centered)).sum(axis=-1)) / eta
        else:
            anchor = x.min(axis=-1, keepdims=True)
            with np.errstate(under="ignore"):
                mass = (p * np.exp(-eta * (x - anchor))).sum(axis=-1)
            result = anchor[..., 0] - np.log(mass) / eta
    result = np.asarray(result, dtype=np.float64)
    if not np.isfinite(result).all():
        raise ArithmeticError("certainty equivalent is not representable as float64")
    return float(result) if result.ndim == 0 else result


def robust_ce(values, probability_rows, gamma, return_worst=False):
    """Minimize entropic utility over finite laws, equivalently their convex hull.

Values may have leading batch axes. First-row ties are deterministic. These
rows describe ambiguity, not a posterior probability over regimes.
"""
    rows = validate_probabilities(probability_rows)
    if rows.ndim != 2:
        raise ValueError("ambiguity rows must have shape [models, outcomes]")
    candidates = np.stack([entropic_ce(values, row, gamma) for row in rows])
    worst = np.argmin(candidates, axis=0)
    value = np.min(candidates, axis=0)
    if value.ndim == 0:
        value, worst = float(value), int(worst)
    return (value, worst) if return_worst else value


def conditional_rows(joint_models, evidence, target_axis, return_models=False):
    """Condition frozen full joint laws on public evidence, then marginalize.

The first axis indexes regimes. Evidence has one int/None per probability
axis. The target must remain unobserved. Regimes assigning zero probability
to this history are removed explicitly; all-zero support is an error.
    """
    models = np.asarray(joint_models, dtype=np.float64)
    if models.ndim < 2 or models.shape[0] == 0 or any(n == 0 for n in models.shape):
        raise ValueError("nonempty [models, probability axes...] array required")
    if not np.isfinite(models).all() or np.any(models < 0):
        raise ValueError("joint probabilities must be finite and nonnegative")
    totals = models.astype(np.longdouble).sum(axis=tuple(range(1, models.ndim)))
    if np.any(np.abs(totals - 1) > np.longdouble("1e-12")):
        raise ValueError("each joint model must be normalized")
    if (not isinstance(evidence, (tuple, list)) or len(evidence) != models.ndim - 1
            or type(target_axis) is not int or not 0 <= target_axis < len(evidence)
            or evidence[target_axis] is not None):
        raise ValueError("invalid evidence or observed target axis")
    for axis, value in enumerate(evidence):
        if value is not None and (type(value) is not int or not 0 <= value < models.shape[axis + 1]):
            raise ValueError("evidence entries must be valid indices or None")
    selected = models[(slice(None),) + tuple(slice(None) if x is None else x for x in evidence)]
    remaining = [i for i, x in enumerate(evidence) if x is None]
    target = 1 + remaining.index(target_axis)
    marginal = selected.astype(np.longdouble).sum(
        axis=tuple(i for i in range(1, selected.ndim) if i != target))
    masses = marginal.sum(axis=1)
    active = np.flatnonzero(masses > 0)
    if active.size == 0:
        raise ValueError("history is impossible under every declared model")
    rows = np.asarray(marginal[active] / masses[active, None], dtype=np.float64)
    rows = validate_probabilities(rows)
    indices = tuple(int(i) for i in active)
    return (rows, indices) if return_models else rows


@dataclass(frozen=True)
class Transition:
    name: str
    next_states: tuple
    probability_rows: object
    rewards: object = 0.0

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or not isinstance(self.next_states, tuple):
            raise ValueError("an action needs a name and tuple of next states")
        rows = validate_probabilities(self.probability_rows)
        if rows.ndim != 2 or rows.shape[1] != len(self.next_states):
            raise ValueError("one outcome per next state required")
        rewards = np.asarray(self.rewards, dtype=np.float64)
        if rewards.ndim == 0:
            rewards = np.full(len(self.next_states), float(rewards))
        if rewards.shape != (len(self.next_states),) or not np.isfinite(rewards).all():
            raise ValueError("finite scalar or per-outcome rewards required")
        rewards = rewards.copy()
        rewards.flags.writeable = False
        object.__setattr__(self, "probability_rows", rows)
        object.__setattr__(self, "rewards", rewards)


@dataclass(frozen=True)
class BellmanSolution:
    values: object
    policy: object
    worst_rows: object


def rectangular_bellman(layers, actions, terminal, gamma):
    """Exact finite backward induction for a history/state-action rectangle.

layers[t] lists public states; actions[(t,state)] is an ordered iterable of
Transition objects. terminal maps final-layer states to utilities. Budget and
observable preferences must be included in state by the caller. Each edge
advances one layer; there is no implicit terminal fallback or hidden state.
    """
    gamma = _nonnegative_scalar(gamma, "gamma")
    if len(layers) < 2 or any(not layer for layer in layers):
        raise ValueError("a positive finite horizon with nonempty layers is required")
    sets = [set(layer) for layer in layers]
    if any(len(states) != len(layer) for states, layer in zip(sets, layers)):
        raise ValueError("duplicate state within a layer")
    if set(terminal) != sets[-1]:
        raise ValueError("terminal utilities must cover exactly the final layer")
    final = len(layers) - 1
    values, policy, worst_rows = {}, {}, {}
    for state, value in terminal.items():
        if not np.isfinite(value):
            raise ValueError("finite terminal utilities required")
        values[(final, state)] = float(value)
    for time in range(final - 1, -1, -1):
        for state in layers[time]:
            available = tuple(actions.get((time, state), ()))
            if not available or len({a.name for a in available}) != len(available):
                raise ValueError("each nonterminal state needs uniquely named feasible actions")
            best = None
            for action in available:
                if not isinstance(action, Transition) or any(s not in sets[time + 1] for s in action.next_states):
                    raise ValueError("every transition must advance to the next public layer")
                outcomes = np.asarray([values[(time + 1, s)] for s in action.next_states]) + action.rewards
                value, worst = robust_ce(outcomes, action.probability_rows, gamma, return_worst=True)
                if best is None or value > best[0]:
                    best = value, action.name, worst
            values[(time, state)], policy[(time, state)], worst_rows[(time, state)] = best
    return BellmanSolution(MappingProxyType(values), MappingProxyType(policy), MappingProxyType(worst_rows))


def gaussian_entropic_bsde(time, brownian, terminal_time=1.0, mu=0.0, sigma=1.0, gamma=1.0):
    """Analytic U,Z only for X_T=mu+sigma*W_T and f(z)=-gamma*z^2/2.

dU=+gamma*Z^2/2 dt+Z dW; U_T=X_T. Z is the martingale exposure,
not dU/dsigma, dU/dgamma, or a neural parameter gradient.
    """
    gamma = _nonnegative_scalar(gamma, "gamma")
    terminal_time = _nonnegative_scalar(terminal_time, "terminal_time")
    t, w = np.broadcast_arrays(np.asarray(time, dtype=float), np.asarray(brownian, dtype=float))
    if (not np.isfinite(t).all() or not np.isfinite(w).all() or np.any(t < 0)
            or np.any(t > terminal_time) or not np.isfinite(mu) or not np.isfinite(sigma)):
        raise ValueError("finite parameters and times within the horizon required")
    u = mu + sigma * w - .5 * gamma * sigma ** 2 * (terminal_time - t)
    z = np.full(t.shape, sigma, dtype=float)
    if not np.isfinite(u).all():
        raise ArithmeticError("analytic value is outside float64 range")
    return (float(u), float(z)) if u.ndim == 0 else (u, z)


@dataclass(frozen=True)
class BinomialStep:
    utility: float
    z: float
    driver: float


def binomial_entropic_step(down_value, up_value, dt, gamma):
    """Exact equal-probability two-outcome backward stochastic difference step.

Delta W is +/-sqrt(dt). U_next=U-driver*dt+Z*Delta W exactly. The
driver tends to -gamma*Z^2/2 for bounded Z as dt tends to zero.
    """
    dt = _nonnegative_scalar(dt, "dt")
    if dt == 0:
        raise ValueError("dt must be positive")
    utility = entropic_ce([down_value, up_value], [.5, .5], gamma)
    down, up = np.longdouble(down_value), np.longdouble(up_value)
    z = float((up - down) / (2 * np.sqrt(np.longdouble(dt))))
    driver = float((np.longdouble(utility) - (down + up) / 2) / dt)
    if not math.isfinite(z) or not math.isfinite(driver):
        raise ArithmeticError("discrete decomposition is outside float64 range")
    return BinomialStep(utility, z, driver)
