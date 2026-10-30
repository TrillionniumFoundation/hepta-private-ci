"""C1 free-boundary gates and continuous/fixed-step neuron dynamics.

This preserves the preceding feasibility model and adds explicit recurrent
coupling. It is a newly designed neural system, not the He--Xiong financial
state process. q is a normalized abandonment-put activation, not a probability.
"""

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq


@dataclass(frozen=True)
class Parameters:
    leak: float = 1.0
    call_gain: float = 1.0
    regen_gain: float = 4.0
    recovery_gain: float = 6.0
    recovery_time: float = 5.0

    def validate(self):
        assert self.leak > 0 and self.recovery_time > 0
        assert self.recovery_gain >= 0
        assert all(np.isfinite(x) for x in self.__dict__.values())


def gates(x):
    """Return q, a, q', a' in a numerically bounded representation.

    q=.5 exp(x) for x<0, 1-.5 exp(-x) otherwise.
    a=C/(B+C)=1-sech(x) for x<0, zero otherwise.
    The model has beta=-1 and the danger coordinate x=log(b/V).
    """
    x = np.asarray(x)
    e = np.exp(-np.abs(x))
    q = np.where(x < 0, .5*e, 1-.5*e)
    dq = .5*e
    sech = 2*e/(1+e*e)
    a = np.where(x < 0, 1-sech, 0.)
    da = np.where(x < 0, sech*np.tanh(x), 0.)
    return q, a, dq, da


def rhs(t, state, p, coupling, input_fn):
    n = len(state)//2
    x, y = state[:n], state[n:]
    q, a, _, _ = gates(x)
    dx = (-p.leak*x+p.call_gain*a+p.regen_gain*q-y
          +coupling@(q-.5)+input_fn(t))
    dy = (p.recovery_gain*q-y)/p.recovery_time
    return np.concatenate((dx, dy))


def jacobian(state, p, coupling):
    n = len(state)//2
    dq, da = gates(state[:n])[2:]
    xx = np.diag(-p.leak+p.call_gain*da+p.regen_gain*dq)+coupling*dq[None, :]
    xy = -np.eye(n)
    yx = np.diag(p.recovery_gain*dq/p.recovery_time)
    yy = -np.eye(n)/p.recovery_time
    return np.block([[xx, xy], [yx, yy]])


def bounds(initial, p, coupling, input_abs_bound):
    """Rigorous componentwise sup bounds for the CONTINUOUS ODE.

    Finite W, bounded input, leak>0, tau>0 suffice; no small-gain condition is
    required for boundedness because all nonlinear signals are bounded.
    This does not imply contraction, uniqueness of an attractor or good gradients.
    """
    p.validate()
    initial = np.asarray(initial)
    n = len(initial)//2
    y_bound = np.maximum(np.abs(initial[n:]), p.recovery_gain)
    forcing = (abs(p.call_gain)+abs(p.regen_gain)+y_bound
               +np.asarray(input_abs_bound)+.5*np.sum(np.abs(coupling), axis=1))
    x_bound = np.maximum(np.abs(initial[:n]), forcing/p.leak)
    return np.concatenate((x_bound, y_bound))


def contraction_certificate(p, coupling, recovery_weight):
    """Sufficient continuous-time contraction condition in weighted max norm.

    Norm=max(||dx||_inf, recovery_weight*||dy||_inf). The nonpositive a'
    improves the logarithmic norm when call_gain>=0. A positive certificate
    forbids autonomous nontrivial periodic orbits under constant input, so it
    deliberately describes a stable alternative, not the excitable baseline.
    """
    p.validate()
    assert p.call_gain >= 0 and recovery_weight > 0
    row_bound = float(np.max(np.sum(np.abs(coupling), axis=1)))
    x_margin = p.leak-.5*(abs(p.regen_gain)+row_bound)-1/recovery_weight
    y_margin = (1-.5*recovery_weight*p.recovery_gain)/p.recovery_time
    rate = min(x_margin, y_margin)
    return dict(weight=recovery_weight, row_l1_bound=row_bound,
                x_margin=x_margin, y_margin=y_margin,
                contraction_rate=rate, certified=bool(rate > 0))


