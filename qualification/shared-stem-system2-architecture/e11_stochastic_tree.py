"""Finite, exactly represented *stochastic* coupled two-sided tree (DENY_ALL).

Registered discrete binary martingale, NOT continuous-time neural FBSDE:
    X_(k+1) = X_k + a*h*Y_k + sigma*m_(k+1)
    (1+lambda*h) Y_k = E[Y_(k+1) | public prefix] + beta*h*X_k
    Y_T = g*X_T,  m in {-s,+s} with conditional probability 1/2.

The affine decoupling field is a CHEAP exact control for this linear law.
Tree validation rechecks every prefix, both successor signs, conditional
covariance, Z*Sigma=B, orthogonal martingale residual and all terminal leaves.
Neither file origin nor semantic task quality is authenticated by this code.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
import re

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")


def number(text: str) -> F:
    if type(text) is not str or len(text) > 50 or not _NUMBER.fullmatch(text):
        raise ValueError("exact canonical rational string required")
    value = F(text)
    if str(value) != text or max(value.numerator.bit_length(), value.denominator.bit_length()) > 80:
        raise ValueError("noncanonical or excessive rational")
    return value


@dataclass(frozen=True)
class Law:
    steps: int = 3
    horizon: str = "3/4"
    a: str = "1/3"
    beta: str = "1/4"
    lam: str = "1/5"
    sigma: str = "1/2"
    driver_scale: str = "2"
    terminal_gain: str = "1/2"
    x0: str = "1"

    def checked(self) -> dict:
        if type(self.steps) is not int or not 1 <= self.steps <= 4:
            raise ValueError("finite registered tree depth 1..4 required")
        parsed = {field: number(getattr(self, field)) for field in (
            "horizon", "a", "beta", "lam", "sigma", "driver_scale",
            "terminal_gain", "x0",
        )}
        if not (0 < parsed["horizon"] <= 2
                and 0 <= parsed["a"] <= 2
                and 0 <= parsed["beta"] <= 2
                and 0 <= parsed["lam"] <= 2
                and 0 < parsed["sigma"] <= 2
                and 0 < parsed["driver_scale"] <= 2
                and 0 <= parsed["terminal_gain"] <= 2
                and -2 <= parsed["x0"] <= 2):
            raise ValueError("law outside bounded registered operating region")
        parsed["h"] = parsed["horizon"] / self.steps
        return parsed


def gains(law: Law) -> tuple[F, ...]:
    """Short-horizon decoupling: positive denominators only, full interval."""
    if type(law) is not Law:
        raise ValueError("registered Law type required")
    p = law.checked()
    result = [F(0)] * (law.steps + 1)
    result[-1] = p["terminal_gain"]
    for k in range(law.steps - 1, -1, -1):
        d = 1 + p["lam"] * p["h"] - p["a"] * p["h"] * result[k + 1]
        if d <= 0:
            raise ValueError("nonregular or singular full-horizon decoupling")
        result[k] = (result[k + 1] + p["beta"] * p["h"]) / d
        if max(result[k].numerator.bit_length(), result[k].denominator.bit_length()) > 160:
            raise ValueError("unbounded gain; no numeric admission")
    return tuple(result)


@dataclass(frozen=True)
class State:
    x: str
    y: str


@dataclass(frozen=True)
class Trace:
    states: tuple[State, ...]
    z: tuple[str, ...]


@dataclass(frozen=True)
class Certificate:
    globally_consistent_registered_law: bool
    forward: str
    backward: str
    terminal: str
    initial: str
    decoupling: str
    covariance: str
    martingale: str
    checked_internal_nodes: int
    checked_leaves: int
    reason: str
    authority: str = "DENY_ALL"
    continuous_fbsde_qualified: bool = False
    independent_future_task_utility: bool = False


def cheap_root(law: Law) -> F:
    """Root recursive utility via O(depth) affine recursion, no tree enumeration."""
    g = gains(law)
    return g[0] * number(law.x0)


def affine_trace(law: Law) -> Trace:
    """Cheap complete-tree control. Every node uses only its PUBLIC prefix."""
    p = law.checked()
    g = gains(law)
    nonleaves = 2**law.steps - 1
    total = 2 * nonleaves + 1
    xx = [F(0)] * total
    yy = [F(0)] * total
    zz = [F(0)] * nonleaves
    xx[0] = p["x0"]
    for i in range(nonleaves):
        depth = (i + 1).bit_length() - 1
        yy[i] = g[depth] * xx[i]
        zz[i] = g[depth + 1] * p["sigma"]
        mid = xx[i] + p["a"] * p["h"] * yy[i]
        noise = p["sigma"] * p["driver_scale"]
        xx[2*i+1] = mid-noise
        xx[2*i+2] = mid+noise
    for i in range(nonleaves, total):
        yy[i] = g[-1] * xx[i]
    return Trace(tuple(State(str(x), str(y)) for x, y in zip(xx, yy)),
                 tuple(map(str, zz)))


def certify(law: Law, trace: Trace) -> Certificate:
    """Independent whole-tree *contract* check; no untrusted passed flag used.

    A trace carries exactly one X,Y,Z for each public information prefix.
    This enforces syntactic adaptedness (no per-future-outcome Y at same
    prefix), NOT actual absence of future-information leakage in data.
    """
    p = law.checked()
    g = gains(law)
    nonleaves = 2**law.steps - 1
    total = 2 * nonleaves + 1
    if type(trace) is not Trace or type(trace.states) is not tuple or type(trace.z) is not tuple:
        raise ValueError("complete typed, immutable trace required")
    if len(trace.states) != total or len(trace.z) != nonleaves:
        raise ValueError("entire public-prefix tree must be present")
    if any(type(s) is not State for s in trace.states):
        raise ValueError("typed X/Y state required")
    x = [number(s.x) for s in trace.states]
    y = [number(s.y) for s in trace.states]
    z = [number(value) for value in trace.z]
    residual = dict(forward=F(0), backward=F(0), terminal=F(0),
                    initial=abs(x[0]-p["x0"]), decoupling=F(0),
                    covariance=F(0), martingale=F(0))
    h = p["h"]
    noise = p["driver_scale"]
    for i in range(total):
        depth = (i + 1).bit_length() - 1
        residual["decoupling"] = max(residual["decoupling"], abs(y[i] - g[depth]*x[i]))
    for i in range(nonleaves):
        left = 2*i+1
        right = left+1
        mid = x[i] + p["a"]*h*y[i]
        residual["forward"] = max(residual["forward"],
                                  abs(x[left] - mid + p["sigma"]*noise),
                                  abs(x[right] - mid - p["sigma"]*noise))
        expected_y = (y[left]+y[right])/2
        residual["backward"] = max(residual["backward"],
                                   abs((1+p["lam"]*h)*y[i] - expected_y - p["beta"]*h*x[i]))
        centered_left = y[left] - expected_y
        centered_right = y[right] - expected_y
        sigma = noise*noise
        b = (centered_right-centered_left)*noise/2
        residual["covariance"] = max(residual["covariance"], abs(z[i]*sigma-b))
        residual["martingale"] = max(residual["martingale"],
                                     abs(centered_left+z[i]*noise),
                                     abs(centered_right-z[i]*noise))
    for i in range(nonleaves, total):
        residual["terminal"] = max(residual["terminal"], abs(y[i]-p["terminal_gain"]*x[i]))
    ok = not any(residual.values())
    reason = "exact_finite_stochastic_tree_only" if ok else next(
        name+"_residual" for name in (
            "initial", "forward", "backward", "terminal", "covariance", "martingale", "decoupling",
        ) if residual[name] != 0
    )
    return Certificate(ok, *(str(residual[name]) for name in (
        "forward", "backward", "terminal", "initial", "decoupling", "covariance", "martingale",
    )), nonleaves, total-nonleaves, reason)


def incomplete_martingale_counterexample() -> dict:
    """Full-rank scalar covariance does NOT imply martingale completeness.

    Three equiprobable outcomes m=(-1,0,+1), utility=(1,0,1):
    Z=0 via Z*Sigma=B, but centered utility residual is nonzero.
    """
    p = (F(1, 3),) * 3
    driver = (-F(1), F(0), F(1))
    utilities = (F(1), F(0), F(1))
    mean_m = sum((a*b for a, b in zip(p, driver)), F(0))
    mean_y = sum((a*b for a, b in zip(p, utilities)), F(0))
    covariance = sum((a*(m-mean_m)**2 for a, m in zip(p, driver)), F(0))
    cross = sum((a*(y-mean_y)*(m-mean_m) for a, y, m in zip(p, utilities, driver)), F(0))
    z = cross/covariance
    orth = tuple(y-mean_y-z*(m-mean_m) for y, m in zip(utilities, driver))
    return {"covariance": str(covariance), "z": str(z),
            "z_sigma_equals_b": z*covariance == cross,
            "orthogonal_residual": tuple(map(str, orth)),
            "martingale_complete": all(v == 0 for v in orth),
            "stochastic_fbsde_global_qualified": False, "authority": "DENY_ALL"}
