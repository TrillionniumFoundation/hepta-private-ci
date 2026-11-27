"""Bounded local search for four actual old-panel constraints, without risk access.

Every accepted action is an observed zero-slack feasible point. A failed finite
search is not a proof of global infeasibility. The phase-II objective only
measures distance from the supplied proposal, never current/future task loss.
"""

import hashlib

import numpy as np
from scipy.optimize import minimize


class SearchBudgetExhausted(Exception):
    pass


class InteriorFound(Exception):
    pass


def joint_project(intended, anchors, bound, oracle, *, initial=None, budget=64,
                  inward_margin=1e-9):
    intended = np.asarray(intended, dtype=np.float64)
    anchors = np.asarray(anchors, dtype=np.float64)
    if (intended.ndim != 1 or not 1 <= intended.size <= 4096
            or anchors.shape != (4,) or not np.isfinite(anchors).all()
            or not np.isfinite(intended).all() or not np.isfinite(bound) or bound <= 0
            or np.any(np.abs(intended) > bound) or type(budget) is not int
            or budget != 64 or inward_margin != 1e-9):
        raise ValueError("fixed V8 search budget, margin, four thresholds and bounded proposal required")
    trials, cache, solvers = [], {}, []
    best, phase, failure = None, "intended", None

    def measure(raw):
        nonlocal best
        raw = np.asarray(raw, dtype=np.float64)
        if raw.shape != intended.shape or not np.isfinite(raw).all():
            raise ValueError("nonfinite or malformed solver action")
        action = np.clip(raw, -bound, bound)
        key = action.tobytes()
        if key in cache:
            return cache[key]
        if len(trials) >= budget:
            raise SearchBudgetExhausted()
        try:
            values, gradients = (initial if not trials and initial is not None else oracle(action))
            values, gradients = np.asarray(values), np.asarray(gradients)
            if (values.shape != (4,) or gradients.shape != (4, intended.size)
                    or not np.isfinite(values).all() or not np.isfinite(gradients).all()):
                raise ValueError("four finite actual losses and action gradients required")
        except Exception as error:
            trials.append({"phase": phase, "action": action.tolist(),
                "error": {"type": type(error).__name__, "message": str(error)}})
            raise
        safe = bool(np.all(values <= anchors))
        distance = float(np.square(action-intended).sum())
        trials.append({"phase": phase, "action": action.tolist(),
            "action_sha256": hashlib.sha256(key).hexdigest(),
            "same_box_projection_linf": float(np.max(np.abs(raw-action))),
            "old_losses": values.tolist(), "within_threshold": safe,
            "gradient_sha256": hashlib.sha256(gradients.tobytes()).hexdigest(),
            "distance_squared_from_intended": distance})
        cache[key] = (values.copy(), gradients.copy())
        if safe and (best is None or distance < best[0]):
            best = (distance, action.copy(), values.copy(), len(trials)-1)
        if phase == "phase_one" and np.max(values-anchors) <= -inward_margin:
            raise InteriorFound()
        return cache[key]

    try:
        measure(intended)
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    if failure is None and best is None:
        phase = "phase_one"
        values, _ = cache[intended.tobytes()]
        initial_z = np.r_[intended, np.max(values-anchors)]

        def constraints(z):
            values, _ = measure(z[:-1])
            return z[-1]-(values-anchors)

        def jacobian(z):
            _, gradients = measure(z[:-1])
            return np.column_stack((-gradients, np.ones(4)))

        try:
            solved = minimize(lambda z: float(z[-1]), initial_z,
                jac=lambda z: np.r_[np.zeros(intended.size), 1.], method="SLSQP",
                bounds=[(-bound, bound)]*intended.size+[(None, None)],
                constraints={"type": "ineq", "fun": constraints, "jac": jacobian},
                options={"maxiter": 48, "ftol": 1e-12})
            solvers.append({"phase": phase, "status": int(solved.status),
                "success": bool(solved.success), "iterations": int(solved.nit),
                "message": str(solved.message)})
            measure(solved.x[:-1])
        except (SearchBudgetExhausted, InteriorFound) as stop:
            solvers.append({"phase": phase, "stop": type(stop).__name__})
        except Exception as error:
            failure = {"type": type(error).__name__, "message": str(error)}
    if failure is None and best is not None and best[0] > 0 and len(trials) < budget:
        phase = "phase_two"
        scale = max(intended.size*bound*bound, 1e-300)

        def constraints(action):
            values, _ = measure(action)
            return anchors-inward_margin-values

        def jacobian(action):
            return -measure(action)[1]

        try:
            solved = minimize(lambda action: .5*float(np.square(action-intended).sum())/scale,
                best[1], jac=lambda action: (action-intended)/scale, method="SLSQP",
                bounds=[(-bound, bound)]*intended.size,
                constraints={"type": "ineq", "fun": constraints, "jac": jacobian},
                options={"maxiter": 48, "ftol": 1e-12})
            solvers.append({"phase": phase, "status": int(solved.status),
                "success": bool(solved.success), "iterations": int(solved.nit),
                "message": str(solved.message)})
            measure(solved.x)
        except SearchBudgetExhausted as stop:
            solvers.append({"phase": phase, "stop": type(stop).__name__})
        except Exception as error:
            failure = {"type": type(error).__name__, "message": str(error)}
    record = {"trials": trials, "solver_records": solvers,
        "unique_search_panel_batches": len(trials), "search_batch_cap": budget,
        "inward_search_margin": inward_margin, "accepted_threshold_slack": 0.,
        "global_feasibility": "unknown", "nearest_action_optimality": "not_certified"}
    if failure is not None:
        record.update(status="unresolved", error=failure, reason="actual-oracle or solver error retained")
        return None, None, record
    if best is None:
        record.update(status="rejected", reason="no feasible action observed within fixed local search")
        return None, None, record
    record.update(status="certified", selected_trial=best[3],
        distance_squared_from_intended=best[0], global_feasibility="feasible_witness_observed")
    return best[1], best[2], record
