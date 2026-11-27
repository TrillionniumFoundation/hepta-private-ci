"""Posthoc same-state feasibility witnesses; never changes the primary V7 run.

Inputs are training and reused planning panels only. Every branch starts from
the same complete state and retains the original four warmup thresholds.
"""

import time

import numpy as np

from cell_field_planner_v7 import make_plan
from cell_field_repair_v7 import panel_losses, repair_sequence
from cell_field_state import _array_digest, dataset_digest


METHODS = ("full", "loss2", "future_field")


def _store_trace(arrays, name, actions, states, losses):
    arrays[name+"_actions"] = np.asarray(actions).reshape(-1, states[0].parameter_count)
    arrays[name+"_states"] = np.asarray([state.vector() for state in states])
    arrays[name+"_old_losses"] = np.asarray(losses)
    return {"state_sha256": [state.digest() for state in states],
        "actions_sha256": _array_digest(arrays[name+"_actions"]),
        "prospective_steps": len(actions)}


def _check_repaired(origin, train, panels, anchors, verified, dt, counter):
    actions = np.asarray(verified["actions"], dtype=np.float64)
    if (actions.shape != (8, origin.parameter_count) or len(verified["states"]) != 9
            or len(verified["receipts"]) != 8 or verified["states"][0].digest() != origin.digest()):
        raise ValueError("certified repair lost its full H8 census")
    current, states = origin.clone(), [origin.clone()]
    losses = [panel_losses(current.head, panels)]
    for k, action in enumerate(actions):
        receipt = current.advance(*train, intervention=dt*action)
        counter["independent_replay_updates"] += 1
        values = panel_losses(current.head, panels)
        if (receipt != verified["receipts"][k] or current.digest() != verified["states"][k+1].digest()
                or not np.isfinite(values).all() or np.any(values > anchors)):
            raise ValueError("repaired actual action/state/receipt/retention replay differs")
        states.append(current.clone()); losses.append(values)
    if current.digest() != verified["state"].digest():
        raise ValueError("certified terminal checkpoint differs")
    return actions, states, losses


def parameter_hold(origin, train, old_panels, anchors, configuration):
    """Try the uniquely specified Adam-cancelling action, with no box expansion."""
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    dt = configuration["dt"]
    bound = configuration["action_bound"]/np.sqrt(origin.parameter_count)
    before = origin.digest()
    current, states, actions, receipts = origin.clone(), [origin.clone()], [], []
    losses = [panel_losses(current.head, old_panels)]
    record = {"status": "unresolved", "certified": False, "horizon": 8,
        "optimizer_updates": 0, "certified_optimizer_steps": 0,
        "original_committed_optimizer_steps": 0, "parameter_hold_exact": True,
        "original_old_anchors": np.asarray(anchors).tolist(), "threshold_slack": 0.,
        "initial_state_sha256": before, "maximum_parameter_drift": 0.}
    try:
        if not np.isfinite(losses[0]).all() or np.any(losses[0] > anchors):
            raise ValueError("original stopped checkpoint already violates a planning panel")
        for step in range(8):
            base = current.clone()
            base.advance(*train)
            record["optimizer_updates"] += 1
            action = (current.parameter_vector()-base.parameter_vector())/dt
            if not np.isfinite(action).all() or np.any(np.abs(action) > bound):
                record.update(status="hold_outside_original_box", failed_at_step=step,
                    required_maximum_coordinate=float(np.max(np.abs(action))), coordinate_bound=float(bound))
                break
            following = current.clone()
            receipt = following.advance(*train, intervention=dt*action)
            record["optimizer_updates"] += 1
            values = panel_losses(following.head, old_panels)
            drift = float(np.max(np.abs(following.parameter_vector()-origin.parameter_vector())))
            record["maximum_parameter_drift"] = max(record["maximum_parameter_drift"], drift)
            record["parameter_hold_exact"] &= np.array_equal(following.parameter_vector(), origin.parameter_vector())
            if not np.isfinite(values).all() or np.any(values > anchors):
                record.update(status="hold_failed_actual_retention", failed_at_step=step,
                    failed_old_losses=values.tolist(), failed_state_sha256=following.digest(),
                    failed_receipt=receipt)
                break
            current = following
            states.append(current.clone()); actions.append(action); receipts.append(receipt); losses.append(values)
        if len(actions) == 8:
            record.update(status="certified", certified=True, certified_optimizer_steps=8)
    except Exception as error:
        record.update(status="unresolved", error={"type": type(error).__name__, "message": str(error)})
    record.update(prospective_safe_steps=len(actions), cpu_ns=time.process_time_ns()-cpu,
        wall_ns=time.perf_counter_ns()-wall, receipts=receipts)
    if origin.digest() != before:
        raise RuntimeError("hold diagnostic mutated its original checkpoint")
    return {"record": record, "states": states, "actions": np.asarray(actions).reshape(-1, origin.parameter_count),
        "losses": losses, "state": current if record["certified"] else origin.clone()}


