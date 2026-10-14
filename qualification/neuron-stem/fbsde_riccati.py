"""Scalar discrete Riccati seeds and tree-Newton elimination for the ORIGINAL FBSDE.

A linear field solves a DIFFERENT (identity, not tanh) problem. Newton uses only
its affine correction internally and rechecks fbsde_coupled.global_map. No model,
owner, production gate, continuous-time error or interval certificate is added.
"""
from dataclasses import asdict
import math

from four_gate_common import digest, require
from fbsde_coupled import forward, global_map, residual_report

LINEAR_TARGET = 'identity_terminal_and_generator.v1'


def _number(value, name, low, high):
    require(type(value) in (float, int) and math.isfinite(value) and low <= value <= high, name)
    return value


def linear_field(p):
    """Compile a time-indexed scalar Riccati field, reusable only for this profile."""
    p.validate()
    values = [0.] * p.steps + [1.]
    pivots = []
    for k in reversed(range(p.steps)):
        pivot = 1 + p.lam*p.h - p.a*p.h*values[k+1]
        require(math.isfinite(pivot) and pivot > 1e-10, 'linear Riccati pivot unsupported')
        values[k] = (values[k+1] + p.beta*p.h) / pivot
        require(math.isfinite(values[k]), 'linear field overflow')
        pivots.append(pivot)
    body = {'target': LINEAR_TARGET, 'profile': asdict(p), 'coefficients': values}
    return {**body, 'binding': digest(body), 'minimum_pivot': min(pivots)}


def linear_trace(p, x0, field):
    """Not a nonlinear answer. Verify recurrence even if caller rehashes a mutation."""
    p.validate()
    _number(x0, 'initial domain', -p.radius, p.radius)
    require(field['target'] == LINEAR_TARGET and field['profile'] == asdict(p),
            'linear field target/profile mismatch')
    coefficients = field['coefficients']
    require(type(coefficients) is list and len(coefficients) == p.steps+1 and
            all(type(v) in (float, int) and math.isfinite(v) for v in coefficients),
            'finite Riccati coefficient inventory')
    require(field['binding'] == digest({k: field[k] for k in ('target', 'profile', 'coefficients')}),
            'linear field binding mismatch')
    require(coefficients[-1] == 1., 'linear terminal boundary')
    for k in range(p.steps):
        pivot = 1+p.lam*p.h-p.a*p.h*coefficients[k+1]
        require(pivot > 1e-10 and abs(coefficients[k]*pivot-coefficients[k+1]-p.beta*p.h)
                <= 1e-12*max(1., abs(coefficients[k])), 'linear field recurrence mismatch')
    n = 2**p.steps-1
    x, y = [float(x0)] + [0.]*(2*n), []
    noise = p.sigma*math.sqrt(p.h)
    for i in range(n):
        value = coefficients[(i+1).bit_length()-1]*x[i]
        y.append(value)
        center = x[i]+p.a*p.h*value
        x[2*i+1], x[2*i+2] = center-noise, center+noise
    require(all(math.isfinite(v) for v in x+y), 'linear trajectory overflow')
    return {'x': x, 'y': y, 'target': LINEAR_TARGET,
            'original_nonlinear_solution_claimed': False}


def newton_direction(p, x0, y, *, pivot_floor=1e-10):
    """Exact-arithmetic Schur elimination of J(y) dy=-R(y) on the binary tree.

    deltaY_i=P_i*deltaX_i+r_i, deltaX_child=deltaX_i+a*h*deltaY_i.
    P,r are NODE-specific. They cannot generally be shared across time-level peers.
    Failed/small pivots reject; no clipping, inversion fallback or different target.
    """
    _number(pivot_floor, 'positive pivot floor', 1e-14, 1.)
    x = forward(p, x0, y)
    n, total = len(y), len(x)
    t = [math.tanh(v) for v in x]
    full_y = list(y)+t[n:]
    residual = [(1+p.lam*p.h)*y[i] - .5*(full_y[2*i+1]+full_y[2*i+2])
                - p.beta*p.h*t[i] for i in range(n)]
    slopes = [0.]*n + [1-v*v for v in t[n:]]
    affine, pivots = [0.]*total, []
    for i in reversed(range(n)):
        ps = .5*(slopes[2*i+1]+slopes[2*i+2])
        rs = .5*(affine[2*i+1]+affine[2*i+2])
        pivot = 1+p.lam*p.h-p.a*p.h*ps
        require(math.isfinite(pivot) and pivot > pivot_floor, 'linearized Riccati pivot unsupported')
        slopes[i] = (ps+p.beta*p.h*(1-t[i]*t[i])) / pivot
        affine[i] = (rs-residual[i]) / pivot
        pivots.append(pivot)
    dx, dy = [0.]*total, [0.]*n
    for i in range(n):
        dy[i] = slopes[i]*dx[i]+affine[i]
        dx[2*i+1] = dx[2*i+2] = dx[i]+p.a*p.h*dy[i]
    require(all(math.isfinite(v) for v in dx+dy+slopes+affine), 'Newton direction overflow')
    return {'dy': dy, 'dx': dx, 'minimum_pivot': min(pivots),
            'backward_nodes': n, 'forward_nodes': n,
            'node_specific_slopes': slopes, 'node_specific_affine': affine}


def solve_newton(p, x0, *, initial=None, tolerance=1e-10, max_updates=32,
                 max_backtracks=20, pivot_floor=1e-10):
    """Use the inherited original-global residual bound for EVERY acceptance/stop.

    This is bounded numerical execution, not a general convergence theorem.
    In particular an exhausted line search/iteration budget returns no solution.
    """
    p.validate()
    _number(x0, 'initial domain', -p.radius, p.radius)
    _number(tolerance, 'registered tolerance', 1e-13, 1e-2)
    _number(pivot_floor, 'positive pivot floor', 1e-14, 1.)
    require(type(max_updates) is int and 0 <= max_updates <= 128, 'bounded Newton updates')
    require(type(max_backtracks) is int and 0 <= max_backtracks <= 24, 'bounded line search')
    n = 2**p.steps-1
    require(initial is None or type(initial) is list and len(initial) == n,
            'bounded initial node inventory')
    y = [0.]*n if initial is None else list(initial)
    calls = 0
    def merit(values):
        nonlocal calls
        mapped = global_map(p, x0, values)
        calls += 1
        return max(abs(a-b) for a, b in zip(values, mapped))/(1-p.q)
    error = merit(y)
    errors, damping, pivots = [error], [], []
    for update in range(max_updates+1):
        if error <= tolerance:
            report = residual_report(p, x0, y)
            require(report['y_error_bound_exact_arithmetic'] <= tolerance,
                    'original residual changed on final check')
            return {'y': y, 'x': forward(p, x0, y), 'report': report,
                    'newton_updates': update, 'merit_map_calls': calls,
                    'final_report_map_calls': 1, 'error_bound_history': errors,
                    'damping': damping, 'pivot_history': pivots,
                    'original_problem_unchanged': True}
        require(update < max_updates, 'Newton iteration budget exhausted; no converged result')
        direction = newton_direction(p, x0, y, pivot_floor=pivot_floor)
        pivots.append(direction['minimum_pivot'])
        for j in range(max_backtracks+1):
            alpha = 2.**(-j)
            candidate = [v+alpha*d for v, d in zip(y, direction['dy'])]
            trial = merit(candidate)
            if trial <= (1-1e-4*alpha)*error:
                y, error = candidate, trial
                errors.append(error)
                damping.append(alpha)
                break
        else:
            raise ValueError('original-global-residual line search exhausted')
    raise AssertionError('unreachable bounded Newton loop')
