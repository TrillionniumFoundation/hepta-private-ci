"""Explicit finite CTMC contract; its three-bin profile is not a diffusion.

The native counterpart is the pinned R9 `cell::Cell`, used by the real R10
owner. Both implement the generator defined below. Teacher matrix exponentials,
trainable features and native uniformization are numerical evaluations of that
same finite generator. A task FIRE resets at the interval END; spontaneous
cell events enter two Erlang recovery phases and may repeat within an interval.
"""
import math

import numpy as np
from scipy.linalg import expm, expm_frechet
from scipy.special import expit

SCHEMA = "hcsn.finite-regenerative-model.r11.v1"
DEFAULT_NODES = 3
PARAMETER_LIMIT = 3.


def _parameters(theta, driver, nodes):
    theta = np.asarray(theta, dtype=float)
    if (theta.shape != (6,) or not np.all(np.isfinite(theta))
            or np.any(np.abs(theta) > PARAMETER_LIMIT) or not math.isfinite(driver)
            or abs(driver) > 1 or type(nodes) is not int or not 3 <= nodes <= 128):
        raise ValueError("Finite-model parameter/driver/topology envelope")
    v = expit(theta)
    drift = .1+.8*float(expit(theta[0]+theta[1]*driver))
    return theta, v, drift, .25+.25*v[2], .8+.4*v[3], -.3+.2*v[4], .3+.5*v[5]


def generator(theta, driver, nodes=DEFAULT_NODES, direction=None):
    """Return augmented generator, reset law and their directional derivatives.

The final coordinate accumulates EXPECTED repeated events, not probability.
The preceding two coordinates are recovery phases. All rates are in seconds.
Derivative branches are fixed; interpolation knots with nonzero motion reject.
"""
    _, v, mu, sigma, boundary, reset, refractory = _parameters(theta, driver, nodes)
    d = np.zeros(6) if direction is None else np.asarray(direction, float)
    if d.shape != (6,) or not np.all(np.isfinite(d)):
        raise ValueError("Invalid directional derivative")
    slope = v*(1-v)*d
    z = float(expit(theta[0]+theta[1]*driver))
    dmu = .8*z*(1-z)*(d[0]+d[1]*driver)
    dsigma, db, dr, dtau = .25*slope[2], .4*slope[3], .2*slope[4], .5*slope[5]
    h, dh = (boundary+1)/nodes, db/nodes
    y, dy = (reset+1)/h-.5, dr/h-(reset+1)*dh/h**2
    left = int(math.floor(y))
    if not 0 <= left < nodes-1:
        raise ValueError("Reset interpolation is outside cell centers")
    if min(y-left, left+1-y) < 1e-10 and abs(dy) > 1e-12:
        raise ValueError("Directional derivative at reset interpolation knot")
    origin, dorigin = np.zeros(nodes+2), np.zeros(nodes+2)
    origin[left:left+2], dorigin[left:left+2] = [left+1-y, y-left], [-dy, dy]
    diffusion = sigma*sigma/(2*h*h)
    ddiffusion = sigma*dsigma/h**2-2*diffusion*dh/h
    up, dup = diffusion+mu/h, ddiffusion+dmu/h-mu*dh/h**2
    recovery, drecovery = 2/refractory, -2*dtau/refractory**2
    q, dq = np.zeros((nodes+3, nodes+3)), np.zeros((nodes+3, nodes+3))

    def edge(i, j, rate, derivative):
        q[i, j] += rate
        q[i, i] -= rate
        dq[i, j] += derivative
        dq[i, i] -= derivative

    for i in range(nodes):
        if i:
            edge(i, i-1, diffusion, ddiffusion)
        edge(i, nodes+1 if i == nodes-1 else i+1, up, dup)
    q[nodes-1, nodes+2], dq[nodes-1, nodes+2] = up, dup
    edge(nodes+1, nodes, recovery, drecovery)
    for i, weight in enumerate(origin[:nodes]):
        if weight or dorigin[i]:
            edge(nodes, i, recovery*weight, drecovery*weight+recovery*dorigin[i])
    return q, origin, dq, dorigin


def initial(theta, nodes=DEFAULT_NODES):
    return generator(np.asarray(theta)[:6], 0., nodes)[1]


