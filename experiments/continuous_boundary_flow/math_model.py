"""Finite-horizon maintenance task using the repository's exact ABM kernels.

B=0 is physical failure; a policy's maintenance boundary is a different object.
A failure pays its cost at the exact first-passage time, stops production for the
rest of that decision window, and reinjects at failure_reset next window. An
active maintenance action pays at the window start and then runs the same
physical dynamics from maintenance_reset. There is at most one active action
per window. The finite state grid and decision windows are declared numerical
approximations; this is not a closed-form He--Xiong equilibrium.
"""

from dataclasses import asdict, dataclass

import numpy as np
from numpy.polynomial.legendre import leggauss

from experiments.first_passage_cell.kernels import (
    first_passage,
    first_passage_gradients,
    killed_cdf,
    killed_density,
)


@dataclass(frozen=True)
class TaskSpec:
    mu: float = -0.22
    sigma: float = 0.42
    dt: float = 0.5
    horizon: int = 16
    discount: float = 0.06
    production_rate: float = 1.0
    failure_cost: float = 2.4
    maintenance_cost: float = 0.38
    maintenance_reset: float = 1.35
    failure_reset: float = 0.95
    initial: float = 1.1

    def __post_init__(self):
        vals = np.asarray(list(asdict(self).values()), dtype=float)
        if not np.isfinite(vals).all():
            raise ValueError("Task parameters must be finite")
        if self.sigma <= 0 or self.dt <= 0 or self.horizon < 1:
            raise ValueError("Positive noise, window and horizon are required")
        if not isinstance(self.horizon, int):
            raise ValueError("Horizon must be an integer")
        if (
            min(
                self.discount,
                self.production_rate,
                self.failure_cost,
                self.maintenance_cost,
            )
            < 0
        ):
            raise ValueError("Discount and costs must be nonnegative")
        if min(self.maintenance_reset, self.failure_reset, self.initial) <= 0:
            raise ValueError("Reset and initial states must exceed physical B=0")


@dataclass
class GridModel:
    spec: TaskSpec
    x: np.ndarray
    killed: np.ndarray
    F: np.ndarray
    S: np.ndarray
    f: np.ndarray
    H: np.ndarray
    occupation: np.ndarray
    transition: np.ndarray
    reward: np.ndarray
    maintenance_distribution: np.ndarray
    failure_distribution: np.ndarray
    initial_distribution: np.ndarray
    maintenance_transition: np.ndarray
    maintenance_reward: float
    upper_tail: np.ndarray
    x_max: float
    diagnostics: dict

    @property
    def gamma(self):
        return float(np.exp(-self.spec.discount * self.spec.dt))

    @property
    def n_states(self):
        return self.x.size


def point_distribution(x, point):
    """Linear mass interpolation; outer half-cells use their nearest center."""
    x = np.asarray(x, dtype=float)
    if not np.isfinite(point) or point <= 0:
        raise ValueError("Point must be finite and strictly positive")
    out = np.zeros(x.size)
    hi = int(np.searchsorted(x, point))
    if hi == 0:
        out[0] = 1.0
    elif hi == x.size:
        out[-1] = 1.0
    else:
        w = (point - x[hi - 1]) / (x[hi] - x[hi - 1])
        out[hi - 1], out[hi] = 1.0 - w, w
    return out


def occupation_time(x, spec):
    """E[integral_0^min(tau,dt) exp(-q t)dt], including the q=0 limit."""
    p = first_passage(x, spec.mu, spec.sigma, spec.dt, spec.discount)
    if spec.discount < 1e-6:
        g = first_passage_gradients(x, spec.mu, spec.sigma, spec.dt, 0.0)
        out = spec.dt * p["S"] - g["H"]["discount"]
        if spec.discount:
            nodes, weights = leggauss(48)
            t = spec.dt * (nodes + 1) / 2
            surv = first_passage(np.asarray(x)[..., None], spec.mu, spec.sigma, t)["S"]
            out = (surv * np.exp(-spec.discount * t)) @ (weights * spec.dt / 2)
    else:
        out = (1.0 - np.exp(-spec.discount * spec.dt) * p["S"] - p["H"]) / spec.discount
    return np.maximum(out, 0.0)


