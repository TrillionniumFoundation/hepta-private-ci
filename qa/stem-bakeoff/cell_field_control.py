"""Finite deterministic parameter-field control of an existing Cell head.

The declared optimizer state is theta/m/v; its step is the known time index.
There is no invented diffusion: full-batch reference updates have Q=0. Dense
linearization and Riccati policies describe a local tangent problem, and their
nonlinear deployments are evaluated separately. No final-evaluation data enter
this module. Intervention cost is a parameter-coordinate quadratic, not runtime.
"""

from dataclasses import dataclass
import time

import numpy as np

from cell_learning_models import normalize_features


def _target_path(target, horizon, outputs):
    value = np.asarray(target, dtype=np.float64)
    if value.shape == (outputs,):
        value = np.tile(value, (horizon + 1, 1))
    if value.shape != (horizon + 1, outputs) or not np.isfinite(value).all():
        raise ValueError("one finite target per time and charged coordinate required")
    return value.copy()


def quadratic_cost(fields, actions, target, dt, effort_price):
    """Half terminal loss plus dt/2 times stage loss and action effort."""
    fields, actions = np.asarray(fields), np.asarray(actions)
    targets = _target_path(target, len(actions), fields.shape[1])
    errors = fields - targets
    tracking = 0.5 * (float(errors[-1] @ errors[-1])
                      + dt * float(np.square(errors[:-1]).sum()))
    effort = 0.5 * dt * effort_price * float(np.square(actions).sum())
    return {"total": tracking + effort, "tracking": tracking, "effort": effort}


def solve_lq(A, E, C, target, dt, effort_price):
    """Backward affine Riccati recursion, with deterministic zero affine drift.

    C is the charged map, which need not equal the policy observation map.
    The full-state optimum here is an unconstrained tangent optimum only.
    """
    A, E, C = (np.asarray(value, dtype=np.float64) for value in (A, E, C))
    horizon, dim = A.shape[:2]
    if (A.shape != (horizon, dim, dim) or E.ndim != 3
            or E.shape[:2] != (horizon, dim) or C.shape[0] != horizon + 1
            or C.shape[2] != dim or not 0 < dt <= 1 or effort_price <= 0
            or not all(np.isfinite(v).all() for v in (A, E, C))):
        raise ValueError("compatible finite LQ arrays and positive charges required")
    r = _target_path(target, horizon, C.shape[1])
    act = E.shape[2]
    P = np.zeros((horizon + 1, dim, dim))
    ell = np.zeros((horizon + 1, dim))
    constant = np.zeros(horizon + 1)
    K, offset = np.zeros((horizon, act, dim)), np.zeros((horizon, act))
    W = np.zeros((horizon, act, act))
    P[-1], ell[-1], constant[-1] = C[-1].T @ C[-1], -C[-1].T @ r[-1], 0.5 * r[-1] @ r[-1]
    for k in range(horizon - 1, -1, -1):
        a, e, c = A[k], E[k], C[k]
        W[k] = dt * effort_price * np.eye(act) + e.T @ P[k + 1] @ e
        W[k] = (W[k] + W[k].T) / 2
        K[k] = np.linalg.solve(W[k], e.T @ P[k + 1] @ a)
        offset[k] = -np.linalg.solve(W[k], e.T @ ell[k + 1])
        P[k] = dt * c.T @ c + a.T @ P[k + 1] @ a - K[k].T @ W[k] @ K[k]
        P[k] = (P[k] + P[k].T) / 2
        ell[k] = -dt * c.T @ r[k] + a.T @ ell[k + 1] + K[k].T @ W[k] @ offset[k]
        constant[k] = constant[k + 1] + 0.5 * dt * r[k] @ r[k] - 0.5 * offset[k] @ W[k] @ offset[k]
    return {"K": K, "offset": offset, "P": P, "ell": ell,
            "constant": constant, "W": W}


