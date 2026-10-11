"""Nonlinear Y-coupled finite-tree FBSDE with an explicit residual error bound.

Continuous target: dX=aY dt+sigma dW; dY=(lam*Y-beta*tanh(X))dt+Z dW,
Y_T=tanh(X_T). This module solves its REGISTERED binary-increment discretization,
not the continuous equation or a task reasoning/production acceptance problem.
The posterior error bound is an exact-arithmetic theorem; float residuals are not
outward-rounded interval certificates. No outcome/model authority is introduced.
"""
from bisect import bisect_right
from dataclasses import asdict, dataclass
import math
from four_gate_common import require


@dataclass(frozen=True)
class CoupledProfile:
    horizon: float = .8
    steps: int = 5
    a: float = .55
    beta: float = .5
    lam: float = .2
    sigma: float = .3
    radius: float = 1.

    @property
    def h(self):
        return self.horizon / self.steps

    @property
    def q(self):
        return self.a * self.horizon * (1 + self.beta * self.horizon)

    @property
    def y_bound(self):
        return 1 + self.beta * self.horizon

    def validate(self):
        require(type(self.steps) is int and 1 <= self.steps <= 10, 'bounded binary time grid')
        for key in ('horizon', 'a', 'beta', 'lam', 'sigma', 'radius'):
            value = getattr(self, key)
            require(type(value) in (float, int) and math.isfinite(value), 'finite profile coefficient')
        require(0 < self.horizon <= 2 and 0 < self.radius <= 4 and
                all(0 <= getattr(self, k) <= 4 for k in ('a', 'beta', 'lam', 'sigma')),
                'coefficient domain')
        require(self.q < .98, 'global contraction margin unsupported; mesh refinement cannot waive it')
        return self


def _vector(values, size):
    require(type(values) is list and len(values) == size and
            all(type(v) in (float, int) and math.isfinite(v) for v in values),
            'finite complete nonanticipative node vector required')


def _initial(p, x0):
    p.validate()
    require(type(x0) in (float, int) and math.isfinite(x0) and abs(x0) <= p.radius,
            'initial state outside registered domain')


def forward(p, x0, y):
    """One value per public binary prefix: there is no future-world action input."""
    _initial(p, x0)
    count = 2**p.steps - 1
    _vector(y, count)
    x = [0.] * (2*count+1)
    x[0] = float(x0)
    noise = p.sigma * math.sqrt(p.h)
    for i in range(count):
        mean = x[i] + p.a * p.h * y[i]
        x[2*i+1], x[2*i+2] = mean-noise, mean+noise
    require(all(math.isfinite(v) for v in x), 'forward overflow')
    return x


def global_map(p, x0, y):
    """F(Y)=backward(forward(Y)); conditional expectation uses both children."""
    x = forward(p, x0, y)
    count = len(y)
    value = [0.] * count + [math.tanh(v) for v in x[count:]]
    for i in reversed(range(count)):
        value[i] = (.5*(value[2*i+1]+value[2*i+2]) +
                    p.h*p.beta*math.tanh(x[i])) / (1+p.lam*p.h)
    return value[:count]


def residual_report(p, x0, y):
    """No tiny-update shortcut: re-evaluate the original global fixed-point map."""
    mapped = global_map(p, x0, y)
    r = max(abs(a-b) for a, b in zip(y, mapped))
    x = forward(p, x0, y)
    full_y = list(y) + [math.tanh(v) for v in x[len(y):]]
    z = [(full_y[2*i+2]-full_y[2*i+1])/(2*math.sqrt(p.h)) for i in range(len(y))]
    f = [p.beta*math.tanh(x[i])-p.lam*y[i] for i in range(len(y))]
    # Local BSDE residual, not generally equal to the full-map residual off solution.
    local = [abs(full_y[2*i+1+bit]-y[i]+p.h*f[i] -
                 z[i]*math.sqrt(p.h)*(2*bit-1)) for i in range(len(y)) for bit in (0, 1)]
    error = r / (1-p.q)
    return {'fixed_point_residual': r, 'max_local_bsde_residual': max(local),
            'global_q_bound': p.q, 'y_error_bound_exact_arithmetic': error,
            'x_error_bound_exact_arithmetic': p.a*p.horizon*error,
            'z_error_bound_exact_arithmetic': max(1, p.a*p.horizon)*error/math.sqrt(p.h),
            'max_abs_generator': max(map(abs, f)), 'max_abs_z': max(map(abs, z)),
            'float_roundoff_rigorously_enclosed': False,
            'bound_target': 'unique_solution_of_this_complete_binary_discrete_system',
            'continuous_time_error_bounded': False, 'production_promotion_permitted': False}