def build_model(spec=None, n_grid=96, x_max=4.8, quadrature_order=8):
    """Conservative finite-volume kernel; last bin contains the upper tail.

    Each finite bin integrates the existing killed_density K_t by Gauss--
    Legendre quadrature. The final bin receives the analytically known S mass
    minus the finite-bin mass. This never renormalizes away physical failure.
    """
    spec = spec or TaskSpec()
    if (
        n_grid < 8
        or x_max <= max(spec.initial, spec.maintenance_reset, spec.failure_reset)
        or quadrature_order < 4
    ):
        raise ValueError("Insufficient grid, upper domain or quadrature")
    dx = x_max / n_grid
    x = (np.arange(n_grid) + 0.5) * dx
    nodes, weights = leggauss(quadrature_order)
    y = (np.arange(n_grid - 1)[:, None] + (nodes + 1) / 2) * dx
    density = killed_density(
        x[:, None, None], y[None, :, :], spec.mu, spec.sigma, spec.dt
    )
    finite = density @ (weights * dx / 2)
    p = first_passage(x, spec.mu, spec.sigma, spec.dt, spec.discount)
    residual = p["S"] - finite.sum(axis=1)
    if residual.min() < -2e-11:
        raise ValueError("K_t quadrature loses positivity; refine grid/quadrature")
    killed = np.column_stack((finite, np.maximum(residual, 0.0)))
    failure_dist = point_distribution(x, spec.failure_reset)
    maintenance_dist = point_distribution(x, spec.maintenance_reset)
    initial_dist = point_distribution(x, spec.initial)
    transition = killed + p["F"][:, None] * failure_dist[None, :]
    occupation = occupation_time(x, spec)
    reward = spec.production_rate * occupation - spec.failure_cost * p["H"]
    upper_tail = p["S"] - killed_cdf(x, x_max, spec.mu, spec.sigma, spec.dt)
    return GridModel(
        spec,
        x,
        killed,
        p["F"],
        p["S"],
        p["f"],
        p["H"],
        occupation,
        transition,
        reward,
        maintenance_dist,
        failure_dist,
        initial_dist,
        maintenance_dist @ transition,
        float(maintenance_dist @ reward - spec.maintenance_cost),
        np.maximum(upper_tail, 0),
        x_max,
        {
            "mass_error": float(np.max(np.abs(transition.sum(axis=1) - 1))),
            "min_transition": float(transition.min()),
            "quadrature_order": quadrature_order,
            "dx": dx,
            "kernel": "experiments.first_passage_cell.kernels",
            "reset_rule": "failure refractory until next decision tick",
        },
    )


def action_values(model, continuation):
    """Same reward/continuation for all controllers, including future resets."""
    continuation = np.asarray(continuation, dtype=float)
    if continuation.shape != model.x.shape or not np.isfinite(continuation).all():
        raise ValueError("A finite continuation value for every grid state is required")
    keep = model.reward + model.gamma * (model.transition @ continuation)
    reset = model.maintenance_reward + model.gamma * (
        model.maintenance_transition @ continuation
    )
    return keep, np.full(model.n_states, reset), np.zeros(model.n_states)


def boundary_from_advantage(x, advantage):
    """Numerical value-matching boundary; report failures of threshold shape.

    Decisions occur only at the declared time grid: continuous-time smooth fit
    is not imposed or claimed. A root is linearly interpolated between nodes.
    """
    advantage = np.asarray(advantage)
    positive = advantage > 0
    crossings = np.flatnonzero(positive[:-1] != positive[1:])
    monotone = bool(not np.any(np.diff(positive.astype(int)) > 0))
    if not positive.any():
        boundary, residual = 0.0, 0.0
    elif positive.all():
        boundary, residual = float(x[-1]), float(advantage[-1])
    elif monotone:
        i = int(crossings[0])
        frac = advantage[i] / (advantage[i] - advantage[i + 1])
        boundary = float(x[i] + frac * (x[i + 1] - x[i]))
        residual = float((1 - frac) * advantage[i] + frac * advantage[i + 1])
    else:
        boundary, residual = None, None
    return {
        "boundary": boundary,
        "value_matching_residual": residual,
        "threshold_shape": monotone,
        "switches": int(crossings.size),
    }


def solve_dp(model, horizon=None):
    """Full-information Bellman upper bound, never a hidden training label."""
    n = model.spec.horizon if horizon is None else horizon
    value = np.zeros((n + 1, model.n_states))
    q_all = np.zeros((n, model.n_states, 3))
    policy = np.zeros_like(q_all)
    boundaries = []
    for remaining in range(1, n + 1):
        q = np.stack(action_values(model, value[remaining - 1]), axis=-1)
        q_all[remaining - 1] = q
        action = np.argmax(q, axis=-1)
        policy[remaining - 1] = np.eye(3)[action]
        value[remaining] = np.max(q, axis=-1)
        item = boundary_from_advantage(model.x, q[:, 1] - np.maximum(q[:, 0], q[:, 2]))
        item["stop_states"] = int(np.sum(action == 2))
        boundaries.append(item)
    return {
        "x": model.x.copy(),
        "value": value,
        "q_keep": q_all[..., 0],
        "q_reset": q_all[..., 1],
        "q_stop": q_all[..., 2],
        "q": q_all,
        "policy": policy,
        "boundaries": boundaries,
        "initial_value": float(model.initial_distribution @ value[n]),
    }