@dataclass
class Reference:
    state: object
    train_features: np.ndarray
    train_labels: np.ndarray
    probes: tuple
    states: np.ndarray
    observations: np.ndarray
    scales: np.ndarray
    A: np.ndarray
    C: np.ndarray
    dt: float
    derivative_audit: list
    build_wall_ns: int

    @property
    def horizon(self):
        return len(self.A)

    def observe(self, vector):
        head = self.state.head_from_vector(vector)
        rows = [head.loss_gradients(x, y, 0.0) for x, y in self.probes]
        gradients = [np.concatenate([g[n].ravel() for n in self.state.names]) for _, g in rows]
        p = self.state.parameter_count
        momentum = vector[p:2 * p]
        return np.array([rows[0][0], rows[1][0], gradients[0] @ momentum,
                         gradients[1] @ momentum]), gradients

    def action_matrix(self, mask):
        p, offset, selected = self.state.parameter_count, 0, []
        for name in self.state.names:
            size = self.state.head.params[name].size
            if mask == "all" or (mask == "bias" and name == "b"):
                selected.extend(range(offset, offset + size))
            offset += size
        if mask not in ("bias", "all") or not selected:
            raise ValueError("nested output-bias or complete-module mask required")
        B = np.eye(p)[:, selected]
        physical = np.vstack([self.dt * B, np.zeros((2 * p, len(selected)))])
        return B, np.tile(physical / self.scales[:, None], (self.horizon, 1, 1))

    def arrays(self):
        return {"reference_states": self.states, "reference_observations": self.observations,
                "state_scales": self.scales, "A": self.A, "C_extended": self.C}


