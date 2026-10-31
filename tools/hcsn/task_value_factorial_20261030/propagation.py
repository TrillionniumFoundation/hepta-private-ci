"""Finite regenerative diffusion reference and exact lower-barrier FPT features.

The task predictor may use first_passage without assuming that repository reads
are Brownian paths. The CTMC below is a separate, declared finite model: reflected
lower grid face, absorbing upper jump followed by independent Erlang refractory
phases, and convex reset interpolation. It is not the continuum He--Xiong model.

Design references (not imported dependencies): HCSN model 1d959d8d82091e6014b13c2191f62bf74e778561;
two-cell Erlang QVI 558989c92f64533e8bd8fa278ad1e97217a046cb.
"""

from dataclasses import dataclass
import itertools
import math

import numpy as np
from scipy.linalg import expm, expm_frechet
from scipy.integrate import solve_ivp
from scipy.special import erfcx, log_ndtr


class NondifferentiablePoint(ValueError):
    """A directional derivative crosses a hard branch or interpolation knot."""


def first_passage(distance, drift, sigma, horizon):
    """P(inf[0,T] X <= 0), X=distance+drift*t+sigma*W; negative drift approaches.

    Supports NumPy broadcasting. Evaluates the reflected exponential/CDF product
    with erfcx when cancellation between its logarithmic factors would be large.
    Only probability is returned: saturated tails are not log-likelihood evidence.
    """
    x, mu, sd, t = np.broadcast_arrays(*[
        np.asarray(z, dtype=float) for z in (distance, drift, sigma, horizon)])
    if not all(np.all(np.isfinite(z)) for z in (x, mu, sd, t)):
        raise ValueError("FPT inputs must be finite")
    if np.any(x < 0) or np.any(sd <= 0) or np.any(t < 0):
        raise ValueError("Require distance >= 0, sigma > 0, horizon >= 0")
    active = (x > 0) & (t > 0)
    safe_t = np.where(active, t, 1.0)
    scale = sd * np.sqrt(safe_t)
    z1, z2 = (-x-mu*safe_t)/scale, (-x+mu*safe_t)/scale
    second = np.empty_like(x)
    reflected = z2 <= 0
    with np.errstate(over="ignore", under="ignore", divide="ignore"):
        second[reflected] = (math.log(.5) - .5*z1[reflected]**2
            + np.log(erfcx(-z2[reflected]/math.sqrt(2))))
        other = ~reflected
        second[other] = (-2*mu[other]*x[other]/sd[other]**2
                         + log_ndtr(z2[other]))
        value = np.exp(np.logaddexp(log_ndtr(z1), second))
    value = np.where(x == 0, 1.0, np.where(t == 0, 0.0, value))
    if np.any(~np.isfinite(value)) or np.any(value < 0) or np.any(value > 1+2e-13):
        raise ArithmeticError("FPT probability cannot be represented reliably")
    # At most floating-point rounding above the mathematical upper bound.
    return np.minimum(value, 1.0)


def fpt_features(distance, drift, sigma, horizon):
    """Scalar FPT summary; an unresolved saturated hazard is explicitly None."""
    p = float(first_passage(distance, drift, sigma, horizon))
    if distance == 0 or horizon == 0:
        density, log_density = 0.0, None
    else:
        log_density = (math.log(distance/sigma)-.5*math.log(2*math.pi)
            -1.5*math.log(horizon)
            -(distance+drift*horizon)**2/(2*sigma*sigma*horizon))
        if log_density > math.log(np.finfo(float).max):
            raise ArithmeticError("FPT density exceeds float64 range")
        density = math.exp(log_density)
    survival = 1-p
    return dict(hit_probability=p, survival=survival, density=density,
        log_density=log_density,
        hazard=density/survival if survival > 1e-14 else None,
        initial_atom=distance == 0,
        model="fixed_coefficient_lower_barrier_first_passage")