def _policy_array(model, policy, horizon=None):
    n = model.spec.horizon if horizon is None else horizon
    out = np.asarray(policy, dtype=float)
    if out.shape == model.x.shape:
        out = np.broadcast_to(out, (n, model.n_states))
    if out.shape == (n, model.n_states):
        out = np.stack((1 - out, out, np.zeros_like(out)), axis=-1)
    if (
        out.shape != (n, model.n_states, 3)
        or not np.isfinite(out).all()
        or np.any(out < 0)
        or np.any(out > 1)
        or np.max(np.abs(out.sum(axis=-1) - 1)) > 1e-10
    ):
        raise ValueError(
            "Policy shape (remaining_steps,states,3), actions wait/repair/stop"
        )
    return out


def evaluate_policy(model, policy, horizon=None):
    """Continuous probability flow and exact expected ledger on the grid.

    Fractional action weights split mass; they never average physical states.
    Array index remaining-1 is shared with solve_dp and sample_policy.
    """
    policy = _policy_array(model, policy, horizon)
    n = policy.shape[0]
    distribution = model.initial_distribution.copy()
    occupations = [distribution.copy()]
    production = failure_cost = maintenance_cost = failures = maintenance = tail = 0.0
    stopped = 0.0
    stopped_mass = [0.0]
    for elapsed in range(n):
        gate = policy[n - elapsed - 1]
        keep_mass = distribution * gate[:, 0]
        reset_mass = float(distribution @ gate[:, 1])
        stopped += float(distribution @ gate[:, 2])
        source = keep_mass + reset_mass * model.maintenance_distribution
        discount = model.gamma**elapsed
        production += (
            discount * model.spec.production_rate * float(source @ model.occupation)
        )
        failure_cost += discount * model.spec.failure_cost * float(source @ model.H)
        maintenance_cost += discount * reset_mass * model.spec.maintenance_cost
        failures += float(source @ model.F)
        maintenance += reset_mass
        tail += float(source @ model.upper_tail)
        distribution = (
            keep_mass @ model.transition + reset_mass * model.maintenance_transition
        )
        occupations.append(distribution.copy())
        stopped_mass.append(stopped)
    value = np.zeros((n + 1, model.n_states))
    for remaining in range(1, n + 1):
        q = np.stack(action_values(model, value[remaining - 1]), axis=-1)
        value[remaining] = np.sum(policy[remaining - 1] * q, axis=-1)
    total = production - failure_cost - maintenance_cost
    backward = float(model.initial_distribution @ value[n])
    return {
        "utility": total,
        "production": production,
        "failure_cost": failure_cost,
        "maintenance_cost": maintenance_cost,
        "failures": failures,
        "maintenance": maintenance,
        "stopped_probability": stopped,
        "upper_tail_visits": tail,
        "occupancy": np.asarray(occupations),
        "stopped_mass": np.asarray(stopped_mass),
        "value": value,
        "flow_backward_residual": abs(total - backward),
        "mass_error": float(
            np.max(np.abs(np.sum(occupations, axis=1) + stopped_mass - 1))
        ),
    }


def _draw_rows(probabilities, uniforms):
    cumulative = np.cumsum(probabilities, axis=1)
    cumulative[:, -1] = 1.0
    return np.sum(uniforms[:, None] > cumulative, axis=1)


