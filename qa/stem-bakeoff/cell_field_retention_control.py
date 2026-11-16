"""Single-sided forgetting penalties on the frozen Cell tangent models.

The penalty is soft: it does not enforce retention feasibility. A full-state
plan is an approximate optimum of declared finite tangent arrays only. Every
plan starts at zero controls; there is no hidden optimizer warm-start state.
"""

from dataclasses import dataclass, field
import time

import numpy as np

from cell_field_control import fit_controller, quadratic_cost, run_nonlinear


def retention_cost(fields, actions, target, dt, effort_price,
                   retention_tolerance=0.0):
    values, controls, targets = (np.asarray(x, dtype=np.float64)
                                for x in (fields, actions, target))
    if (values.shape != targets.shape or values.shape != (len(controls) + 1, 2)
            or controls.ndim != 2 or dt <= 0 or effort_price <= 0
            or retention_tolerance < 0 or not np.isfinite([dt, effort_price, retention_tolerance]).all()
            or not all(np.isfinite(x).all() for x in (values, controls, targets))):
        raise ValueError("finite compatible loss fields and positive charges required")
    errors = values - targets
    current = errors[:, 0]
    raw_excess = errors[:, 1] - retention_tolerance
    forgetting = np.maximum(raw_excess, 0.0)
    weights = np.r_[np.full(len(controls), dt), 1.0]
    current_cost = 0.5 * float(weights @ np.square(current))
    forgetting_cost = 0.5 * float(weights @ np.square(forgetting))
    effort = 0.5 * dt * effort_price * float(np.square(controls).sum())
    return {"total": current_cost + forgetting_cost + effort,
            "tracking": current_cost + forgetting_cost,
            "current": current_cost, "forgetting": forgetting_cost,
            "effort": effort, "maximum_old_excess": float(raw_excess.max()),
            "terminal_old_excess": float(raw_excess[-1]),
            "old_violation_steps": int(np.count_nonzero(raw_excess > 1e-12)),
            "retention_tolerance": retention_tolerance,
            "scope": "single-sided soft penalty; no hard retention guarantee"}


def condense_dynamics(F, D, charged, target, dt, start=0, lookahead=None):
    """Affine weighted error maps for a remaining-horizon control sequence.

    Returns current_error=M@U+current_state@initial+current_offset and
    old_error=N@U+old_state@initial+old_offset. Positive time weights are
    already absorbed. A one-step lookahead retains terminal weight one.
    """
    F, D, C, target = (np.asarray(x, dtype=np.float64)
                       for x in (F, D, charged, target))
    horizon, dim = F.shape[:2]
    if (F.shape != (horizon, dim, dim) or D.shape[:2] != (horizon, dim)
            or C.shape != (horizon + 1, 2, dim) or target.shape != (horizon + 1, 2)
            or type(start) is not int or not 0 <= start < horizon or dt <= 0
            or not all(np.isfinite(x).all() for x in (F, D, C, target))):
        raise ValueError("compatible finite dynamics and valid starting step required")
    remaining = horizon - start if lookahead is None else lookahead
    if type(remaining) is not int or not 1 <= remaining <= horizon - start:
        raise ValueError("lookahead must fit within remaining horizon")
    act = D.shape[2]
    initial_map = np.eye(dim)
    control_map = np.zeros((dim, remaining * act))
    control_rows, initial_rows = [], []
    weights = np.sqrt(np.r_[np.full(remaining, dt), 1.0])
    for local in range(remaining + 1):
        k = start + local
        initial_rows.append(weights[local] * C[k] @ initial_map)
        control_rows.append(weights[local] * C[k] @ control_map)
        if local < remaining:
            initial_map = F[k] @ initial_map
            control_map = F[k] @ control_map
            control_map[:, local * act:(local + 1) * act] += D[k]
    G, H = np.array(control_rows), np.array(initial_rows)
    offset = -weights[:, None] * target[start:start + remaining + 1]
    return {"M": G[:, 0], "N": G[:, 1], "current_state": H[:, 0],
            "old_state": H[:, 1], "current_offset": offset[:, 0],
            "old_offset": offset[:, 1], "sqrt_weights": weights,
            "horizon": remaining, "action_width": act}


def condensed_value_gradient(M, a, N, b, regularization, controls,
                             one_sided=True):
    """Objective and exact gradient; separate entry point for independent checks."""
    current = M @ controls + a
    raw_old = N @ controls + b
    old = np.maximum(raw_old, 0.0) if one_sided else raw_old
    value = 0.5 * float(current @ current + old @ old
                        + regularization * (controls @ controls))
    gradient = M.T @ current + N.T @ old + regularization * controls
    return value, gradient, raw_old


