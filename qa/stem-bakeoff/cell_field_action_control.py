"""Bounded one-intervention Cell candidates and explicit tangent certificates.

Every candidate is one parameter-coordinate action followed by zero controls.
Solver qualification is independently checkable floating arithmetic on the
declared convex tangent problem, not nonlinear retention or global optimality.
"""

import time

import numpy as np
from scipy.optimize import linprog, minimize, nnls


def objective_value_gradient(M, a, N, b, c, constant, regularization, u):
    current = M @ u + a
    old = np.maximum(N @ u + b, 0.0)
    value = (constant + c @ u + 0.5 * (current @ current + old @ old
                                      + regularization * (u @ u)))
    gradient = M.T @ current + N.T @ old + c + regularization * u
    return float(value), gradient


def _feasibility(G, q, bound, tolerance):
    """Find a feasible point or a box-Farkas separating witness, never guess."""
    n, m = len(bound), len(q)
    zero = np.zeros(n)
    record = {"status": "zero_feasible", "lp_status": None, "dual_lp_status": None,
              "witness_margin": None, "witness_tolerance": tolerance,
              "scope": "hard tangent rows enlarged by the declared feasibility tolerance"}
    if not m or np.max(G @ zero - q) <= 0:
        return zero, np.zeros(m), record
    options = {"primal_feasibility_tolerance": 1e-10,
               "dual_feasibility_tolerance": 1e-10, "time_limit": 10.0,
               "maxiter": 10000}
    feasible = linprog(zero, A_ub=G, b_ub=q, bounds=list(zip(-bound, bound)),
                       method="highs", options=options)
    record["lp_status"] = int(feasible.status)
    if feasible.x is not None and np.isfinite(feasible.x).all():
        point = np.clip(np.asarray(feasible.x), -bound, bound)
        if np.max(G @ point - q) <= tolerance:
            record["status"] = "phase_one_feasible"
            return point, np.zeros(m), record
    # For mu>=0, sum(mu)=1, every box point satisfies
    # mu@(G*u-(q+tol)) >= -bound@abs(G.T@mu)-(q+tol)@mu.
    # A positive right side separates the entire box from all hard rows.
    objective = np.r_[q + tolerance, bound]
    inequalities = np.vstack([np.c_[G.T, -np.eye(n)], np.c_[-G.T, -np.eye(n)]])
    witness = linprog(objective, A_ub=inequalities, b_ub=np.zeros(2 * n),
                      A_eq=np.r_[np.ones(m), np.zeros(n)][None, :], b_eq=[1.0],
                      bounds=(0.0, None), method="highs", options=options)
    record["dual_lp_status"] = int(witness.status)
    mu = np.zeros(m)
    if witness.x is not None and np.isfinite(witness.x).all():
        mu = np.maximum(witness.x[:m], 0.0)
        if mu.sum() > 0:
            mu /= mu.sum()
            margin = float(-bound @ np.abs(G.T @ mu) - (q + tolerance) @ mu)
            record["witness_margin"] = margin
            if margin > tolerance:
                record["status"] = "tangent_infeasible_with_box_witness"
                return None, mu, record
    record["status"] = "feasibility_unresolved"
    return None, mu, record