def diagnose_origin(origin, train, current_panels, old_panels, anchors, configuration):
    """Run the three unchanged H8 planners and the separately declared hold."""
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    before, anchors = origin.digest(), np.asarray(anchors, dtype=np.float64)
    if (origin.protocol["sampler"] != "full_batch" or len(current_panels) != 4 or len(old_panels) != 4
            or anchors.shape != (4,) or not np.isfinite(anchors).all()
            or origin.contexts.get(origin.active_context) != dataset_digest(*train)):
        raise ValueError("complete original state and four current/old planning panels required")
    panels = list(current_panels)+list(old_panels)
    options = {key: configuration[key] for key in ("dt", "effort_price", "action_bound",
        "old_weight", "current_dispersion", "relinearizations")}
    records, arrays, plans, targets = {}, {}, {}, {}
    for method in METHODS:
        branch_cpu, branch_wall = time.process_time_ns(), time.perf_counter_ns()
        row = {"status": "unresolved", "certified": False, "independent_replay_updates": 0,
            "initial_state_sha256": before, "original_committed_optimizer_steps": 0}
        try:
            plan = make_plan(origin, train, panels, anchors, method=method, horizon=8, **options)
            plans[method], row["plan"] = plan, plan["record"]
            for key in ("maps", "reference_states", "reference_observations", "nominal_reference_actions"):
                if plan.get(key) is not None:
                    arrays[method+"_"+key] = plan[key]
            if plan["record"]["status"] != "qualified":
                row["status"] = "plan_"+plan["record"]["status"]
            else:
                verified = repair_sequence(origin, train, old_panels, plan["actions"], anchors,
                    horizon=8, dt=configuration["dt"], action_bound=configuration["action_bound"])
                row["repair"] = verified["record"]
                row["status"] = "repair_"+verified["record"]["status"]
                if verified["record"]["certified"]:
                    actions, states, losses = _check_repaired(origin, train, old_panels, anchors,
                        verified, configuration["dt"], row)
                    row.update(_store_trace(arrays, method, actions, states, losses))
                    row.update(status="certified", certified=True, receipts=verified["receipts"],
                        maximum_old_excess=float(np.max(np.asarray(losses[1:])-anchors)))
                    if method == "full":
                        targets[method] = actions, panel_losses(states[-1].head, panels)
        except Exception as error:
            row.update(status="unresolved", certified=False,
                error={"type": type(error).__name__, "message": str(error)})
        row.update(cpu_ns=time.process_time_ns()-branch_cpu, wall_ns=time.perf_counter_ns()-branch_wall)
        records[method] = row
    hold = parameter_hold(origin, train, old_panels, anchors, configuration)
    records["parameter_hold"] = hold["record"]
    records["parameter_hold"].update(_store_trace(arrays, "parameter_hold", hold["actions"], hold["states"], hold["losses"]))
    if hold["record"]["certified"]:
        targets["parameter_hold"] = hold["actions"], panel_losses(hold["state"].head, panels)
    predictions = []
    for target, (actions, actual) in targets.items():
        for method, plan in plans.items():
            if any(plan.get(key) is None for key in ("maps", "reference_observations", "nominal_reference_actions")):
                continue
            row = {"target": target, "predictor": method, "status": "unavailable"}
            try:
                nominal, maps = plan["nominal_reference_actions"], plan["maps"]
                predicted = plan["reference_observations"][-1]+np.einsum("kqp,kp->q", maps, actions-nominal)
                if not np.isfinite(predicted).all():
                    raise ValueError("nonfinite diagnostic terminal prediction")
                row.update(status="computed", executed_actions_sha256=_array_digest(actions),
                    nominal_actions_sha256=_array_digest(nominal), reference_states_sha256=_array_digest(plan["reference_states"]),
                    action_deviation_l2=float(np.linalg.norm(actions-nominal)),
                    predicted_terminal_panels=predicted.tolist(), actual_terminal_panels=actual.tolist(),
                    error=(predicted-actual).tolist(), rmse=float(np.sqrt(np.mean((predicted-actual)**2))))
            except Exception as error:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
            predictions.append(row)
    if origin.digest() != before:
        raise RuntimeError("diagnostic altered its original complete state")
    return {"record": {"schema": "hepta.loss2-stop-diagnostic.v7", "initial_state_sha256": before,
        "original_old_anchors": anchors.tolist(), "configuration": configuration, "branches": records,
        "full_actual_safe_witness": records["full"]["certified"],
        "hold_actual_safe_witness": records["parameter_hold"]["certified"],
        "terminal_prediction_errors": predictions, "prediction_scope": "same executed actions; each predictor uses its own recorded final nominal; reference differences are not pure compression effects",
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall,
        "global_nonlinear_infeasibility_claimed": False, "scientific_acceptance": False,
        "selection_labels_used": False, "primary_run_modified": False}, "arrays": arrays}