def build_reference(state, train_features, train_labels, probes, *, horizon=24,
                    dt=0.02, fd_step=2e-5):
    """Freeze an exact full-batch trajectory and its numerical tangent arrays.

    probes = ((current_x,current_y),(old_x,old_y)); neither is unseen evaluation.
    State coordinates are scaled by fixed block RMS floors [.05,.001,1e-6].
    Theta columns use central finite differences, audited again at half step.
    Adam moment columns are analytic, so v is never perturbed across zero.
    Extended observations append g_current dot m and g_old dot m to both losses.
    """
    if (state.protocol["sampler"] != "full_batch" or state.step_count < 1
            or type(horizon) is not int or not 1 <= horizon <= 256
            or not 0 < dt <= 1 or not 1e-8 <= fd_step <= 1e-2 or len(probes) != 2):
        raise ValueError("warmed full-batch state and bounded control protocol required")
    began = time.perf_counter_ns()
    train_x, train_y = np.array(train_features, dtype=np.float64), np.array(train_labels, dtype=np.int64)
    normalized = tuple((normalize_features(x), np.asarray(y, dtype=np.int64).copy()) for x, y in probes)
    if any(x.shape[1] != state.head.width or y.shape != (len(x),)
           or len(np.unique(y)) != state.head.classes for x, y in normalized):
        raise ValueError("each controller probe must contain every declared class")
    p, x0 = state.parameter_count, state.vector()
    scales = np.concatenate([np.full(p, max(float(np.sqrt(np.mean(np.square(block)))), floor))
                             for block, floor in zip(np.split(x0, 3), (0.05, 0.001, 1e-6))])
    states = np.zeros((horizon + 1, 3 * p))
    states[0] = x0
    for k in range(horizon):
        states[k + 1] = state.transition_vector(states[k], state.step_count + k, train_x, train_y)
    ref = Reference(state.clone(), train_x, train_y, normalized, states,
                    np.zeros((horizon + 1, 4)), scales, np.zeros((horizon, 3 * p, 3 * p)),
                    np.zeros((horizon + 1, 4, 3 * p)), dt, [], 0)
    b1, b2 = state.protocol["beta1"], state.protocol["beta2"]
    lr, eps = state.protocol["learning_rate"], state.protocol["epsilon"]
    for k, x in enumerate(states):
        observation, gradients = ref.observe(x)
        ref.observations[k] = observation
        c = np.zeros((4, 3 * p))
        c[:2, :p] = np.vstack(gradients) * scales[:p]
        c[2:, p:2 * p] = np.vstack(gradients) * scales[p:2 * p]
        theta_a, theta_a_half = [], []
        c_half = c.copy()
        gradient_error = 0.0
        for j in range(p):
            values, transitions = [], []
            for multiplier in (1.0, 0.5):
                delta = fd_step * multiplier * scales[j]
                plus, minus = x.copy(), x.copy()
                plus[j] += delta
                minus[j] -= delta
                oplus, _ = ref.observe(plus)
                ominus, _ = ref.observe(minus)
                values.append((oplus - ominus) / (2 * fd_step * multiplier))
                if k < horizon:
                    tplus = state.transition_vector(plus, state.step_count + k, train_x, train_y)
                    tminus = state.transition_vector(minus, state.step_count + k, train_x, train_y)
                    transitions.append((tplus - tminus) / (2 * fd_step * multiplier) / scales)
            c[2:, j], c_half[2:, j] = values[0][2:], values[1][2:]
            gradient_error = max(gradient_error, float(np.max(np.abs(values[1][:2] - c[:2, j]))))
            if k < horizon:
                theta_a.append(transitions[0])
                theta_a_half.append(transitions[1])
        ref.C[k] = c
        audit = {"step": k, "theta_raw_fd_step": float(fd_step * scales[0]),
                 "moment_derivatives": "analytic; no v perturbations",
                 "loss_gradient_max_abs_fd_discrepancy": gradient_error,
                 "observation_half_step_relative_difference": float(np.linalg.norm(c - c_half) / (1 + np.linalg.norm(c_half)))}
        if k < horizon:
            a = ref.A[k]
            a[:, :p] = np.stack(theta_a, axis=1)
            completed = state.step_count + k + 1
            next_m, next_v = states[k + 1, p:2 * p], states[k + 1, 2 * p:]
            mhat, rootv = next_m / (1 - b1**completed), np.sqrt(next_v / (1 - b2**completed))
            dm = -lr * b1 / (1 - b1**completed) / (rootv + eps)
            dv = np.zeros(p)
            positive = rootv > 0
            if np.any((~positive) & (mhat != 0)):
                raise ValueError("nondifferentiable Adam reference moment encountered")
            dv[positive] = (lr * mhat[positive] * b2 / (2 * (1 - b2**completed)
                            * rootv[positive] * np.square(rootv[positive] + eps)))
            a[:p, p:2 * p] = np.diag(dm * scales[p:2 * p] / scales[:p])
            a[:p, 2 * p:] = np.diag(dv * scales[2 * p:] / scales[:p])
            a[p:2 * p, p:2 * p] = b1 * np.eye(p)
            a[2 * p:, 2 * p:] = b2 * np.eye(p)
            half = np.stack(theta_a_half, axis=1)
            audit["transition_theta_half_step_relative_difference"] = float(np.linalg.norm(a[:, :p] - half) / (1 + np.linalg.norm(half)))
        ref.derivative_audit.append(audit)
    if not all(np.isfinite(v).all() for v in (ref.states, ref.A, ref.C, ref.observations)):
        raise ValueError("nonfinite reference or tangent coefficients")
    ref.build_wall_ns = time.perf_counter_ns() - began
    return ref


@dataclass
class Controller:
    mode: str
    mask: str
    B: np.ndarray
    E: np.ndarray
    Cobs: np.ndarray
    F: np.ndarray
    D: np.ndarray
    charged: np.ndarray
    target: np.ndarray
    dt: float
    effort_price: float
    K: np.ndarray
    offset: np.ndarray
    riccati: dict
    build_wall_ns: int

    def action(self, k, observation):
        return -self.K[k] @ observation + self.offset[k]

    def arrays(self):
        return {"B": self.B, "E": self.E, "Cobs": self.Cobs, "F": self.F,
                "D": self.D, "charged": self.charged, "target": self.target,
                "K": self.K, "offset": self.offset,
                **{f"riccati_{key}": value for key, value in self.riccati.items()}}