def solve_bounded_problem(M, a, N, b, c, constant, regularization, bound, G, q,
                          *, feasibility_tolerance=1e-9, gap_tolerance=1e-9,
                          max_iterations=300, ftol=1e-13):
    """SLSQP proposal followed by a nonnegative-multiplier dual gap check.

The numerical certificate uses G*u<=q+feasibility_tolerance and exact boxes.
For any nonnegative multipliers, strong convexity bounds the Lagrangian below
by L(u)-||grad L(u)||^2/(2*regularization). Feasible u supplies an upper bound.
The solver success flag is recorded but never substitutes for this check.
"""
    M, a, N, b, c, bound, G, q = (np.asarray(x, dtype=np.float64)
                                 for x in (M, a, N, b, c, bound, G, q))
    n = len(c)
    if (c.shape != (n,) or not 1 <= n <= 4096 or M.ndim != 2 or M.shape[1] != n
            or N.ndim != 2 or N.shape[1] != n or a.shape != (len(M),)
            or b.shape != (len(N),) or bound.shape != (n,) or np.any(bound <= 0)
            or G.ndim != 2 or G.shape[1] != n or q.shape != (len(G),)
            or type(max_iterations) is not int or not 1 <= max_iterations <= 10000
            or min(regularization, feasibility_tolerance, gap_tolerance, ftol) <= 0
            or not np.isfinite([constant, regularization, feasibility_tolerance,
                                gap_tolerance, ftol]).all()
            or not all(np.isfinite(x).all() for x in (M, a, N, b, c, bound, G, q))):
        raise ValueError("finite compatible convex arrays, positive charges and bounds required")
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    point, witness, phase = _feasibility(G, q, bound, feasibility_tolerance)
    certificate_A = np.vstack([G, np.eye(n), -np.eye(n)])
    certificate_b = np.r_[q + feasibility_tolerance, bound, bound]
    record = {"solver": "scipy_slsqp_then_nonnegative_dual_check", "status": phase["status"],
              "qualified": False, "solver_success": False, "solver_status": None,
              "iterations": 0, "maximum_iterations": max_iterations, "ftol": ftol,
              "feasibility_tolerance": feasibility_tolerance, "gap_tolerance": gap_tolerance,
              "strong_convexity": regularization, "phase_one": phase,
              "objective": None, "objective_lower_bound": None, "optimality_gap_bound": None,
              "raw_hard_violation": None, "certificate_primal_violation": None,
              "bound_violation": None, "stationarity_norm_squared": None,
              "multiplier_fit_failure": None,
              "initialization": "zero_or_declared_phase_one_point; no cross-call warm start",
              "certificate_scope": "floating arithmetic; tolerance-enlarged hard tangent rows; exact box budget; no nonlinear guarantee"}
    if point is None:
        record.update(wall_ns=time.perf_counter_ns() - began,
                      cpu_ns=time.process_time_ns() - cpu_began)
        return {"u": np.zeros(0), "gradient": np.zeros(0), "dual": np.zeros(len(certificate_b)),
                "stationarity": np.zeros(0), "certificate_A": certificate_A,
                "certificate_b": certificate_b, "phase_one_point": np.zeros(0),
                "farkas_weights": witness, "history": np.zeros((0, 2)), "record": record}
    history = []
    value_grad = lambda u: objective_value_gradient(M, a, N, b, c, constant, regularization, u)

    def callback(u):
        history.append([value_grad(u)[0], float(max(0.0, np.max(G @ u - q))) if len(q) else 0.0])

    constraints = [] if not len(q) else [{"type": "ineq", "fun": lambda u: q - G @ u,
                                         "jac": lambda u: -G}]
    result = minimize(lambda u: value_grad(u)[0] - constant, point,
                      jac=lambda u: value_grad(u)[1], method="SLSQP",
                      bounds=list(zip(-bound, bound)), constraints=constraints,
                      callback=callback, options={"maxiter": max_iterations, "ftol": ftol, "disp": False})
    u = np.asarray(result.x, dtype=np.float64)
    if u.shape != (n,) or not np.isfinite(u).all():
        record.update(status="solver_failed_or_unresolved", failure="invalid_or_nonfinite_solver_proposal",
                      solver_success=bool(result.success), solver_status=int(result.status),
                      solver_message=str(result.message), iterations=int(result.nit),
                      wall_ns=time.perf_counter_ns() - began, cpu_ns=time.process_time_ns() - cpu_began)
        return {"u": u, "gradient": np.zeros(0), "dual": np.zeros(len(certificate_b)),
                "stationarity": np.zeros(0), "certificate_A": certificate_A,
                "certificate_b": certificate_b, "phase_one_point": point,
                "farkas_weights": witness, "history": np.asarray(history).reshape(-1, 2), "record": record}
    # This is the final bounded optimization proposal, never deployment clipping.
    clipped = np.clip(u, -bound, bound)
    record["solver_bound_repair_max_abs"] = float(np.max(np.abs(clipped - u)))
    u = clipped
    value, gradient = value_grad(u)
    residuals = certificate_A @ u - certificate_b
    active = residuals >= -max(1e-7, 10 * feasibility_tolerance)
    dual = np.zeros(len(residuals))
    if np.any(active):
        try:
            dual[active] = nnls(certificate_A[active].T, -gradient,
                                maxiter=max(1000, 3 * int(active.sum())))[0]
        except RuntimeError as error:
            record["multiplier_fit_failure"] = str(error)
    stationarity = gradient + certificate_A.T @ dual
    squared = float(stationarity @ stationarity)
    gap = float(-dual @ residuals + squared / (2 * regularization))
    raw_hard = float(max(0.0, np.max(G @ u - q))) if len(q) else 0.0
    cert_violation = float(max(0.0, residuals.max()))
    bound_violation = float(max(0.0, np.max(np.abs(u) - bound)))
    finite = all(np.isfinite(v).all() for v in (u, gradient, stationarity, dual))
    qualified = (finite and np.isfinite([value, gap]).all() and cert_violation == 0.0
                 and 0.0 <= gap <= gap_tolerance)
    record.update(status="qualified" if qualified else "solver_failed_or_unresolved",
                  qualified=bool(qualified), solver_success=bool(result.success),
                  solver_status=int(result.status), solver_message=str(result.message),
                  iterations=int(result.nit), objective=value, objective_lower_bound=value - gap,
                  optimality_gap_bound=gap, raw_hard_violation=raw_hard,
                  certificate_primal_violation=cert_violation, bound_violation=bound_violation,
                  stationarity_norm_squared=squared, wall_ns=time.perf_counter_ns() - began,
                  cpu_ns=time.process_time_ns() - cpu_began)
    return {"u": u, "gradient": gradient, "dual": dual, "stationarity": stationarity,
            "certificate_A": certificate_A, "certificate_b": certificate_b,
            "phase_one_point": point, "farkas_weights": witness,
            "history": np.asarray(history, dtype=np.float64).reshape(-1, 2), "record": record}