@dataclass(frozen=True)
class Cell:
    drift: float = .3
    sigma: float = .35
    boundary: float = 1.0
    reset: float = -.2
    refractory: float = .25
    lower: float = -1.0
    active: int = 5
    phases: int = 2

    def validate(self):
        if not all(math.isfinite(getattr(self, k)) for k in
                   ("drift", "sigma", "boundary", "reset", "refractory", "lower")):
            raise ValueError("Cell scalars must be finite")
        if not (self.sigma > 0 and self.refractory > 0 and self.boundary > self.lower
                and type(self.active) is int and 2 <= self.active <= 12
                and type(self.phases) is int and 1 <= self.phases <= 6):
            raise ValueError("Invalid cell domain or state budget")
        h = (self.boundary-self.lower)/self.active
        if not self.lower+h/2 <= self.reset <= self.boundary-h/2:
            raise ValueError("Reset must lie within the active cell centers")


def _geometry(cell, direction):
    cell.validate()
    d = direction or {}
    allowed = {"drift", "sigma", "boundary", "reset", "refractory"}
    if set(d)-allowed or not all(math.isfinite(v) for v in d.values()):
        raise ValueError("Invalid derivative direction")
    h = (cell.boundary-cell.lower)/cell.active
    dh = d.get("boundary", 0.0)/cell.active
    index = np.arange(cell.active)+.5
    return h, dh, cell.lower+h*index, dh*index


def _interpolate(x, dx, cell, direction):
    h, dh, _, _ = _geometry(cell, direction)
    y = (x-cell.lower)/h-.5
    dy = dx/h-(x-cell.lower)*dh/h**2
    if y <= 0:
        if abs(y) < 1e-10 and abs(dy) > 1e-12:
            raise NondifferentiablePoint("Lower interpolation knot")
        return [(0, 1.0, 0.0)]
    if y >= cell.active-1:
        if abs(y-cell.active+1) < 1e-10 and abs(dy) > 1e-12:
            raise NondifferentiablePoint("Upper interpolation knot")
        return [(cell.active-1, 1.0, 0.0)]
    i = int(math.floor(y))
    if min(y-i, i+1-y) < 1e-10 and abs(dy) > 1e-12:
        raise NondifferentiablePoint("Reset/remap interpolation knot")
    return [(i, 1-y+i, -dy), (i+1, y-i, dy)]


def _axis_edges(state, axis, cells, coupling, directions, dcoupling):
    cell = cells[axis]
    d = directions[axis]
    i = state[axis]
    h, dh, _, _ = _geometry(cell, d)
    if i >= cell.active:
        rate = cell.phases/cell.refractory
        drate = -rate*d.get("refractory", 0.0)/cell.refractory
        if i > cell.active:
            yield i-1, rate, drate, 0
        else:
            for j, w, dw in _interpolate(cell.reset, d.get("reset", 0.), cell, d):
                yield j, rate*w, drate*w+rate*dw, 0
        return
    mu, dmu = cell.drift, d.get("drift", 0.0)
    for other, c in enumerate(cells):
        if other == axis or state[other] >= c.active:
            continue
        _, _, centers, dcenters = _geometry(c, directions[other])
        z = centers[state[other]]-c.reset
        dz = dcenters[state[other]]-directions[other].get("reset", 0.)
        mu += coupling*z
        dmu += dcoupling*z+coupling*dz
    if abs(mu) < 1e-12 and abs(dmu) > 1e-12:
        raise NondifferentiablePoint("Upwind drift changes sign")
    diff = cell.sigma**2/(2*h*h)
    ddiff = cell.sigma*d.get("sigma", 0.)/h**2-2*diff*dh/h
    for sign in (-1, 1):
        drift = max(sign*mu, 0.)
        ddrift = sign*dmu if sign*mu > 0 else 0.
        rate, drate = diff+drift/h, ddiff+ddrift/h-drift*dh/h**2
        if i+sign < 0:
            continue  # Lower face reflects by blocking the outward jump.
        fire = int(i+sign == cell.active)
        target = cell.active+cell.phases-1 if fire else i+sign
        yield target, rate, drate, fire