def solve_squared_hinge(M, a, N, b, regularization, *, max_iterations=100,
                        gap_tolerance=1e-10, one_sided=True):
    """Semismooth Newton with deterministic Armijo globalization.

    Hessians are lambda*I plus at most two rows per time point. Woodbury solves
    the small row-space system. Strong convexity gives the global same-array
    bound f(U)-f* <= ||gradient||^2/(2*lambda). No solver flag substitutes for it.
    """
    M, a, N, b = (np.asarray(x, dtype=np.float64) for x in (M, a, N, b))
    if (M.ndim != 2 or N.shape != M.shape or a.shape != (len(M),)
            or b.shape != a.shape or regularization <= 0
            or type(max_iterations) is not int or not 1 <= max_iterations <= 10000
            or gap_tolerance <= 0 or not np.isfinite([regularization, gap_tolerance]).all()
            or not all(np.isfinite(x).all() for x in (M, a, N, b))):
        raise ValueError("compatible finite condensed arrays and positive regularization required")
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    controls = np.zeros(M.shape[1])
    backtracks, history, converged, failure = 0, [], False, None
    for iteration in range(max_iterations + 1):
        value, gradient, raw_old = condensed_value_gradient(
            M, a, N, b, regularization, controls, one_sided)
        norm_squared = float(gradient @ gradient)
        gap = norm_squared / (2 * regularization)
        history.append([value, norm_squared, gap])
        if not np.isfinite([value, norm_squared, gap]).all():
            failure = "nonfinite_objective_or_gradient"
            break
        if gap <= gap_tolerance:
            converged = True
            break
        if iteration == max_iterations:
            failure = "iteration_budget_exhausted"
            break
        active = raw_old > 0 if one_sided else np.ones(len(b), dtype=bool)
        rows, offset = np.vstack([M, N[active]]), np.r_[a, b[active]]
        system = rows @ rows.T + regularization * np.eye(len(rows))
        try:
            optimum_for_cell = -rows.T @ np.linalg.solve(system, offset)
        except np.linalg.LinAlgError:
            failure = "linear_system_solve_failure"
            break
        direction = optimum_for_cell - controls
        descent = float(gradient @ direction)
        if not np.isfinite(descent) or descent >= 0:
            failure = "non_descent_newton_direction"
            break
        step = 1.0
        accepted = False
        for reductions in range(41):
            proposal = controls + step * direction
            proposal_value = condensed_value_gradient(
                M, a, N, b, regularization, proposal, one_sided)[0]
            if np.isfinite(proposal_value) and proposal_value <= value + 1e-4 * step * descent:
                controls = proposal
                backtracks += reductions
                accepted = True
                break
            step *= 0.5
        if not accepted:
            failure = "line_search_budget_exhausted"
            break
    record = {"solver": "semismooth_newton_armijo_woodbury", "converged": converged,
              "objective_kind": "hinge" if one_sided else "symmetric",
              "iterations": iteration, "maximum_iterations": max_iterations,
              "line_search_reductions": backtracks, "objective": value,
              "gradient_norm_squared": norm_squared,
              "optimality_gap_bound": gap, "gap_tolerance": gap_tolerance,
              "strong_convexity": regularization, "failure": failure,
              "initialization": "zero_controls_no_cross_step_state",
              "wall_ns": time.perf_counter_ns() - began,
              "cpu_ns": time.process_time_ns() - cpu_began}
    return {"controls": controls, "gradient": gradient, "record": record,
            "history": np.asarray(history), "active_old": raw_old > 0}


