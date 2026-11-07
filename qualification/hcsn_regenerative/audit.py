"""Independent density-integral and backward-PDE checks for fixed regeneration.

The oracles below do not import the production first-passage or renewal code.
The PDE discretizes L=mu*d_x+sigma**2/2*d_xx with a physical delayed boundary.
It is a bounded-domain approximation: its grid/domain errors must be measured.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad
from scipy.sparse import diags
from scipy.sparse.linalg import splu


@dataclass(frozen=True)
class IntegralResult:
    value: float
    absolute_error: float
    log_absolute_value: float


def hit_integral(x, horizon, mu, sigma, discount=0.0, derivative=None):
    """Integrate the inverse-Gaussian density, including its separate x=0 atom.

    z=x/(sigma*sqrt(t)) removes the t=0 singularity. Exponent rescaling preserves
    relative tail precision. Parameter derivatives integrate the density score
    at fixed physical time, rather than differentiating a candidate CDF.
    """
    if x < 0 or horizon < 0 or sigma <= 0 or discount < 0:
        raise ValueError("invalid first-passage domain")
    if derivative not in (None, "x", "mu", "sigma", "discount"):
        raise ValueError("unknown density derivative")
    if x == 0:
        if derivative == "x":
            raise ValueError("the boundary atom requires a separate right-limit audit")
        value = 1.0 if derivative is None else 0.0
        return IntegralResult(value, 0.0, 0.0 if value else -math.inf)
    if horizon == 0:
        return IntegralResult(0.0, 0.0, -math.inf)
    lower = x / (sigma * math.sqrt(horizon))
    kappa = mu * x / sigma**2
    time_scale = (x / sigma)**2
    peak = (kappa**2 + 2 * discount * time_scale)**0.25

    def exponent(z):
        if z == 0:
            return 0.0 if kappa == 0 and discount == 0 else -math.inf
        return -0.5 * (z + kappa / z)**2 - discount * time_scale / z**2

    mode = max(lower, peak)
    log_scale = exponent(mode)

    def integrand(z):
        power = exponent(z) - log_scale
        if power < -745:
            return 0.0
        weight = math.exp(power)
        if derivative is None:
            return weight
        time = time_scale / z**2
        shifted = x + mu * time
        score = {"x": lambda: 1 / x - shifted / (sigma**2 * time),
                 "mu": lambda: -shifted / sigma**2,
                 "sigma": lambda: -1 / sigma + shifted**2 / (sigma**3 * time),
                 "discount": lambda: -time}[derivative]()
        return weight * score

    # Explicitly visit narrow low-noise peaks and Gaussian boundary tails.
    points = sorted({lower, max(lower, mode - 12), mode,
                     mode + 10 / max(mode, 1), mode + 12}) + [math.inf]
    pieces = [quad(integrand, lo, hi, epsabs=2e-12, epsrel=2e-12, limit=250)
              for lo, hi in zip(points[:-1], points[1:]) if hi > lo]
    integral = math.fsum(p[0] for p in pieces) * math.sqrt(2 / math.pi)
    error = math.fsum(p[1] for p in pieces) * math.sqrt(2 / math.pi)
    log_abs = log_scale + math.log(abs(integral)) if integral else -math.inf
    value = math.copysign(math.exp(log_abs), integral) if log_abs > -746 else 0.0
    absolute_error = math.exp(log_scale) * error if log_scale > -746 else 0.0
    return IntegralResult(value, absolute_error, log_abs)


def survivor_integral(x, horizon, mu, sigma, lower=0.0, upper=math.inf):
    """Integrate the positive killed density; do not subtract two CDFs."""
    if x < 0 or horizon < 0 or sigma <= 0 or lower < 0 or upper <= lower:
        raise ValueError("invalid survivor interval")
    if x == 0:
        return 0.0
    if horizon == 0:
        return float(lower <= x < upper)
    scale = sigma * math.sqrt(horizon)
    mean = x + mu * horizon
    start, end = (lower - mean) / scale, (upper - mean) / scale

    def integrand(z):
        y = max(0.0, mean + scale * z)
        return (math.exp(-0.5 * z*z) / math.sqrt(2 * math.pi)
                * -math.expm1(-2 * x * y / scale**2))

    cuts = [start] + [v for v in (-12.0, 0.0, 12.0) if start < v < end] + [end]
    return math.fsum(quad(integrand, lo, hi, epsabs=2e-13, epsrel=2e-12,
                         limit=200)[0] for lo, hi in zip(cuts[:-1], cuts[1:]))


@dataclass(frozen=True)
class PDEResult:
    single_cycle: float
    regenerative: float
    single_slope: float
    regenerative_slope: float
    space_step: float
    time_step: float
    space_intervals: int
    time_intervals: int
    domain: float
    drift_scheme: str
    upper_boundary_hit_probability: float


def pde_value(x, horizon, mu, sigma, discount, margin, refractory=0.0,
              hit_reward=1.0, active_reward=0.0, terminal_reward=0.0,
              *, space_step=0.005, time_step=0.002, domain=3.0):
    """Backward Euler with separate killed E and delayed, nonlocal-boundary U.

    U(T,0)=h+exp(-q*d) U(T-d,margin) for T>=d; otherwise U(T,0)=h.
    Terminal payoff is paid only in active states, including exact release time.
    Space refinement and domain expansion remain necessary even when it solves.
    """
    if not (0 <= x <= domain and horizon >= 0 and sigma > 0 and discount >= 0
            and margin > 0 and refractory >= 0 and space_step > 0 and time_step > 0):
        raise ValueError("invalid PDE domain")
    nx = math.ceil(domain / space_step)
    dx = domain / nx
    if nx < 4 or not dx <= margin <= domain - dx:
        raise ValueError("reset must be resolved strictly inside the spatial domain")
    nt = math.ceil(horizon / time_step) if horizon else 0
    dt = horizon / nt if nt else 0.0
    grid = np.linspace(0, domain, nx + 1)
    e = np.full(nx + 1, terminal_reward, dtype=float)
    u = e.copy()
    e[0] = hit_reward
    u[0] = hit_reward + (terminal_reward if refractory == 0 else 0)
    coefficient = sigma**2 / (2 * dx**2)
    left, right = coefficient - mu / (2 * dx), coefficient + mu / (2 * dx)
    scheme = "central"
    if min(left, right) < 0:
        left, right = coefficient + max(-mu, 0) / dx, coefficient + max(mu, 0) / dx
        scheme = "monotone_upwind"
    if nt:
        reset_cell = min(nx - 2, max(1, int(margin / dx)))
        reset_fraction = margin / dx - reset_cell
        reset_indices = [reset_cell, reset_cell + 1]
        reset_weights = [1 - reset_fraction, reset_fraction]
        reset_at = lambda v: sum(w * v[j] for w, j in zip(reset_weights, reset_indices))
        diagonal = np.full(nx - 1, 1 + dt * (left + right + discount))
        base = diags([-dt * left * np.ones(nx - 2), diagonal,
                      -dt * right * np.ones(nx - 2)], [-1, 0, 1], format="csc")
        killed_solve = splu(base).solve
        delayed = base.tolil()
        current_weight = max(0.0, 1 - refractory / dt)
        release_discount = math.exp(-discount * refractory)
        for weight, index in zip(reset_weights, reset_indices):
            delayed[0, index - 1] -= dt * left * release_discount * current_weight * weight
        renewal_solve = splu(delayed.tocsc()).solve
        history = np.zeros(nt + 1)
        history[0] = terminal_reward
        for n in range(1, nt + 1):
            time = n * dt
            active_time = time if discount == 0 else -math.expm1(-discount * time) / discount
            upper = active_reward * active_time + terminal_reward * math.exp(-discount * time)
            e_rhs = e[1:-1] + dt * active_reward
            e_rhs[0] += dt * left * hit_reward
            e_rhs[-1] += dt * right * upper
            e[1:-1] = killed_solve(e_rhs)
            e[-1] = upper
            delay_index = n - refractory / dt
            past = 0.0
            released = delay_index >= -1e-12
            if released:
                delay_index = max(0.0, delay_index)
                nearest = round(delay_index)
                if abs(delay_index - nearest) < 1e-10:
                    delay_index = float(nearest)
                lo = math.floor(delay_index)
                frac = delay_index - lo
                if lo < n:
                    past += (1 - frac) * history[lo]
                if lo + 1 < n:
                    past += frac * history[lo + 1]
            u_rhs = u[1:-1] + dt * active_reward
            u_rhs[0] += dt * left * (hit_reward + release_discount * past)
            u_rhs[-1] += dt * right * upper
            u[1:-1] = renewal_solve(u_rhs)
            u[-1] = upper
            history[n] = reset_at(u)
            u[0] = hit_reward + (release_discount * (past + current_weight * history[n])
                                  if released else 0.0)
    slopes_e, slopes_u = np.gradient(e, dx, edge_order=2), np.gradient(u, dx, edge_order=2)
    return PDEResult(float(np.interp(x, grid, e)), float(np.interp(x, grid, u)),
                     float(np.interp(x, grid, slopes_e)), float(np.interp(x, grid, slopes_u)),
                     dx, dt, nx, nt, domain, scheme,
                     hit_integral(domain, horizon, mu, sigma).value)


def five_point_derivative(function, point, step):
    """Function sensitivity; this does not certify an autodiff implementation."""
    if step <= 0:
        raise ValueError("step must be positive")
    return (function(point - 2*step) - 8*function(point - step)
            + 8*function(point + step) - function(point + 2*step)) / (12*step)


@dataclass(frozen=True)
class StationaryPDEResult:
    single_cycle: float
    regenerative: float
    single_slope: float
    regenerative_slope: float
    space_step: float
    domain: float
    drift_scheme: str


def stationary_hx_pde(par, boundary, margin, refractory, hit_reward, x,
                      *, space_step=0.01, domain=6.0):
    """Independent FD resolvent conditional on a supplied fixed HX boundary.

    Debt cashflow is reconstructed from positive-density integrals, and B*exp(x)
    is subtracted analytically to leave a bounded source and stable far boundary.
    This audits value at the supplied boundary, not regenerative optimal stopping.
    """
    if not (0 <= x <= domain and par.r > 0 and boundary > 0 and refractory >= 0
            and par.sigma > 0 and space_step > 0):
        raise ValueError("invalid stationary audit domain")
    nx = math.ceil(domain / space_step)
    dx = domain / nx
    if nx < 4 or not dx <= margin <= domain - dx:
        raise ValueError("reset must be strictly resolved inside the spatial domain")
    grid = np.linspace(0, domain, nx + 1)
    mu, sigma, q_debt = par.r - par.delta - par.sigma**2 / 2, par.sigma, par.r + par.ell
    coupon, face = par.coupon / par.maturity, par.principal / par.maturity
    recovery = par.recovery * boundary / par.maturity
    debt = []
    for distance in grid[1:-1]:
        f = hit_integral(distance, par.maturity, mu, sigma).value
        g = hit_integral(distance, par.maturity, mu, sigma, q_debt).value
        debt.append(coupon / q_debt * (1 - g)
                    + math.exp(-q_debt * par.maturity) * (face - coupon / q_debt) * (1 - f)
                    + recovery * g)
    bounded_flow = -(1 - par.tax) * par.coupon + np.array(debt) - face
    flow_at_infinity = (-(1 - par.tax) * par.coupon + coupon / q_debt
                        + math.exp(-q_debt * par.maturity) * (face - coupon / q_debt) - face)
    upper = flow_at_infinity / par.r
    diffusion = sigma**2 / (2 * dx**2)
    left, right = diffusion - mu / (2 * dx), diffusion + mu / (2 * dx)
    scheme = "central"
    if min(left, right) < 0:
        left, right = diffusion + max(-mu, 0) / dx, diffusion + max(mu, 0) / dx
        scheme = "monotone_upwind"
    matrix = diags([-left * np.ones(nx - 2),
                    np.full(nx - 1, left + right + par.r), -right * np.ones(nx - 2)],
                   [-1, 0, 1], format="csc")
    e_rhs = bounded_flow.copy()
    e_rhs[0] += left * -boundary
    e_rhs[-1] += right * upper
    e = np.concatenate(([-boundary], splu(matrix).solve(e_rhs), [upper]))
    reset_cell = min(nx - 2, max(1, int(margin / dx)))
    fraction = margin / dx - reset_cell
    factor = math.exp(-par.r * refractory)
    regeneration = matrix.tolil()
    regeneration[0, reset_cell - 1] -= left * factor * (1 - fraction)
    regeneration[0, reset_cell] -= left * factor * fraction
    boundary_constant = hit_reward - boundary + factor * boundary * math.exp(margin)
    u_rhs = bounded_flow.copy()
    u_rhs[0] += left * boundary_constant
    u_rhs[-1] += right * upper
    u = np.concatenate(([0.0], splu(regeneration.tocsc()).solve(u_rhs), [upper]))
    u[0] = boundary_constant + factor * ((1 - fraction) * u[reset_cell] + fraction * u[reset_cell + 1])
    source_particular = boundary * np.exp(grid)
    e_slope = np.gradient(e, dx, edge_order=2) + source_particular
    u_slope = np.gradient(u, dx, edge_order=2) + source_particular
    return StationaryPDEResult(float(np.interp(x, grid, e + source_particular)),
                               float(np.interp(x, grid, u + source_particular)),
                               float(np.interp(x, grid, e_slope)),
                               float(np.interp(x, grid, u_slope)), dx, domain, scheme)
