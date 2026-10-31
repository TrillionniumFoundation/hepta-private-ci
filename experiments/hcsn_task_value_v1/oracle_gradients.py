"""Implicit and one-sided optimal-value sensitivities of the finite QVI.

At tied optimal actions, solve a tangent Bellman problem rather than
differentiating argmax or pretending every selected policy is locally unique.
These derivatives belong to a finite CTMC, not a continuum free-boundary proof.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

from .oracle import _array, branches, policy_system, solve_policy


@dataclass(frozen=True)
class Tangent:
    rates: csr_matrix
    discount: float
    cash: np.ndarray


@dataclass(frozen=True)
class Sensitivity:
    right: np.ndarray
    left: np.ndarray
    fixed: np.ndarray
    kink_norm: float
    tie_states: int
    active_tolerance: float


def _rate_derivatives(cell, x, dmu, dsigma):
    h = float(x[1]-x[0])
    base = .5*(cell.diffusion/h)**2
    down, up = base-cell.drift/(2*h), base+cell.drift/(2*h)
    if (dmu or dsigma) and abs(min(down, up)) < 1e-12*max(1., base):
        raise ValueError("Centered/upwind switch has no declared ordinary derivative")
    dd = cell.diffusion*dsigma/(h*h)
    if min(down, up) < 0:
        dm = dd + (-dmu/h if cell.drift < 0 else 0)
        dp = dd + (dmu/h if cell.drift > 0 else 0)
    else:
        dm, dp = dd-dmu/(2*h), dd+dmu/(2*h)
    return dm, dp


def _reset_derivative(model, axis, coordinate, supplied):
    base = model.reset1 if axis == 0 else model.reset2
    derivative = np.zeros_like(base)
    if supplied is not None:
        derivative += _array(supplied, base.shape, "reset kernel tangent")
    if coordinate:
        if not model.coordinate_reset[axis]:
            raise ValueError("Coordinate derivative cannot modify an explicit reset kernel")
        x = model.x1 if axis == 0 else model.x2
        cell = model.cells.first if axis == 0 else model.cells.second
        h = float(x[1]-x[0])
        if np.min(np.abs(x-cell.reset)) < 1e-12*max(1., abs(cell.reset), abs(h)):
            raise ValueError("Reset at interpolation node requires separate one-sided kernels")
        j = int(np.searchsorted(x, cell.reset)-1)
        derivative[:, j] -= coordinate/h
        derivative[:, j+1] += coordinate/h
    if np.max(np.abs(derivative.sum(axis=1))) > 2e-12:
        raise ValueError("Reset tangent must preserve probability mass")
    if np.any((base == 0) & (derivative != 0)):
        raise ValueError("Two-sided reset tangent leaves simplex at a zero-probability entry")
    return derivative


def direction(model, *, drift=(0., 0.), diffusion=(0., 0.), discount=0.,
              refractory=(0., 0.), cost=(0., 0.), reset=(0., 0.),
              reset1=None, reset2=None, running=None, impulse1=None, impulse2=None):
    """Analytic primitive derivatives; phase counts and grid coordinates are fixed.

    Cost directions subtract from event reward even if an event array was
    supplied: callers must use the same convention when rebuilding perturbations.
    Explicit reset tangents are two-sided probability-simplex tangents.
    """
    for name, pair in (("drift", drift), ("diffusion", diffusion),
                       ("refractory", refractory), ("cost", cost), ("reset", reset)):
        if len(pair) != 2 or not all(math.isfinite(z) for z in pair):
            raise ValueError(f"Invalid {name} direction")
    if not math.isfinite(discount):
        raise ValueError("Invalid discount direction")
    n1, n2 = len(model.x1), len(model.x2)
    s1, s2 = model.shape
    cells = (model.cells.first, model.cells.second)
    rates = [_rate_derivatives(c, x, dm, ds) for c, x, dm, ds in
             zip(cells, (model.x1, model.x2), drift, diffusion)]
    lam = [k/c.refractory for k, c in zip(model.phases, cells)]
    dlam = [-k*dt/c.refractory**2 for k, c, dt in
            zip(model.phases, cells, refractory)]
    dk1 = _reset_derivative(model, 0, reset[0], reset1)
    dk2 = _reset_derivative(model, 1, reset[1], reset2)
    rows, cols, data = [], [], []
    for i in range(s1):
        for j in range(s2):
            row, edges = i*s2+j, []
            if i < n1:
                if i:
                    edges.append(((i-1)*s2+j, rates[0][0]))
                if i < n1-1:
                    edges.append(((i+1)*s2+j, rates[0][1]))
            elif i == n1:
                ds = dlam[0]*model.reset1[j]+lam[0]*dk1[j]
                edges.extend((ii*s2+j, rate) for ii, rate in enumerate(ds) if rate)
            else:
                edges.append(((i-1)*s2+j, dlam[0]))
            if j < n2:
                if j:
                    edges.append((i*s2+j-1, rates[1][0]))
                if j < n2-1:
                    edges.append((i*s2+j+1, rates[1][1]))
            elif j == n2:
                ds = dlam[1]*model.reset2[i]+lam[1]*dk2[i]
                edges.extend((i*s2+jj, rate) for jj, rate in enumerate(ds) if rate)
            else:
                edges.append((i*s2+j-1, dlam[1]))
            for dest, rate in edges:
                rows.append(row); cols.append(dest); data.append(rate)
    size = s1*s2
    derivative_rates = csr_matrix((data, (rows, cols)), shape=(size, size))
    cash = np.zeros((3, s1, s2))
    for action, arr in enumerate((running, impulse1, impulse2)):
        if arr is not None:
            cash[action] = _array(arr, model.shape, "reward tangent")
    cash[1, :n1, :] -= cost[0]
    cash[2, :, :n2] -= cost[1]
    return Tangent(derivative_rates, float(discount), cash.reshape(3, size))


def tangent_cash(model, result, tangent):
    """b'_a - A'_a V, with WAIT in physical-time generator units."""
    size = len(model.denominator)
    if tangent.rates.shape != (size, size) or tangent.cash.shape != (3, size):
        raise ValueError("Tangent dimensions do not match model")
    if not (np.all(np.isfinite(tangent.rates.data)) and
            np.all(np.isfinite(tangent.cash)) and math.isfinite(tangent.discount)):
        raise ValueError("Nonfinite tangent")
    v = result.values.ravel()
    forcing = np.array(tangent.cash, copy=True)
    diagonal = tangent.discount + np.asarray(tangent.rates.sum(axis=1)).ravel()
    forcing[0] += tangent.rates @ v - diagonal*v
    return forcing


def fixed_policy_gradient(model, result, tangent):
    forcing = tangent_cash(model, result, tangent)
    matrix, rhs = policy_system(model, result.policy, forcing)
    derivative = spsolve(matrix, rhs)
    if not np.all(np.isfinite(derivative)):
        raise ArithmeticError("Nonfinite implicit sensitivity")
    return derivative.reshape(model.shape)


def one_sided_gradients(model, result, tangent, *, active_tolerance=1e-10):
    """Right derivative and conventional left derivative along one direction.

    At exact ties the derivative satisfies its own Bellman problem over base
    optimal actions. Tolerance admits numerically tied actions; users must check
    its stability and finite differences. No claim of smoothness at every state.
    """
    if not math.isfinite(active_tolerance) or not 1e-14 <= active_tolerance <= 1e-6:
        raise ValueError("Invalid active-set tolerance")
    v = result.values.ravel()
    q = branches(model, v)
    scale = np.maximum(1., np.abs(v))
    errors = v[None, :] - q
    if float(np.max(np.abs(np.max(q, axis=0)-v)/scale)) > active_tolerance:
        raise ValueError("Base value is not accurate enough for tangent active set")
    allowed = model.eligible & (errors <= active_tolerance*scale[None, :])
    forcing = tangent_cash(model, result, tangent)
    right = solve_policy(model, cash=forcing, allowed=allowed).values
    left = -solve_policy(model, cash=-forcing, allowed=allowed).values
    fixed = fixed_policy_gradient(model, result, tangent)
    return Sensitivity(right, left, fixed, float(np.max(np.abs(right-left))),
                       int(np.sum(allowed.sum(axis=0) > 1)), active_tolerance)
