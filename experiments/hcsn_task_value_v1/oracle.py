"""Finite task-value QVI with asynchronous refractory and general reset kernels.

This extends the exact #4393 finite CTMC contract, not the He--Xiong financial
equilibrium. Rewards are signed: running reward is per unit physical time;
impulse reward is paid once at FIRE. General rewards need not yield a single
threshold. Independent algorithms below solve the same finite discretization.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.sparse import csr_matrix, lil_matrix
from scipy.sparse.linalg import spsolve

from ..hcsn_hx_unified_v3.erlang_async_qvi import _prepare


@dataclass(frozen=True)
class Model:
    cells: object
    rect: object
    phases: tuple
    x1: np.ndarray
    x2: np.ndarray
    shape: tuple
    neighbors: tuple
    rates: csr_matrix
    denominator: np.ndarray
    targets: np.ndarray
    eligible: np.ndarray
    cash: np.ndarray
    reset1: np.ndarray
    reset2: np.ndarray
    coordinate_reset: tuple


@dataclass(frozen=True)
class Result:
    values: np.ndarray
    policy: np.ndarray
    iterations: int
    bellman_residual: float
    qvi_residual: float


def _array(value, shape, name):
    out = np.array(value, dtype=np.float64, copy=True)
    if out.shape != shape or not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must be finite with shape {shape}")
    out.flags.writeable = False
    return out


def _kernel(value, shape, interpolation, name):
    if value is None:
        value = np.zeros(shape)
        for index, weight in interpolation:
            value[:, index] = weight
    out = _array(value, shape, name)
    if np.min(out) < 0 or np.max(np.abs(out.sum(axis=1) - 1)) > 2e-13:
        raise ValueError(f"{name} must be a row-stochastic reset kernel")
    return out


def build(cells, rect, phases=(2, 2), *, running=None, impulse1=None,
          impulse2=None, reset1=None, reset2=None):
    """Build finite CTMC. Reset1 has shape (n2+k2,n1), Reset2 (n1+k1,n2).

    A recovery kernel may depend on the other cell's current active/phase state.
    All reward arrays have the full state shape, including refractory states.
    """
    g = _prepare(cells, rect, phases)
    n1, n2 = len(g.x1), len(g.x2)
    shape = (n1 + g.k1, n2 + g.k2)
    size = math.prod(shape)
    k1 = _kernel(reset1, (shape[1], n1), g.r1, "reset1")
    k2 = _kernel(reset2, (shape[0], n2), g.r2, "reset2")
    cash = np.zeros((3, *shape))
    cash[1, :n1, :] = g.x1[:, None] - cells.first.cost
    cash[2, :, :n2] = g.x2[None, :] - cells.second.cost
    for action, value in enumerate((running, impulse1, impulse2)):
        if value is not None:
            cash[action] = _array(value, shape, f"reward{action}")
    targets = np.full((2, size), -1, dtype=np.int64)
    eligible = np.zeros((3, size), dtype=bool)
    eligible[0] = True
    neighbors, rows, cols, weights = [], [], [], []
    for i in range(shape[0]):
        for j in range(shape[1]):
            row, edges = i * shape[1] + j, []
            if i < n1:
                if i > 0:
                    edges.append(((i-1)*shape[1]+j, g.qm1[i]))
                if i < n1-1:
                    edges.append(((i+1)*shape[1]+j, g.qp1[i]))
                targets[0, row] = (shape[0]-1)*shape[1]+j
                eligible[1, row] = True
            elif i == n1:
                edges.extend((ii*shape[1]+j, g.lam1*w)
                             for ii, w in enumerate(k1[j]) if w)
            else:
                edges.append(((i-1)*shape[1]+j, g.lam1))
            if j < n2:
                if j > 0:
                    edges.append((i*shape[1]+j-1, g.qm2[j]))
                if j < n2-1:
                    edges.append((i*shape[1]+j+1, g.qp2[j]))
                targets[1, row] = i*shape[1]+shape[1]-1
                eligible[2, row] = True
            elif j == n2:
                edges.extend((i*shape[1]+jj, g.lam2*w)
                             for jj, w in enumerate(k2[i]) if w)
            else:
                edges.append((i*shape[1]+j-1, g.lam2))
            neighbors.append(tuple((int(dest), float(rate)) for dest, rate in edges))
            for dest, rate in edges:
                rows.append(row); cols.append(dest); weights.append(rate)
    rates = csr_matrix((weights, (rows, cols)), shape=(size, size))
    total = np.asarray(rates.sum(axis=1)).ravel()
    denominator = g.rho + total
    if not np.all(np.isfinite(denominator)) or not np.all(denominator > total):
        raise ArithmeticError("Nonfinite rates or lost discount in fp64")
    for array in (cash, targets, eligible, denominator):
        array.flags.writeable = False
    return Model(cells, rect, phases, g.x1, g.x2, shape, tuple(neighbors),
                 rates, denominator, targets, eligible, cash.reshape(3, size),
                 k1, k2, (reset1 is None, reset2 is None))


def branches(model, values, cash=None):
    """Normalized Bellman branches, with ineligible actions represented by -inf."""
    v = np.asarray(values).ravel()
    rewards = model.cash if cash is None else cash
    out = np.full_like(rewards, -math.inf)
    out[0] = (rewards[0] + model.rates @ v) / model.denominator
    for action in (1, 2):
        mask = model.eligible[action]
        out[action, mask] = rewards[action, mask] + v[model.targets[action-1, mask]]
    return out


def policy_system(model, policy, cash=None):
    """Raw generator rows for WAIT, instantaneous intervention rows for FIRE."""
    p = np.asarray(policy).ravel()
    rewards = model.cash if cash is None else cash
    size = len(model.denominator)
    if p.shape != (size,) or not np.issubdtype(p.dtype, np.integer):
        raise ValueError("Policy shape/type invalid")
    if np.any((p < 0) | (p > 2)) or not np.all(model.eligible[p, np.arange(size)]):
        raise ValueError("Policy contains ineligible action")
    matrix = lil_matrix((size, size))
    rhs = rewards[p, np.arange(size)]
    for row, action in enumerate(p):
        if action == 0:
            matrix[row, row] = model.denominator[row]
            for dest, rate in model.neighbors[row]:
                matrix[row, dest] -= rate
        else:
            matrix[row, row] = 1
            matrix[row, model.targets[action-1, row]] -= 1
    return matrix.tocsc(), rhs


def _controls(model, cash, allowed):
    rewards = model.cash if cash is None else _array(cash, model.cash.shape, "cash")
    choices = model.eligible if allowed is None else np.asarray(allowed, dtype=bool)
    if choices.shape != model.eligible.shape or np.any(choices & ~model.eligible):
        raise ValueError("Action mask is invalid")
    if not np.all(choices.any(axis=0)):
        raise ValueError("Every state requires at least one action")
    return rewards, choices


def _result(model, v, policy, iterations, rewards, allowed):
    if not np.all(np.isfinite(v)):
        raise ArithmeticError("Nonfinite task value")
    differences = np.where(allowed, branches(model, v, rewards)-v, -math.inf)
    bellman = float(np.max(np.abs(differences.max(axis=0))))
    differences[0] *= model.denominator
    qvi = float(np.max(np.abs(differences.max(axis=0))))
    return Result(v.reshape(model.shape), policy.reshape(model.shape), iterations,
                  bellman, qvi)


def solve_policy(model, *, cash=None, allowed=None, max_iterations=200,
                 decision_tolerance=1e-12):
    """Howard iteration; no single-threshold or nonnegative-value assumption."""
    if type(max_iterations) is not int or not 1 <= max_iterations <= 2000:
        raise ValueError("Invalid iteration budget")
    if not math.isfinite(decision_tolerance) or not 0 <= decision_tolerance <= 1e-7:
        raise ValueError("Invalid decision tolerance")
    rewards, choices = _controls(model, cash, allowed)
    policy = np.argmax(choices, axis=0).astype(np.int8)
    indices = np.arange(policy.size)
    for iteration in range(1, max_iterations+1):
        matrix, rhs = policy_system(model, policy, rewards)
        v = spsolve(matrix, rhs)
        if not np.all(np.isfinite(v)):
            raise ArithmeticError("Nonfinite policy evaluation")
        q = np.where(choices, branches(model, v, rewards), -math.inf)
        proposal = np.argmax(q, axis=0).astype(np.int8)
        improve = q.max(axis=0) > q[policy, indices] + decision_tolerance
        proposal = np.where(improve, proposal, policy).astype(np.int8)
        if np.array_equal(proposal, policy):
            out = _result(model, v, policy, iteration, rewards, choices)
            scale = max(1., float(np.max(np.abs(v))))
            if out.bellman_residual > max(3*decision_tolerance, 1e-10)*scale:
                raise ArithmeticError("Howard stopped with excessive residual")
            return out
        policy = proposal
    raise RuntimeError("Howard iteration budget exhausted")


def solve_jacobi(model, *, tolerance=1e-12, max_iterations=150000):
    """Separate scalar-loop Bellman updates, without sparse policy assembly."""
    if not math.isfinite(tolerance) or not 0 < tolerance < 1e-4:
        raise ValueError("Invalid Jacobi tolerance")
    if type(max_iterations) is not int or not 1 <= max_iterations <= 500000:
        raise ValueError("Invalid Jacobi budget")
    size = len(model.denominator)
    v, policy = np.zeros(size), np.zeros(size, dtype=np.int8)
    for iteration in range(1, max_iterations+1):
        nxt = np.empty_like(v)
        for row in range(size):
            flow = sum(rate*v[dest] for dest, rate in model.neighbors[row])
            best = (model.cash[0, row]+flow)/model.denominator[row]
            act = 0
            for action in (1, 2):
                if model.eligible[action, row]:
                    candidate = model.cash[action, row]+v[model.targets[action-1, row]]
                    if candidate > best:
                        best, act = candidate, action
            nxt[row], policy[row] = best, act
        error = float(np.max(np.abs(nxt-v)))
        v = nxt
        if error < tolerance:
            return _result(model, v, policy, iteration, model.cash, model.eligible)
    raise RuntimeError("Jacobi iteration budget exhausted")