def solve_global(p, x0, *, initial=None, tolerance=1e-10, max_iterations=256):
    _initial(p, x0)
    require(type(tolerance) in (float, int) and math.isfinite(tolerance) and
            1e-13 <= tolerance <= 1e-2, 'registered solver tolerance')
    require(type(max_iterations) is int and 1 <= max_iterations <= 1000, 'bounded iteration budget')
    y = [0.]*(2**p.steps-1) if initial is None else list(initial)
    _vector(y, 2**p.steps-1)
    history = []
    for iteration in range(max_iterations):
        candidate = global_map(p, x0, y)
        r = max(abs(a-b) for a, b in zip(y, candidate))
        history.append(r)
        if r/(1-p.q) <= tolerance:
            return {'y': y, 'x': forward(p, x0, y), 'map_calls': iteration+1,
                    'residual_history': history, 'report': residual_report(p, x0, y)}
        y = candidate
    raise ValueError('coupled iteration budget exhausted; no converged result')


def _interpolate(grid, values, x):
    require(math.isfinite(x) and grid[0]-1e-12 <= x <= grid[-1]+1e-12,
            'continuation field domain exhausted; no extrapolation')
    # Clamp only endpoint arithmetic roundoff, never a missing state domain.
    x = min(grid[-1], max(grid[0], x))
    i = min(len(grid)-2, max(0, bisect_right(grid, x)-1))
    weight = (x-grid[i])/(grid[i+1]-grid[i])
    return values[i]*(1-weight)+values[i+1]*weight


def continuation_fields(p, spacing, *, reset_at=()):
    """Locally solve y=E[u_next(x+a*h*y+noise)]+h*f, passing the SAME suffix field.

    reset_at deliberately supplies tanh instead of the suffix for the negative
    control. Its output is NOT marked a consistent global solution.
    """
    p.validate()
    require(type(spacing) in (float, int) and math.isfinite(spacing) and .001 <= spacing <= 1,
            'bounded field-grid spacing')
    require(type(reset_at) is tuple and len(set(reset_at)) == len(reset_at) and
            all(type(k) is int and 0 < k < p.steps for k in reset_at), 'interior reset inventory')
    increment = p.a*p.y_bound*p.h + p.sigma*math.sqrt(p.h)
    grids = []
    for k in range(p.steps+1):
        radius = p.radius+k*increment
        cells = math.ceil(2*radius/spacing)
        grids.append([-radius+2*radius*j/cells for j in range(cells+1)])
    require(sum(map(len, grids)) <= 200_000, 'field allocation budget')
    values = [None]*p.steps + [[math.tanh(v) for v in grids[-1]]]
    lipschitz = [0.]*p.steps + [1.]
    local_calls = []
    for k in reversed(range(p.steps)):
        reset = k+1 in reset_at
        next_values = [math.tanh(x) for x in grids[k+1]] if reset else values[k+1]
        next_lip = 1. if reset else lipschitz[k+1]
        denom = 1+p.lam*p.h-p.a*p.h*next_lip
        require(denom > 1e-6, 'continuation Lipschitz bound lost')
        lipschitz[k] = (next_lip+p.beta*p.h)/denom
        qlocal = p.a*p.h*next_lip/(1+p.lam*p.h)
        y = [0.]*len(grids[k])
        for calls in range(1, 257):
            new = []
            for x, yi in zip(grids[k], y):
                center = x+p.a*p.h*yi
                pair = [_interpolate(grids[k+1], next_values, center+s*p.sigma*math.sqrt(p.h))
                        for s in (-1, 1)]
                new.append((sum(pair)/2+p.h*p.beta*math.tanh(x))/(1+p.lam*p.h))
            residual = max(abs(a-b) for a, b in zip(new, y))
            y = new
            if residual/(1-qlocal) <= 1e-12:
                break
        else:
            raise ValueError('local continuation solve budget exhausted')
        measured_lip = max(abs(b-a)/(v-u) for a, b, u, v in
                           zip(y, y[1:], grids[k], grids[k][1:]))
        require(measured_lip <= lipschitz[k]+1e-9, 'field violates analytic Lipschitz envelope')
        values[k] = y
        local_calls.append({'level': k, 'iterations': calls, 'residual': residual,
                            'qlocal_bound': qlocal, 'lip_bound': lipschitz[k],
                            'measured_grid_lip': measured_lip, 'terminal_reset': reset})
    return {'profile': asdict(p), 'grids': grids, 'values': values,
            'reset_at': list(reset_at), 'local_solves': local_calls}


def trace_fields(p, x0, fields):
    _initial(p, x0)
    require(fields['profile'] == asdict(p), 'field/solver coefficient identity mismatch')
    count = 2**p.steps-1
    x, y, jumps = [0.]*(2*count+1), [], []
    x[0] = float(x0)
    for i in range(count):
        k = (i+1).bit_length()-1
        value = _interpolate(fields['grids'][k], fields['values'][k], x[i])
        y.append(value)
        if k in fields['reset_at']:
            jumps.append(abs(math.tanh(x[i])-value))
        center = x[i]+p.a*p.h*value
        x[2*i+1], x[2*i+2] = [center+s*p.sigma*math.sqrt(p.h) for s in (-1, 1)]
    return {'y': y, 'x': x, 'max_reset_interface_jump': max(jumps, default=0.),
            'report': residual_report(p, x0, y)}