def generator(cells, coupling=0.0, directions=None, dcoupling=0.0):
    """Return Q, event rates, and exact active-set directional derivatives."""
    cells = tuple(cells)
    if not 1 <= len(cells) <= 2 or not math.isfinite(coupling+dcoupling):
        raise ValueError("One or two cells with finite coupling required")
    directions = tuple(directions or ({} for _ in cells))
    if len(directions) != len(cells):
        raise ValueError("Derivative direction count mismatch")
    for c, d in zip(cells, directions):
        _geometry(c, d)
    shape = tuple(c.active+c.phases for c in cells)
    size = math.prod(shape)
    if size > 256:
        raise ValueError("Reference dense-state budget exceeded")
    q, dq = np.zeros((size, size)), np.zeros((size, size))
    r, dr = np.zeros((size, len(cells))), np.zeros((size, len(cells)))
    for state in itertools.product(*(range(n) for n in shape)):
        row = np.ravel_multi_index(state, shape)
        for axis in range(len(cells)):
            for target, rate, deriv, fire in _axis_edges(
                    state, axis, cells, coupling, directions, dcoupling):
                successor = list(state)
                successor[axis] = target
                col = np.ravel_multi_index(tuple(successor), shape)
                q[row, col] += rate
                dq[row, col] += deriv
                q[row, row] -= rate
                dq[row, row] -= deriv
                r[row, axis] += rate*fire
                dr[row, axis] += deriv*fire
    return q, r, dq, dr


def flow(cells, duration, coupling=0.0, directions=None, dcoupling=0.0,
         dduration=0.0):
    """Matrix exponential and Frechet derivative, including repeated counts."""
    if not math.isfinite(duration+dduration) or duration < 0:
        raise ValueError("Finite nonnegative duration required")
    q, r, dq, dr = generator(cells, coupling, directions, dcoupling)
    n, k = r.shape
    a, da = np.zeros((n+k, n+k)), np.zeros((n+k, n+k))
    a[:n, :n], a[:n, n:] = q, r
    da[:n, :n], da[:n, n:] = dq, dr
    if directions is None and dcoupling == 0 and dduration == 0:
        value, derivative = expm(duration*a), np.zeros_like(a)
    else:
        value, derivative = expm_frechet(duration*a, duration*da+dduration*a)
    return value[:n, :n], value[:n, n:], derivative[:n, :n], derivative[:n, n:]


def remap(old, new, old_directions=None, new_directions=None):
    """Conservative moving-grid remap; covered active mass fires at time zero.

    Existing refractory phase indices persist. A change in refractory parameter
    changes future phase rates; it never restarts elapsed phase progress.
    """
    if len(old) != len(new) or any((a.active, a.phases) != (b.active, b.phases)
                                  for a, b in zip(old, new)):
        raise ValueError("Grid topology cannot change within a stream")
    old_directions = tuple(old_directions or ({} for _ in old))
    new_directions = tuple(new_directions or ({} for _ in new))
    if len(old_directions) != len(old) or len(new_directions) != len(new):
        raise ValueError("Remap derivative direction count mismatch")
    matrices, derivatives, fire_vectors = [], [], []
    for a, b, da, db in zip(old, new, old_directions, new_directions):
        n = a.active+a.phases
        m, dm, fire = np.zeros((n, n)), np.zeros((n, n)), np.zeros(n)
        _, _, centers, dcenters = _geometry(a, da)
        for i in range(n):
            if i >= a.active:
                m[i, i] = 1.
                continue
            x, dx = centers[i], dcenters[i]
            if abs(x-b.boundary) < 1e-10 and abs(dx-db.get("boundary", 0.)) > 1e-12:
                raise NondifferentiablePoint("Moving boundary crosses active mass atom")
            if x >= b.boundary:
                m[i, b.active+b.phases-1], fire[i] = 1., 1.
            else:
                for j, w, dw in _interpolate(x, dx, b, db):
                    m[i, j] += w
                    dm[i, j] += dw
        matrices.append(m)
        derivatives.append(dm)
        fire_vectors.append(fire)
    m, dm = np.ones((1, 1)), np.zeros((1, 1))
    for value, deriv in zip(matrices, derivatives):
        dm, m = np.kron(dm, value)+np.kron(m, deriv), np.kron(m, value)
    shape = tuple(c.active+c.phases for c in old)
    atoms = np.zeros((math.prod(shape), len(old)))
    for state in itertools.product(*(range(n) for n in shape)):
        atoms[np.ravel_multi_index(state, shape)] = [f[i] for f, i in zip(fire_vectors, state)]
    return m, atoms, dm