def build_action_model(reference, *, observation):
    """One post-Adam impulse followed by common zero continuation."""
    if observation not in ("loss2", "full"):
        raise ValueError("registered loss2 or full observation required")
    ref, horizon = reference, reference.horizon
    B, E = ref.action_matrix("all")
    d, p = ref.states.shape[1], B.shape[1]
    if observation == "full":
        Cobs = np.tile(np.eye(d), (horizon + 1, 1, 1))
        F, D, charged = ref.A.copy(), E.copy(), ref.C[:, :2].copy()
    else:
        Cobs = ref.C[:, :2].copy()
        inverses = [np.linalg.pinv(c, rcond=1e-10) for c in Cobs]
        F = np.array([Cobs[k + 1] @ ref.A[k] @ inverses[k] for k in range(horizon)])
        D = np.array([Cobs[k + 1] @ E[k] for k in range(horizon)])
        charged = np.tile(np.eye(2), (horizon + 1, 1, 1))
    impulse = np.zeros((horizon + 1, F.shape[1], p))
    impulse[1] = D[0]
    for k in range(1, horizon):
        impulse[k + 1] = F[k] @ impulse[k]
    maps = np.einsum("kij,kjl->kil", charged, impulse)
    return {"B": B, "E": E, "Cobs": Cobs, "F": F, "D": D, "charged": charged,
            "impulse_states": impulse, "loss_maps": maps,
            "reference_observations": ref.observations[:, :2].copy()}


def action_problem(model, *, objective, lookahead, old_anchor, dt=0.02,
                   effort_price=0.1, action_bound=1.0, current_shift=0.03,
                   direct_coefficient=0.03):
    if objective not in ("tracking_soft", "direct_soft", "direct_hard"):
        raise ValueError("registered one-factor objective required")
    maps, baseline = model["loss_maps"], model["reference_observations"]
    horizon, p = len(maps) - 1, maps.shape[2]
    if (type(lookahead) is not int or not 1 <= lookahead <= horizon
            or maps.shape != (horizon + 1, 2, p) or baseline.shape != (horizon + 1, 2)
            or min(dt, effort_price, action_bound, current_shift, direct_coefficient) <= 0
            or not np.isfinite([old_anchor, dt, effort_price, action_bound,
                                current_shift, direct_coefficient]).all()
            or not np.isfinite(maps).all() or not np.isfinite(baseline).all()):
        raise ValueError("compatible finite one-action model and declared horizon required")
    weights = np.r_[np.full(lookahead, dt), 1.0]
    roots = np.sqrt(weights)
    if objective == "tracking_soft":
        M = roots[:, None] * maps[:lookahead + 1, 0]
        a, c = roots * current_shift, np.zeros(p)
    else:
        M, a = np.zeros((0, p)), np.zeros(0)
        c = direct_coefficient * (weights @ maps[:lookahead + 1, 0])
    N = roots[:, None] * maps[:lookahead + 1, 1]
    b = roots * (baseline[:lookahead + 1, 1] - old_anchor)
    G, q = np.zeros((0, p)), np.zeros(0)
    if objective == "direct_hard":
        G, q = maps[1:, 1].copy(), old_anchor - baseline[1:, 1]
    return {"M": M, "a": a, "N": N, "b": b, "c": c, "constant": 0.0,
            "regularization": dt * effort_price, "bound": np.full(p, action_bound / np.sqrt(p)),
            "G": G, "q": q}


