"""Four-panel bounded tangent QP with independently checked optimality.

The dual has four variables. Solver success is insufficient: primal bounds,
stationarity and complementary slackness are recomputed. An infeasibility
claim requires a separating mixture of the original four inequalities.
The panel dispersion is also linearized at the nominal losses; this is not
the exact norm-plus-quadratic optimization of the predicted panel loss vector.
"""

import time

import numpy as np
from scipy.optimize import linprog, minimize


def objective_weights(losses, old_weight, dispersion):
    losses = np.asarray(losses, dtype=np.float64)
    if (losses.shape != (8,) or not np.isfinite(losses).all()
            or not 0 <= old_weight <= 10 or not 0 <= dispersion <= .5):
        raise ValueError("eight finite panel losses and bounded objective weights required")
    centered = losses[:4]-losses[:4].mean()
    spread = np.sqrt(np.mean(centered**2)+1e-12)
    weights = np.r_[(1+dispersion*centered/spread)/4, np.full(4, old_weight/4)]
    value = losses[:4].mean()+dispersion*spread+old_weight*losses[4:].mean()
    if not np.isfinite(spread) or not np.isfinite(value) or not np.isfinite(weights).all():
        raise ValueError("derived panel objective must remain finite")
    return float(value), weights


def solve_terminal(maps, baseline, anchors, nominal_actions, *, dt=.02,
                   effort_price=.03, action_bound=4., old_weight=0., current_dispersion=0.):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    maps, baseline, anchors, nominal = [np.asarray(v, dtype=np.float64)
        for v in (maps, baseline, anchors, nominal_actions)]
    if (maps.ndim != 3 or maps.shape[1] != 8 or not 1 <= maps.shape[0] <= 8
            or not 1 <= maps.shape[2] <= 4096 or baseline.shape != (8,) or anchors.shape != (4,)
            or nominal.shape != (maps.shape[0], maps.shape[2])
            or not all(np.isfinite(v).all() for v in (maps, baseline, anchors, nominal))
            or not np.isfinite([dt, effort_price, action_bound]).all()
            or not 0 < dt <= 1 or not 0 < effort_price <= 100 or not 0 < action_bound <= 1e6):
        raise ValueError("finite bounded eight-output response and absolute nominal actions required")
    value, weights = objective_weights(baseline, old_weight, current_dispersion)
    h, _, p = maps.shape
    c = np.einsum("i,kip->kp", weights, maps).ravel()
    normals = maps[:, 4:, :].transpose(1, 0, 2).reshape(4, h*p)
    q = anchors-baseline[4:]+normals@nominal.ravel()
    regularization, bound = dt*effort_price, action_bound/np.sqrt(p)
    if (not np.isfinite([regularization, bound]).all() or regularization <= 0 or bound <= 0
            or not all(np.isfinite(v).all() for v in (c,normals,q))):
        raise ValueError("derived tangent objective and bounds must remain finite and positive")
    record = {"schema": "hepta.cell-field-panel-qp.v7", "status": "unresolved",
        "horizon": h, "control_dimension": h*p, "response_coordinates": 8,
        "old_panel_constraints": 4, "old_weight": old_weight,
        "current_dispersion": current_dispersion, "effort_price": effort_price,
        "action_bound": action_bound, "dt": dt, "original_old_anchors": anchors.tolist(),
        "scope": "current/old risk and current dispersion linearized at nominal; local tangent QP; actual nonlinear path verified separately"}
    dual = np.zeros(4)
    scale = np.maximum(np.linalg.norm(normals, axis=1), 1e-15)
    n, rhs = normals/scale[:, None], q/scale
    if not all(np.isfinite(v).all() for v in (scale,n,rhs)):
        raise ValueError("constraint scaling must remain finite")

    def optimum(multiplier):
        return np.clip(-(c+n.T@multiplier)/regularization, -bound, bound)

    def negative_dual(multiplier):
        u = optimum(multiplier)
        linear = c+n.T@multiplier
        return float(-linear@u-.5*regularization*(u@u)+rhs@multiplier), rhs-n@u

    def certificate(multiplier):
        u = optimum(multiplier)
        original_dual = multiplier/scale
        residual = normals@u-q
        gradient = c+regularization*u+normals.T@original_dual
        stationarity = float(np.max(np.abs(u-np.clip(u-gradient, -bound, bound))))
        violation = float(max(0., np.max(residual)))
        complementarity = float(np.max(np.abs(original_dual*residual)))
        return u, original_dual, stationarity, violation, complementarity

    attempts = []
    if np.any(normals@optimum(dual) > q):
        for method in ("L-BFGS-B", "SLSQP"):
            options = ({"maxiter": 512, "maxls": 40, "ftol": 1e-15, "gtol": 1e-12}
                if method == "L-BFGS-B" else {"maxiter": 512, "ftol": 1e-14})
            result = minimize(negative_dual, dual, jac=True, method=method,
                bounds=[(0., 1e6)]*4, options=options)
            dual = np.asarray(result.x)
            dual_feasible = (dual.shape == (4,) and np.isfinite(dual).all()
                and np.all(dual >= 0) and np.all(dual <= 1e6))
            attempts.append({"method": method, "success": bool(result.success),
                "iterations": int(result.nit), "evaluations": int(result.nfev),
                "dual_candidate_feasible": bool(dual_feasible)})
            if dual_feasible:
                _, _, stationarity, violation, gap = certificate(dual)
                if stationarity <= 1e-10 and violation <= 1e-10 and gap <= 1e-8:
                    break
            else:
                dual = np.zeros(4)
    u, original_dual, stationarity, violation, gap = certificate(dual)
    record.update(attempts=attempts, stationarity=stationarity,
        maximum_constraint_violation=violation, complementary_slackness=gap,
        dual_multipliers=original_dual.tolist(),
        dual_feasible=bool(np.isfinite(original_dual).all() and np.all(original_dual >= 0)))
    qualified = (np.isfinite(u).all() and np.isfinite([stationarity, violation, gap]).all()
        and record["dual_feasible"] and stationarity <= 1e-10 and violation <= 1e-10 and gap <= 1e-8)
    if qualified:
        actions = u.reshape(h, p)
        predicted = baseline+np.einsum("kip,kp->i", maps, actions-nominal)
        tangent_objective = float(value+c@(u-nominal.ravel())+.5*regularization*(u@u))
        penalty = float(.5*regularization*(u@u))
        if not np.isfinite(predicted).all() or not np.isfinite([tangent_objective,penalty]).all():
            raise ValueError("derived prediction and objective must remain finite")
        record.update(status="qualified", predicted_terminal_losses=predicted.tolist(),
            tangent_objective=tangent_objective, parameter_penalty=penalty)
    else:
        actions = None
        # min_t t with N*u-q <= t. Its nonnegative unit-sum dual mixture
        # supplies an independently evaluable lower bound over the whole box.
        phase = linprog(np.r_[np.zeros(h*p), 1.],
            A_ub=np.column_stack((normals, -np.ones(4))), b_ub=q,
            bounds=[(-bound, bound)]*(h*p)+[(None, None)], method="highs")
        record["phase_one_status"] = int(phase.status)
        if phase.success:
            mixture = np.maximum(0., -np.asarray(phase.ineqlin.marginals))
            mixture /= max(float(mixture.sum()), 1e-300)
            lower = float(-bound*np.abs(mixture@normals).sum()-mixture@q)
            record.update(separating_mixture=mixture.tolist(),
                verified_box_infeasibility_lower_bound=lower)
            if (np.isfinite(lower) and np.all(mixture >= 0)
                    and abs(float(mixture.sum())-1) <= 1e-12 and lower > 1e-10):
                record["status"] = "tangent_infeasible"
        record["reason"] = ("verified separating mixture" if record["status"] == "tangent_infeasible"
            else "bounded numerical solve did not supply required KKT certificate")
    record.update(cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-began)
    return {"actions": actions, "record": record}