def transition(theta, driver, duration, nodes=DEFAULT_NODES, direction=None,
               first_hit=False):
    """Finite transition and Frechet derivative including the event accumulator.

`first_hit` removes the upper jump to recovery but retains its positive flux
into the event accumulator. This avoids cancellation in 1 - survival.
"""
    if not math.isfinite(duration) or not 0 <= duration <= 128:
        raise ValueError("Duration envelope is 0..128 seconds")
    q, _, dq, _ = generator(np.asarray(theta)[:6], driver, nodes, direction)
    if first_hit:
        q[nodes-1, nodes+1] = 0.
        dq[nodes-1, nodes+1] = 0.
    if direction is None:
        return expm(q*duration)
    return expm_frechet(q*duration, dq*duration)


def physical_state(theta, history, nodes=DEFAULT_NODES, direction=None):
    """Replay complete causal history, retaining events across task resets."""
    _, origin, _, dorigin = generator(np.asarray(theta)[:6], 0., nodes, direction)
    p, dp = np.r_[origin, 0.], np.r_[dorigin, 0.]
    for event in history:
        driver, duration = float(event["driver"]), float(event["duration"])
        if type(event["reset"]) is not bool:
            raise ValueError("A task reset must be explicitly boolean")
        if direction is None:
            p = p @ transition(theta, driver, duration, nodes)
        else:
            flow, dflow = transition(theta, driver, duration, nodes, direction)
            dp, p = dp @ flow+p @ dflow, p @ flow
        if event["reset"]:
            p[:-1], dp[:-1] = origin, dorigin
    return (p, dp) if direction is not None else p


def _history_key(history):
    return tuple((float(e["driver"]), float(e["duration"]), bool(e["reset"])) for e in history)


def recurrent_features(family, theta, records):
    """Drop-in four-feature recurrence for the fixed native three-bin profile."""
    if family == "distribution":
        family = "analytic"
    _parameters(theta, 0., DEFAULT_NODES)
    if family not in ("ordinary", "analytic"):
        raise ValueError("Unknown cell family")
    origin = initial(theta) if family == "analytic" else np.array([.5, .5])
    states, flows = {(): origin}, {}

    def matrix(driver, duration, killed=False):
        key = (driver, duration, killed)
        if key not in flows:
            flows[key] = transition(theta, driver, duration, first_hit=killed)
        return flows[key]

    def state(key):
        if key not in states:
            p = state(key[:-1])
            driver, duration, reset = key[-1]
            if family == "analytic":
                p = (np.r_[p, 0.] @ matrix(driver, duration))[:-1]
            else:
                _parameters(theta, driver, DEFAULT_NODES)
                if not math.isfinite(duration) or not 0 <= duration <= 128:
                    raise ValueError("Duration envelope")
                rates = np.logaddexp(0., np.asarray(theta).reshape(2, 3) @ [1., driver, driver*driver])
                retain = np.exp(-rates*duration)
                p = retain*p+(1-retain)*np.array([expit(2*driver), driver*driver])
            states[key] = origin.copy() if reset else p
        return states[key]

    rows = []
    for record in records:
        if any(type(e["reset"]) is not bool for e in record["history"]):
            raise ValueError("Explicit boolean task reset required")
        p = state(_history_key(record["history"]))
        driver, horizon = float(record["driver"]), float(record["horizon"])
        _parameters(theta, driver, DEFAULT_NODES)
        if not 0 < horizon <= 128 or not math.isfinite(horizon):
            raise ValueError("Forecast horizon envelope")
        if family == "ordinary":
            rates = np.logaddexp(0., np.asarray(theta).reshape(2, 3) @ [1., driver, driver*driver])
            rows.append(np.r_[p, -np.expm1(-rates*horizon)])
        else:
            augmented = np.r_[p, 0.]
            count = float((augmented @ matrix(driver, horizon))[-1])
            hit = float((augmented @ matrix(driver, horizon, True))[-1])
            if (abs(p.sum()-1) > 5e-11 or p.min() < -5e-13
                    or not 0 <= hit <= 1+5e-12 or count+5e-12 < hit):
                raise ArithmeticError("Finite probability/event contract failed")
            rows.append([p[:3] @ np.array([1., 3., 5.])/6., p[3:].sum(), count/(1+count), hit])
    return np.asarray(rows, float).reshape(len(records), 4)


def augmented_features(family, parameters, records):
    parameters = np.asarray(parameters, float)
    if parameters.shape != (11,) or not np.all(np.isfinite(parameters)) or np.max(np.abs(parameters)) > 3:
        raise ValueError("Eleven finite parameters in [-3,3] required")
    raw = recurrent_features(family, parameters[:6], records)
    return np.column_stack((raw, expit(raw @ parameters[6:10]+parameters[10])))
