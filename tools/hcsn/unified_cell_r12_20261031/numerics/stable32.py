"""A pure-FP32 candidate for full HX; R11 remains the unchanged control.

Near the stopping boundary, evaluate the *same* second-order equity ODE
with its zero value/slope data using a fixed Gauss integral. This avoids
subtracting the O(100) A7 terms to produce O(x**2) equity. This is a
numerical quadrature candidate, not a new closed form or an admission claim.
"""

import importlib.util
from pathlib import Path

import numpy as np

UPSTREAM = Path(__file__).resolve().parents[2] / "calibrated_operator_r11_20261031" / "numerics"
spec = importlib.util.spec_from_file_location("r11_hx_kernel", UPSTREAM / "kernel.py")
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)
NODES, WEIGHTS = np.polynomial.legendre.leggauss(24)
NODES, WEIGHTS = (NODES + 1) / 2, WEIGHTS / 2


def pairwise(terms):
    """FP32 stays FP32 for both values and tangents during reduction."""
    dtype = terms[0].g.dtype
    return k.Dual(np.sum(np.asarray([t.v for t in terms], dtype=dtype), dtype=dtype),
                  np.sum(np.stack([t.g for t in terms], axis=-1), axis=-1, dtype=dtype))


class StableHX(k.FullHX):
    """Inherited full financial boundary and payoffs; two evaluations replaced."""

    def B(self, y):
        d = self.z + y
        # The derivative integral is the exact divided-difference identity.
        # The fixed quadrature has an error, which is measured, not waived.
        if abs(d.v) <= .25 * (1 + self.z.v) or self.s.v < .1:
            terms = []
            for node, weight in zip(NODES, WEIGHTS):
                at = -self.z + node * d
                exponent = .5 * (self.z - at) * (self.z + at) * self.s * self.s
                terms.append(weight * (self.s * k.exp_phi(0., at * self.s)
                                       + at * self.s * self.s * k.exp_cdf(exponent, -self.z * self.s)))
            return pairwise(terms)
        return super().B(y)

    def increments(self, x):
        """Compute survival and G-1 without subtracting two near-unit values."""
        lo, hi = self.a * self.s - x / self.s, self.a * self.s + x / self.s
        survival = k.cdf_interval(x.coerce(0.), lo, hi)
        survival -= k.expm1(-2 * self.a * x) * k.Phi(lo)
        u, v = -self.a + self.zt, -self.a - self.zt
        gm1 = k.expm1(u * x) * k.Phi(-x / self.s - self.zt * self.s)
        gm1 += k.expm1(v * x) * k.Phi(-x / self.s + self.zt * self.s)
        for sign in (-1, 1):
            hi = sign * self.zt * self.s
            gm1 -= k.cdf_interval(x.coerce(0.), hi - x / self.s, hi)
        return survival, gm1

    def local_equity(self, x):
        """Green integral for .5*s2*E'' + a*s2*E' - r*E = -flow."""
        flow0 = (self.delta * self.b - (1 - self.theta[4]) * self.theta[7]
                 + (self.alpha * self.b - self.theta[8]) / self.m)
        cuts = [x.coerce(0.)]
        if x.v > 8 * self.s.v:
            cuts.append(8 * self.s)
        cuts.append(x)
        pieces = []
        for left, right in zip(cuts[:-1], cuts[1:]):
            terms = []
            for node, weight in zip(NODES, WEIGHTS):
                y = left + node * (right - left)
                gap = x - y
                survival, gm1 = self.increments(y)
                flow = flow0 + self.delta * self.b * k.expm1(y)
                flow += self.discount * self.q * survival + (self.alpha * self.b / self.m - self.c / self.R) * gm1
                green = -k.exp(self.eta * gap) * k.expm1(-2 * self.z * gap)
                terms.append(-weight * green * flow)
            pieces.append((right - left) * pairwise(terms))
        return pairwise(pieces) / (self.z * self.s2)

    def equity(self, x):
        # Keep the exponentially growing IVP solution in a bounded interval.
        # Beyond it the inherited A7 remains, including its recorded failures.
        limits = [x.coerce(.5), 1 / self.eta]
        limit = min(limits, key=lambda y: y.v)
        if x.v <= .8 * limit.v:
            return self.local_equity(x)
        if x.v >= limit.v:
            return self.raw_equity(x)
        t = (x / limit - .8) / .2
        weight = t ** 3 * (10 + t * (-15 + 6 * t))
        return (1 - weight) * self.local_equity(x) + weight * self.raw_equity(x)


def evaluate(theta, state, *, coordinate="log_distance", mode="float32", jacobian=True,
             diagnostic_outside_box=False, candidate=True):
    """No hidden FP64 kernel; mixed32 is explicitly separate.

    diagnostic_outside_box bypasses only the rectangular input-box guard for
    recorded experiments. It never indicates deployment/training admission.
    """
    if mode not in ("float32", "float64", "mixed32") or coordinate not in ("asset", "log_distance"):
        raise ValueError("Unknown mode/coordinate")
    inp = np.float64 if mode == "float64" else np.float32
    internal = np.float32 if mode == "float32" else np.float64
    values, state = np.asarray(theta, dtype=inp), inp(state)
    if values.shape != (9,) or not np.all(np.isfinite(values)) or not np.isfinite(state):
        raise ValueError("Expected finite inputs")
    if not diagnostic_outside_box and (np.any(values < k.LOWER.astype(inp)) or np.any(values > k.UPPER.astype(inp))):
        raise ValueError("Outside the unchanged R11 admitted parameter box")
    if values[2] <= 0 or values[6] <= 0 or values[0] + values[5] <= 0 or state < 0:
        raise ValueError("Invalid physical coordinate")
    basis = np.eye(10, dtype=internal) if jacobian else np.empty((10, 0), dtype=internal)
    p = [k.Dual(v, basis[i]) for i, v in enumerate(values)]
    arg = k.Dual(state, basis[-1])
    model = (StableHX if candidate else k.FullHX)(p)
    x = k.log(arg / model.b) if coordinate == "asset" else arg
    if x.v <= 0 and coordinate == "asset":
        e, f, g = x.coerce(0.), x.coerce(1.), x.coerce(1.)
        debt = model.alpha * model.b / model.m
    else:
        e, (f, g) = model.equity(x), model.first_hit(x, model.m)
        if candidate and x.v < .25:
            survival, gm1 = model.increments(x)
            debt = model.alpha * model.b / model.m + model.discount * model.q * survival
            debt += (model.alpha * model.b / model.m - model.c / model.R) * gm1
        else:
            debt = model.c / model.R + model.discount * model.q * (1 - f)
            debt += (model.alpha * model.b / model.m - model.c / model.R) * g
    result = [model.b, e, f, g, debt]
    out = np.float32 if mode == "mixed32" else internal
    return np.asarray([v.v for v in result], dtype=out), np.asarray([v.g for v in result], dtype=out)