@dataclass
class RetentionController:
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
    retention_tolerance: float = 0.0
    max_iterations: int = 100
    gap_tolerance: float = 1e-10
    K: np.ndarray = field(default_factory=lambda: np.zeros((0,)))
    offset: np.ndarray = field(default_factory=lambda: np.zeros((0,)))
    build_wall_ns: int = 0
    records: list = field(default_factory=list)
    plans: list = field(default_factory=list)
    _maps: dict = field(default_factory=dict)

    def arrays(self):
        return {key: getattr(self, key) for key in
                ("B", "E", "Cobs", "F", "D", "charged", "target", "K", "offset")}

    def plan(self, k, observation):
        """Pure control plan; mutable caches contain only fixed model arrays."""
        observed = np.asarray(observation, dtype=np.float64)
        if observed.shape != (self.Cobs.shape[1],) or not np.isfinite(observed).all():
            raise ValueError("finite observation of the declared width required")
        if k not in self._maps:
            self._maps[k] = condense_dynamics(
                self.F, self.D, self.charged, self.target, self.dt, k,
                1 if self.mode == "myopic" else None)
        maps = self._maps[k]
        a = maps["current_state"] @ observed + maps["current_offset"]
        b = maps["old_state"] @ observed + maps["old_offset"]
        b -= self.retention_tolerance * maps["sqrt_weights"]
        regularization = self.dt * self.effort_price
        if self.mode in ("zero", "symmetric_loss2"):
            remaining, act = maps["horizon"], maps["action_width"]
            actions, current = np.zeros((remaining, act)), observed.copy()
            for i in range(remaining):
                if self.mode == "symmetric_loss2":
                    actions[i] = -self.K[k + i] @ current + self.offset[k + i]
                current = self.F[k + i] @ current + self.D[k + i] @ actions[i]
            value, gradient, _ = condensed_value_gradient(
                maps["M"], a, maps["N"], b, regularization, actions.ravel(),
                self.mode != "symmetric_loss2")
            norm_squared = float(gradient @ gradient)
            gap = norm_squared / (2 * regularization)
            qualified = self.mode == "symmetric_loss2" and gap <= self.gap_tolerance
            record = {"solver": "none" if self.mode == "zero" else "original_affine_riccati",
                      "converged": qualified,
                      "objective_kind": "hinge" if self.mode == "zero" else "symmetric",
                      "iterations": 0, "maximum_iterations": 0,
                      "objective": value, "gradient_norm_squared": norm_squared,
                      "optimality_gap_bound": gap,
                      "strong_convexity": regularization,
                      "failure": "riccati_gradient_gap_exceeds_tolerance"
                      if self.mode == "symmetric_loss2" and not qualified else None,
                      "gap_tolerance": self.gap_tolerance}
            solution = {"controls": actions.ravel(), "gradient": gradient,
                        "record": record, "history": np.zeros((0, 3))}
        else:
            solution = solve_squared_hinge(maps["M"], a, maps["N"], b, regularization,
                                          max_iterations=self.max_iterations,
                                          gap_tolerance=self.gap_tolerance)
            actions = solution["controls"].reshape(maps["horizon"], maps["action_width"])
        states = [observed.copy()]
        for i, action in enumerate(actions):
            states.append(self.F[k + i] @ states[-1] + self.D[k + i] @ action)
        fields = np.einsum("kij,kj->ki", self.charged[k:k + len(states)], np.asarray(states))
        return {**solution, "actions": actions, "fields": fields,
                "states": np.asarray(states), "start": k}

    def action(self, k, observation):
        began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
        plan = self.plan(k, observation)
        record = {**plan["record"], "step": k, "horizon": len(plan["actions"]),
                  "plan_wall_ns": time.perf_counter_ns() - began,
                  "plan_cpu_ns": time.process_time_ns() - cpu_began}
        self.records.append(record)
        self.plans.append(plan)
        if self.mode != "zero" and not record["converged"]:
            raise RuntimeError("retention solver failed: " + str(record["failure"]))
        return plan["actions"][0].copy()

    @classmethod
    def from_arrays(cls, arrays, *, mode, mask, dt, effort_price=0.1,
                    retention_tolerance=0.0, max_iterations=100, gap_tolerance=1e-10):
        return cls(mode, mask, **{key: np.array(arrays[key], copy=True) for key in
                   ("B", "E", "Cobs", "F", "D", "charged", "target", "K", "offset")},
                   dt=dt, effort_price=effort_price, retention_tolerance=retention_tolerance,
                   max_iterations=max_iterations, gap_tolerance=gap_tolerance)


def fit_retention_controller(reference, *, mask, mode, target, effort_price=0.1,
                             retention_tolerance=0.0, max_iterations=100,
                             gap_tolerance=1e-10):
    began = time.perf_counter_ns()
    if mode not in ("zero", "myopic", "loss2", "extended", "full", "symmetric_loss2"):
        raise ValueError("unregistered retention policy")
    if retention_tolerance != 0:
        raise ValueError("v2 isolates the single-sided change with tolerance fixed to zero")
    ref, n, d = reference, reference.horizon, reference.states.shape[1]
    target = np.asarray(target, dtype=np.float64)
    if target.shape != (n + 1, 2) or not np.isfinite(target).all():
        raise ValueError("finite two-loss target at every reference point required")
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
    controller = RetentionController(mode, mask, B, E, Cobs, F, D, charged,
                                     target.copy(), ref.dt, effort_price,
                                     retention_tolerance, max_iterations, gap_tolerance)
    if mode == "symmetric_loss2":
        legacy = fit_controller(ref, mask=mask, mode="loss2", target=target,
                                effort_price=effort_price)
        controller.K, controller.offset = legacy.K.copy(), legacy.offset.copy()
    controller.build_wall_ns = time.perf_counter_ns() - began
    return controller