def rollout(initial, initial_cells, schedule, directions=None):
    """Schedule rows have cells/duration/coupling and optional corresponding d*.

    Initial probabilities are parameter-independent. Derivatives include every
    remap, exponential, reset interpolation, refractory rate and previous state.
    """
    p = np.asarray(initial, dtype=float).copy()
    if p.shape != (math.prod(c.active+c.phases for c in initial_cells),):
        raise ValueError("Initial distribution shape mismatch")
    if np.any(p < 0) or abs(p.sum()-1) > 1e-12:
        raise ValueError("Initial distribution must have unit nonnegative mass")
    dp, counts, dcounts = np.zeros_like(p), np.zeros(len(initial_cells)), np.zeros(len(initial_cells))
    old, old_d = initial_cells, directions
    rows = []
    for step in schedule:
        cells, d = step["cells"], step.get("directions")
        m, atoms, dm = remap(old, cells, old_d, d)
        counts += p@atoms
        dcounts += dp@atoms
        dp, p = dp@m+p@dm, p@m
        t, events, dt, devents = flow(cells, step["duration"], step.get("coupling", 0.),
            d, step.get("dcoupling", 0.), step.get("dduration", 0.))
        counts += p@events
        dcounts += dp@events+p@devents
        dp, p = dp@t+p@dt, p@t
        rows.append(dict(mass=float(p.sum()), minimum=float(p.min()),
                         counts=counts.tolist(), derivative_mass=float(dp.sum())))
        old, old_d = cells, d
    return dict(probability=p, counts=counts, probability_derivative=dp,
                count_derivative=dcounts, rows=rows)


def factorized_rollout(initial, initial_cells, schedule):
    """Two marginal mean-field approximation; correlations are discarded.

    This is an explicitly approximate alternative to the product-state CTMC.
    Expected other-cell active displacement replaces its actual state in drift.
    ODE accuracy does not bound this closure's modeling error. No derivatives
    through this approximation are certified here.
    """
    if len(initial_cells) != 2:
        raise ValueError("Factorized reference requires exactly two cells")
    shape = tuple(c.active+c.phases for c in initial_cells)
    initial = np.asarray(initial, dtype=float)
    if initial.shape != (math.prod(shape),) or np.any(initial < 0) or abs(initial.sum()-1) > 1e-12:
        raise ValueError("Invalid initial probability")
    joint = initial.reshape(shape)
    marginals = [joint.sum(axis=1), joint.sum(axis=0)]
    counts, previous = np.zeros(2), initial_cells
    for segment in schedule:
        cells = segment["cells"]
        if tuple(c.active+c.phases for c in cells) != shape:
            raise ValueError("Marginal state topology cannot change")
        for i in range(2):
            matrix, atoms, _ = remap((previous[i],), (cells[i],))
            counts[i] += float(marginals[i]@atoms[:, 0])
            marginals[i] = marginals[i]@matrix
        def rhs(time, value):
            del time
            ps = [value[:shape[0]], value[shape[0]:sum(shape)]]
            means = [float(p[:c.active]@(_geometry(c, {})[2]-c.reset)) for p, c in zip(ps, cells)]
            dp, dc = [], []
            for i in range(2):
                c = cells[i]
                mu = c.drift+segment.get("coupling", 0.)*means[1-i]
                local = Cell(mu, c.sigma, c.boundary, c.reset, c.refractory, c.lower, c.active, c.phases)
                q, rewards, _, _ = generator((local,))
                dp.append(ps[i]@q)
                dc.append(float(ps[i]@rewards[:, 0]))
            return np.concatenate((*dp, dc))
        start = np.concatenate((*marginals, counts))
        duration = segment["duration"]
        if duration < 0 or not math.isfinite(duration):
            raise ValueError("Invalid duration")
        if duration > 0:
            solution = solve_ivp(rhs, (0., duration), start, method="DOP853", rtol=1e-10, atol=1e-12)
            if not solution.success:
                raise ArithmeticError("Mean-field integrator failed")
            start = solution.y[:, -1]
        marginals = [start[:shape[0]], start[shape[0]:sum(shape)]]
        counts, previous = start[-2:], cells
    return dict(probability=np.outer(*marginals).ravel(), counts=counts,
                retained_states=sum(shape), exact_joint_states=math.prod(shape))