def equilibria(current, p):
    """Enumerate scalar roots in a provably adequate finite bracket."""
    span = (abs(p.call_gain)+abs(p.regen_gain-p.recovery_gain)+abs(current))/p.leak+2
    xs = np.linspace(-span, span, 2001)

    def fn(x):
        q, a, _, _ = gates(x)
        return -p.leak*x+p.call_gain*a+(p.regen_gain-p.recovery_gain)*q+current

    vals = fn(xs)
    roots = []
    for i in range(len(xs)-1):
        if vals[i] == 0:
            roots.append(xs[i])
        if vals[i]*vals[i+1] < 0:
            roots.append(brentq(fn, xs[i], xs[i+1], xtol=1e-13))
    roots = sorted(set(round(float(x), 12) for x in roots))
    return [np.array([x, p.recovery_gain*gates(x)[0]]) for x in roots]


def reference(initial, p, coupling, input_fn, duration, sample=.02, tight=False):
    times = np.linspace(0, duration, round(duration/sample)+1)
    sol = solve_ivp(lambda t, s: rhs(t, s, p, coupling, input_fn), (0, duration),
                    initial, t_eval=times, method="DOP853",
                    rtol=1e-11 if tight else 1e-9,
                    atol=1e-13 if tight else 1e-11,
                    max_step=.025 if tight else .2)
    if not sol.success:
        raise RuntimeError(sol.message)
    return times, sol.y.T


def fixed_step(initial, p, coupling, input_fn, duration, dt, method="euler", dtype=np.float64):
    """The exponential method freezes all nonlinear gates and cross-state terms.

    It is NOT the exact flow of the coupled ODE. It preserves the same invariant
    magnitude bounds for arbitrary dt>0. Euler does so for dt<=min(1/leak,tau).
    """
    n = len(initial)//2
    steps = round(duration/dt)
    times = np.arange(steps+1)*dt
    state = np.asarray(initial, dtype=dtype)
    trajectory = np.empty((steps+1, 2*n), dtype=dtype)
    trajectory[0] = state
    w = np.asarray(coupling, dtype=dtype)
    step = dtype(dt)

    def f(t, s):
        return np.asarray(rhs(t, s, p, w, input_fn), dtype=dtype)

    for k in range(steps):
        t = times[k]
        if method == "euler":
            state = state+step*f(t, state)
        elif method == "rk4":
            k1 = f(t, state)
            k2 = f(t+dt/2, state+step*k1/2)
            k3 = f(t+dt/2, state+step*k2/2)
            k4 = f(t+dt, state+step*k3)
            state = state+step*(k1+2*k2+2*k3+k4)/6
        elif method == "exponential":
            x, y = state[:n], state[n:]
            q, a, _, _ = gates(x)
            ex = dtype(np.exp(-p.leak*dt))
            ey = dtype(np.exp(-dt/p.recovery_time))
            forcing = (p.call_gain*a+p.regen_gain*q-y+w@(q-.5)+input_fn(t))
            xn = ex*x+dtype(-np.expm1(-p.leak*dt)/p.leak)*forcing
            yn = ey*y+dtype(-np.expm1(-dt/p.recovery_time))*p.recovery_gain*q
            state = np.asarray(np.concatenate((xn, yn)), dtype=dtype)
        else:
            raise ValueError(method)
        trajectory[k+1] = state
    return times, trajectory


def upward_crossings(times, values, level=0.):
    idx = np.where((values[:-1] < level) & (values[1:] >= level))[0]
    return [float(times[i]+(level-values[i])/(values[i+1]-values[i])*(times[i+1]-times[i])) for i in idx]