def plan_action(model, *, objective, lookahead, old_anchor, dt=0.02,
                effort_price=0.1, action_bound=1.0, current_shift=0.03,
                direct_coefficient=0.03, feasibility_tolerance=1e-9,
                gap_tolerance=1e-9, max_iterations=300, ftol=1e-13):
    problem = action_problem(model, objective=objective, lookahead=lookahead,
                             old_anchor=old_anchor, dt=dt, effort_price=effort_price,
                             action_bound=action_bound, current_shift=current_shift,
                             direct_coefficient=direct_coefficient)
    result = solve_bounded_problem(**problem, feasibility_tolerance=feasibility_tolerance,
                                   gap_tolerance=gap_tolerance, max_iterations=max_iterations,
                                   ftol=ftol)
    horizon, p = len(model["loss_maps"]) - 1, model["loss_maps"].shape[2]
    actions, fields, losses = np.zeros((0, p)), np.zeros((0, 2)), np.zeros((0, 2))
    if result["u"].shape == (p,) and np.isfinite(result["u"]).all():
        actions = np.zeros((horizon, p))
        actions[0] = result["u"]
        fields = np.einsum("kij,j->ki", model["loss_maps"], result["u"])
        losses = model["reference_observations"] + fields
    return {**result, "status": result["record"]["status"], "actions": actions,
            "fields": fields, "losses": losses, "problem": problem}


def score_common(fields, actions, reference_observations, old_anchor, *, dt=0.02,
                 effort_price=0.1, current_shift=0.03, direct_coefficient=0.03,
                 feasibility_tolerance=1e-9):
    """Common H-step score; inputs are loss deviations from the zero reference."""
    fields, actions, baseline = (np.asarray(v, dtype=np.float64)
                                for v in (fields, actions, reference_observations))
    horizon = len(actions)
    if (actions.ndim != 2 or fields.shape != (horizon + 1, 2)
            or baseline.shape != fields.shape or horizon < 1
            or min(dt, effort_price, current_shift, direct_coefficient, feasibility_tolerance) <= 0
            or not np.isfinite([old_anchor, dt, effort_price, current_shift,
                                direct_coefficient, feasibility_tolerance]).all()
            or not all(np.isfinite(v).all() for v in (fields, actions, baseline))):
        raise ValueError("finite common-horizon losses, actions and reference required")
    weights = np.r_[np.full(horizon, dt), 1.0]
    excess = baseline[:, 1] + fields[:, 1] - old_anchor
    direct = direct_coefficient * float(weights @ fields[:, 0])
    tracking = 0.5 * float(weights @ np.square(fields[:, 0] + current_shift))
    forgetting = 0.5 * float(weights @ np.square(np.maximum(excess, 0.0)))
    effort = 0.5 * dt * effort_price * float(np.square(actions).sum())
    return {"direct_soft_total": direct + forgetting + effort,
            "tracking_soft_total": tracking + forgetting + effort,
            "direct_current": direct, "tracking_current": tracking,
            "forgetting": forgetting, "effort": effort,
            "initial_old_excess": float(excess[0]),
            "maximum_future_old_excess": float(excess[1:].max()),
            "terminal_old_excess": float(excess[-1]),
            "future_old_violation_steps": int(np.count_nonzero(excess[1:] > feasibility_tolerance)),
            "future_retention_within_tolerance": bool(np.max(excess[1:]) <= feasibility_tolerance),
            "terminal_current_nll": float(baseline[-1, 0] + fields[-1, 0]),
            "terminal_old_nll": float(baseline[-1, 1] + fields[-1, 1]),
            "feasibility_tolerance": feasibility_tolerance,
            "scope": "shared one-action horizon; empirical probe values, no independent-task retention guarantee"}