def _plan_arrays(controller):
    n, act = len(controller.F), controller.B.shape[1]
    actions, fields = np.zeros((n, n, act)), np.zeros((n, n + 1, 2))
    lengths = np.zeros(n, dtype=np.int64)
    for plan in controller.plans:
        k, size = plan["start"], len(plan["actions"])
        actions[k, :size], fields[k, :size + 1], lengths[k] = plan["actions"], plan["fields"], size
    return {"planned_actions": actions, "planned_fields": fields, "plan_lengths": lengths}


def run_retention_nonlinear(state, reference, controller):
    controller.records.clear()
    controller.plans.clear()
    run = run_nonlinear(state, reference, controller)
    run["legacy_symmetric_cost"] = run["cost"]
    run["cost"] = retention_cost(run["fields"], run["actions"], controller.target,
                                  controller.dt, controller.effort_price,
                                  controller.retention_tolerance)
    run["solver_records"] = list(controller.records)
    run.update(_plan_arrays(controller))
    return run


def initial_optimum(controller, initial=None):
    if controller.mode != "full":
        raise ValueError("same-action full tangent controller required for oracle")
    initial = np.zeros(controller.F.shape[1]) if initial is None else np.asarray(initial)
    plan = controller.plan(0, initial)
    if not plan["record"]["converged"]:
        raise RuntimeError("unconverged full-state plan is not an oracle")
    upper, gap = plan["record"]["objective"], plan["record"]["optimality_gap_bound"]
    return {**plan, "value_lower": upper - gap, "value_upper": upper,
            "scope": "certified numerical optimum interval of declared tangent arrays only"}


def diagnose_retention_tangent(reference, controller, oracle=None, initial=None):
    """Actual feedback in full tangent dynamics; no nonlinear or Bellman claim."""
    ref, policy = reference, controller
    n, d = ref.horizon, ref.states.shape[1]
    z, actions = np.zeros((n + 1, d)), np.zeros((n, policy.B.shape[1]))
    if initial is not None:
        z[0] = np.asarray(initial)
    policy.records.clear()
    policy.plans.clear()
    forcing = np.zeros(n)
    for k in range(n):
        actions[k] = policy.action(k, policy.Cobs[k] @ z[k])
        residual = policy.Cobs[k + 1] @ ref.A[k] - policy.F[k] @ policy.Cobs[k]
        forcing[k] = np.linalg.norm(policy.charged[k + 1] @ residual @ z[k])
        z[k + 1] = ref.A[k] @ z[k] + policy.E[k] @ actions[k]
    fields = np.einsum("kij,kj->ki", ref.C[:, :2], z)
    result = {"states": z, "actions": actions, "fields": fields,
              "charged_closure_forcing": forcing,
              "cost": retention_cost(fields, actions, policy.target, policy.dt,
                                      policy.effort_price, policy.retention_tolerance),
              "legacy_symmetric_cost": quadratic_cost(fields, actions, policy.target,
                                                       policy.dt, policy.effort_price),
              "solver_records": list(policy.records), **_plan_arrays(policy)}
    if oracle is not None:
        if (oracle.mask != policy.mask or not np.array_equal(oracle.B, policy.B)
                or not np.array_equal(oracle.target, policy.target)
                or oracle.dt != policy.dt or oracle.effort_price != policy.effort_price
                or oracle.retention_tolerance != policy.retention_tolerance):
            raise ValueError("identical actions and objective required for comparator")
        optimum = initial_optimum(oracle, z[0])
        actual = result["cost"]["total"]
        result.update(oracle_value_lower=optimum["value_lower"],
                      oracle_value_upper=optimum["value_upper"],
                      combined_information_policy_gap_interval=[actual - optimum["value_upper"],
                                                                actual - optimum["value_lower"]])
    result["scope"] = "deterministic frozen tangent model; combined gap, no irreducible information claim"
    return result