def fit_controller(reference, *, mask, mode, target, effort_price=0.1):
    began = time.perf_counter_ns()
    if mode not in ("zero", "myopic", "loss2", "extended", "full"):
        raise ValueError("unknown frozen controller family")
    ref, n, d = reference, reference.horizon, reference.states.shape[1]
    target = _target_path(target, n, 2)
    B, E = ref.action_matrix(mask)
    if mode == "full":
        Cobs, F, D, charged = np.tile(np.eye(d), (n + 1, 1, 1)), ref.A.copy(), E.copy(), ref.C[:, :2].copy()
    else:
        q = 4 if mode == "extended" else 2
        Cobs = ref.C[:, :q].copy()
        inverses = [np.linalg.pinv(c, rcond=1e-10) for c in Cobs]
        F = np.array([Cobs[k + 1] @ ref.A[k] @ inverses[k] for k in range(n)])
        D = np.array([Cobs[k + 1] @ E[k] for k in range(n)])
        charged = np.tile(np.eye(q)[:2], (n + 1, 1, 1))
    act, obs = B.shape[1], Cobs.shape[1]
    riccati = {}
    if mode == "zero":
        K, offset = np.zeros((n, act, obs)), np.zeros((n, act))
    elif mode == "myopic":
        K, offset = np.zeros((n, act, obs)), np.zeros((n, act))
        for k in range(n):
            ce = charged[k + 1] @ D[k]
            W = ref.dt * effort_price * np.eye(act) + ce.T @ ce
            K[k] = np.linalg.solve(W, ce.T @ charged[k + 1] @ F[k])
            offset[k] = np.linalg.solve(W, ce.T @ target[k + 1])
    else:
        riccati = solve_lq(F, D, charged, target, ref.dt, effort_price)
        K, offset = riccati["K"], riccati["offset"]
    if not all(np.isfinite(v).all() for v in (K, offset)):
        raise ValueError("nonfinite policy; do not deploy")
    return Controller(mode, mask, B, E, Cobs, F, D, charged, target, ref.dt,
                      effort_price, K, offset, riccati, time.perf_counter_ns() - began)


def run_nonlinear(state, reference, controller):
    """Run a frozen policy through actual legacy-head Adam updates, without clipping."""
    ref, policy = reference, controller
    if state.digest() != ref.state.digest():
        raise ValueError("policy execution must start from the exact reference checkpoint")
    current = state.clone()
    n, d = ref.horizon, ref.states.shape[1]
    states, fields = np.zeros((n + 1, d)), np.zeros((n + 1, 2))
    observations = np.zeros((n + 1, 4))
    actions = np.zeros((n, policy.B.shape[1]))
    receipts = []
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    mask = np.any(policy.B != 0, axis=1)
    for k in range(n + 1):
        states[k] = current.vector()
        observations[k], _ = ref.observe(states[k])
        fields[k] = observations[k, :2] - ref.observations[k, :2]
        if k == n:
            break
        if policy.mode == "full":
            measured = (states[k] - ref.states[k]) / ref.scales
        else:
            width = policy.Cobs.shape[1]
            measured = observations[k, :width] - ref.observations[k, :width]
        actions[k] = policy.action(k, measured)
        delta = ref.dt * policy.B @ actions[k]
        receipts.append(current.advance(ref.train_features, ref.train_labels, intervention=delta, mask=mask))
    elapsed, cpu_elapsed = time.perf_counter_ns() - began, time.process_time_ns() - cpu_began
    if not np.isfinite(states).all() or not np.isfinite(actions).all():
        raise ValueError("nonfinite nonlinear deployment")
    return {"state": current, "states": states, "observations": observations, "fields": fields,
            "actions": actions, "receipts": receipts,
            "cost": quadratic_cost(fields, actions, policy.target, policy.dt, policy.effort_price),
            "wall_ns": elapsed, "cpu_ns": cpu_elapsed,
            "physical_intervention_squared_norm": float(np.square(ref.dt * actions).sum()),
            "max_physical_intervention_l2": float(np.max(np.linalg.norm(ref.dt * actions, axis=1)))}