def sample_step(model, state_indices, actions, rng=None, uniforms=None):
    """Sample one window with an auditable within-window event ledger.

    An actual hit is sampled from F and its time from conditional F inversion;
    surviving endpoint bins use K_t/S. Stopped paths use next_state_idx=-1.
    """
    states = np.asarray(state_indices, dtype=int).copy()
    actions = np.asarray(actions, dtype=int)
    if states.shape != actions.shape or states.ndim != 1:
        raise ValueError("States and actions must be matching 1D arrays")
    if (
        np.any(states < 0)
        or np.any(states >= model.n_states)
        or np.any(actions < 0)
        or np.any(actions > 2)
    ):
        raise ValueError("Invalid state/action")
    count = states.size
    if uniforms is None:
        if rng is None:
            raise ValueError("Supply a generator or five fixed uniform slots")
        uniforms = rng.random((count, 5))
    uniforms = np.asarray(uniforms, dtype=float)
    if (
        uniforms.shape != (count, 5)
        or not np.isfinite(uniforms).all()
        or np.any(uniforms < 0)
        or np.any(uniforms >= 1)
    ):
        raise ValueError("Uniform slots must have shape (paths,5) and lie in [0,1)")
    reset, stopped = actions == 1, actions == 2
    states[reset] = np.searchsorted(
        np.cumsum(model.maintenance_distribution), uniforms[reset, 0], side="right"
    )
    x_after_action = model.x[states].copy()
    x_after_action[stopped] = np.nan
    failed = (uniforms[:, 1] < model.F[states]) & ~stopped
    active_time = np.where(stopped, 0.0, model.spec.dt)
    tau_hit = np.full(count, np.nan)
    if failed.any():
        x = model.x[states[failed]]
        target = uniforms[failed, 2] * model.F[states[failed]]
        lo, hi = np.zeros_like(x), np.full_like(x, model.spec.dt)
        for _ in range(36):
            mid = (lo + hi) / 2
            reached = first_passage(x, model.spec.mu, model.spec.sigma, mid)["F"]
            below = reached < target
            lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
        tau_hit[failed] = active_time[failed] = (lo + hi) / 2
    q = model.spec.discount
    produced = -np.expm1(-q * active_time) / q if q else active_time
    reward = (
        model.spec.production_rate * produced
        - np.where(failed, model.spec.failure_cost * np.exp(-q * active_time), 0.0)
        - reset * model.spec.maintenance_cost
    )
    next_states = np.full(count, -1, dtype=int)
    survivors = ~failed & ~stopped
    rows = model.killed[states[survivors]] / model.S[states[survivors], None]
    next_states[survivors] = _draw_rows(rows, uniforms[survivors, 3])
    next_states[failed] = np.searchsorted(
        np.cumsum(model.failure_distribution), uniforms[failed, 4], side="right"
    )
    optional_tau = np.where(failed, tau_hit, None)
    optional_x = np.where(stopped, None, x_after_action)
    return {
        "tau_hit": optional_tau,
        "active_time": active_time,
        "failed": failed,
        "next_state_idx": next_states,
        "action": actions.copy(),
        "state_idx": np.asarray(state_indices).copy(),
        "x_after_action": optional_x,
        "reward": reward,
        "F_after_action": np.where(stopped, None, model.F[states]),
        "H_after_action": np.where(stopped, None, model.H[states]),
        "uniforms": uniforms.copy(),
    }


def sample_policy(
    model, policy, n_paths=10000, seed=0, horizon=None, record_trace=False
):
    """Event realization of exactly the same task evaluated by mass flow."""
    policy = _policy_array(model, policy, horizon)
    if n_paths < 2:
        raise ValueError("At least two paths are needed for a standard error")
    rng = np.random.default_rng(seed)
    states = np.searchsorted(
        np.cumsum(model.initial_distribution), rng.random(n_paths), side="right"
    )
    returns = np.zeros(n_paths)
    failures = np.zeros(n_paths, dtype=int)
    maintenance = np.zeros(n_paths, dtype=int)
    traces = []
    for elapsed in range(policy.shape[0]):
        innovations = rng.random((n_paths, 6))
        alive = np.flatnonzero(states >= 0)
        if not alive.size:
            break
        action = _draw_rows(
            policy[policy.shape[0] - elapsed - 1, states[alive]], innovations[alive, 0]
        )
        trace = sample_step(
            model, states[alive], action, uniforms=innovations[alive, 1:]
        )
        returns[alive] += model.gamma**elapsed * trace["reward"]
        failures[alive] += trace["failed"]
        maintenance[alive] += action == 1
        states[alive] = trace["next_state_idx"]
        if record_trace:
            trace.update(
                {
                    "path_ids": alive,
                    "action_uniform": innovations[alive, 0],
                    "elapsed": elapsed,
                    "discount_factor": model.gamma**elapsed,
                }
            )
            traces.append(trace)
    result = {
        "utility": float(returns.mean()),
        "standard_error": float(returns.std(ddof=1) / np.sqrt(n_paths)),
        "failures": float(failures.mean()),
        "maintenance": float(maintenance.mean()),
        "stopped_probability": float(np.mean(states < 0)),
        "returns": returns,
        "final_states": states,
        "seed": seed,
        "n_paths": n_paths,
    }
    if record_trace:
        result["trace"] = traces
    return result


def readout(model, continuation=None, boundary=0.0):
    """Task-grounded channels, with any learned continuation supplied explicitly.

    C is discounted production plus future utility including failure reset.
    P is discounted failure loss. Neither is called an independent financial
    option. Their difference exactly recovers Q_keep for the supplied critic.
    Supplying an oracle critic must be disclosed as an oracle experiment.
    """
    if continuation is None:
        continuation = np.zeros(model.n_states)
    continuation = np.asarray(continuation, dtype=float)
    if continuation.shape != model.x.shape or not np.isfinite(continuation).all():
        raise ValueError("Bad continuation shape or value")
    call = model.spec.production_rate * model.occupation + model.gamma * (
        model.transition @ continuation
    )
    put = model.spec.failure_cost * model.H
    return {
        "margin": model.x - boundary,
        "C": call,
        "P": put,
        "F": model.F,
        "S": model.S,
        "f": model.f,
        "H": model.H,
        "q_keep": call - put,
    }