def diagnose_tangent(reference, controller, oracle=None, initial=None):
    """Exact algebraic diagnostics of the declared numerical deterministic arrays.

    Occupancy is a point path. The Bellman gap is combined information/policy
    error, not an estimate of irreducible information loss. Transfer compares
    the same feedback in full and projected arrays, never nonlinear deployment.
    """
    ref, policy = reference, controller
    n, d, q, act = ref.horizon, ref.states.shape[1], policy.Cobs.shape[1], policy.B.shape[1]
    if oracle is None:
        oracle = fit_controller(ref, mask=policy.mask, mode="full", target=policy.target,
                                effort_price=policy.effort_price)
    if oracle.mode != "full" or oracle.mask != policy.mask or not np.array_equal(oracle.target, policy.target):
        raise ValueError("identical-action, identical-objective full-state oracle required")
    z = np.zeros((n + 1, d))
    if initial is not None:
        z[0] = np.asarray(initial, dtype=np.float64)
    projected = np.zeros((n + 1, q))
    projected[0] = policy.Cobs[0] @ z[0]
    u, up = np.zeros((n, act)), np.zeros((n, act))
    forcing, bound, discrepancy = np.zeros(n), np.zeros(n + 1), np.zeros(n + 1)
    advantage = 0.0
    for k in range(n):
        measured = policy.Cobs[k] @ z[k]
        u[k], up[k] = policy.action(k, measured), policy.action(k, projected[k])
        residual = policy.Cobs[k + 1] @ ref.A[k] - policy.F[k] @ policy.Cobs[k]
        forcing[k] = np.linalg.norm(residual @ z[k])
        bound[k + 1] = np.linalg.norm(policy.F[k] - policy.D[k] @ policy.K[k], 2) * bound[k] + forcing[k]
        z[k + 1] = ref.A[k] @ z[k] + policy.E[k] @ u[k]
        projected[k + 1] = policy.F[k] @ projected[k] + policy.D[k] @ up[k]
        discrepancy[k + 1] = np.linalg.norm(policy.Cobs[k + 1] @ z[k + 1] - projected[k + 1])
        diff = u[k] - oracle.action(k, z[k])
        advantage += 0.5 * float(diff @ oracle.riccati["W"][k] @ diff)
    fields = np.einsum("kij,kj->ki", ref.C[:, :2], z)
    projected_fields = np.einsum("kij,kj->ki", policy.charged, projected)
    full_cost = quadratic_cost(fields, u, policy.target, policy.dt, policy.effort_price)
    projected_cost = quadratic_cost(projected_fields, up, policy.target, policy.dt, policy.effort_price)
    value = float(0.5 * z[0] @ oracle.riccati["P"][0] @ z[0]
                  + oracle.riccati["ell"][0] @ z[0] + oracle.riccati["constant"][0])
    field_delta = np.linalg.norm(fields - projected_fields, axis=1)
    sizes = np.linalg.norm(fields - policy.target, axis=1) + np.linalg.norm(projected_fields - policy.target, axis=1)
    action_delta = np.linalg.norm(u - up, axis=1)
    action_sizes = np.linalg.norm(u, axis=1) + np.linalg.norm(up, axis=1)
    cost_bound = 0.5 * float(field_delta[-1] * sizes[-1] + policy.dt * np.sum(field_delta[:-1] * sizes[:-1]
                            + policy.effort_price * action_delta * action_sizes))
    return {"states": z, "projected_states": projected, "actions": u, "projected_actions": up,
            "forcing": forcing, "field_discrepancy": discrepancy, "field_transfer_bound": bound,
            "cost": full_cost, "projected_cost": projected_cost, "oracle_value": value,
            "combined_information_policy_gap": full_cost["total"] - value,
            "bellman_advantage_sum": advantage,
            "bellman_identity_abs_error": abs(full_cost["total"] - value - advantage),
            "same_policy_cost_difference": full_cost["total"] - projected_cost["total"],
            "same_policy_cost_bound": cost_bound,
            "transfer_bound_max_violation": float(np.max(discrepancy - bound)),
            "observation_ranks": [int(np.linalg.matrix_rank(c, tol=1e-10 * np.linalg.norm(c, 2))) for c in policy.Cobs],
            "scope": "deterministic tangent arrays; no irreducible-information or nonlinear certificate"}
