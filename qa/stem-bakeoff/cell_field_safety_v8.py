"""Common four-panel nonlinear safety filter with atomic H1..H8 verification.

The filter reads complete optimizer state and old-panel gradients for every
proposal method. Loss2 constrains the risk forecast, not the whole controller's
information. No empirical panel certificate implies independent retention.
"""

import time

import numpy as np

from cell_field_joint_search_v8 import joint_project
from cell_field_repair_v7 import panel_losses
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import normalize_features


def _repair_step(state, train, panels, intended, anchors, dt, bound):
    p = state.parameter_count
    record = {"status": "unresolved", "optimizer_updates": 0, "panel_batches": 0,
        "attempted_panel_head_evaluations": 0, "oracle_failures": [],
        "initial_state_sha256": state.digest(), "repaired": False,
        "intended_action": intended.tolist(), "search": None}

    def advance(action):
        current = state.clone()
        receipt = current.advance(*train, intervention=dt*action)
        record["optimizer_updates"] += 1
        return current, receipt

    def measure(vector, action):
        head = state.head_from_vector(vector)
        values, gradients = [], []
        for index, (x, y) in enumerate(panels):
            record["attempted_panel_head_evaluations"] += 1
            try:
                loss, gradient = head.loss_gradients(x, y, 0.)
            except Exception as error:
                record["oracle_failures"].append({"panel_index": index, "action": action.tolist(),
                    "error": {"type": type(error).__name__, "message": str(error)}})
                raise
            values.append(float(loss))
            gradients.append(dt*np.concatenate([gradient[n].ravel() for n in state.names]))
        record["panel_batches"] += 1
        values, gradients = np.asarray(values), np.asarray(gradients)
        if not np.isfinite(values).all() or not np.isfinite(gradients).all():
            raise ValueError("nonfinite actual old-panel loss or action gradient")
        return values, gradients

    try:
        first, receipt = advance(intended)
        values, gradients = measure(first.vector(), intended)
        record["intended_old_losses"] = values.tolist()
        if np.all(values <= anchors):
            record.update(status="certified", old_losses=values.tolist(),
                accepted_action=intended.tolist(), accepted_kind="intended",
                terminal_state_sha256=first.digest())
            return first, intended.copy(), receipt, record
        base, _ = advance(np.zeros(p))
        base_vector = base.vector()
        prospective = base_vector.copy()
        prospective[:p] += dt*intended
        if not np.array_equal(prospective, first.vector()):
            raise RuntimeError("intended and repair trials do not share the same Adam base")

        def oracle(action):
            vector = base_vector.copy()
            vector[:p] += dt*action
            return measure(vector, action)

        action, selected_losses, search = joint_project(intended, anchors, bound, oracle,
            initial=(values, gradients))
        record["search"] = search
        if action is None:
            record.update(status=search["status"], reason=search["reason"], global_feasibility="unknown")
            return None, None, None, record
        current, receipt = advance(action)
        expected = base.clone()
        vector = base_vector.copy()
        vector[:p] += dt*action
        expected.set_vector(vector)
        if current.digest() != expected.digest():
            raise RuntimeError("selected action changed its complete prospective checkpoint")
        replayed, _ = measure(current.vector(), action)
        if not np.array_equal(replayed, selected_losses) or np.any(replayed > anchors):
            raise RuntimeError("selected action failed exact zero-slack four-panel replay")
        record.update(status="certified", repaired=True, old_losses=replayed.tolist(),
            accepted_action=action.tolist(), accepted_kind="joint_actual_old_search",
            terminal_state_sha256=current.digest())
        return current, action, receipt, record
    except Exception as error:
        record.update(status="unresolved", global_feasibility="unknown",
            error={"type": type(error).__name__, "message": str(error)})
        return None, None, None, record


def repair_sequence(state, train, old_panels, candidate, old_anchors, *, horizon=8,
                    dt=.02, action_bound=4.):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    anchors, actions = np.asarray(old_anchors, dtype=np.float64), np.asarray(candidate, dtype=np.float64)
    if (type(state) is not CellTrainingState or state.protocol["sampler"] != "full_batch"
            or type(horizon) is not int or not 1 <= horizon <= 8 or len(old_panels) != 4
            or anchors.shape != (4,) or not np.isfinite(anchors).all() or np.any(anchors < 0)
            or not np.isfinite([dt, action_bound]).all() or not 0 < dt <= 1
            or not 0 < action_bound <= 1e6
            or state.contexts.get(state.active_context) != dataset_digest(*train)):
        raise ValueError("complete full-batch context and four unchanged old thresholds required")
    p, before = state.parameter_count, state.digest()
    bound = action_bound/np.sqrt(p)
    if actions.shape != (horizon, p) or not np.isfinite(actions).all() or np.any(np.abs(actions) > bound):
        raise ValueError("finite intended actions inside the original coordinate box required")
    panels = [(normalize_features(x), np.asarray(y)) for x, y in old_panels]
    initial = panel_losses(state.head, old_panels)
    record = {"schema": "hepta.cell-field-joint-old-filter.v8", "status": "rejected",
        "certified": False, "horizon": horizon, "dt": dt, "action_bound": action_bound,
        "initial_state_sha256": before, "original_old_anchors": anchors.tolist(),
        "initial_old_losses": initial.tolist(), "initial_within_threshold": bool(np.all(initial <= anchors)),
        "old_panel_sha256": [dataset_digest(*panel) for panel in old_panels],
        "threshold_slack": 0., "step_records": [], "verified_optimizer_steps": 0,
        "panel_head_evaluations": 4, "repaired_steps": 0, "prospective_safe_steps": 0,
        "certified_optimizer_steps": 0, "committed_optimizer_steps": 0,
        "unique_search_batch_cap_per_step": 64, "extra_selected_replay_batches": 1,
        "authority": "DENY_ALL", "production_authority": False,
        "scope": "shared full-state old-only finite search; no held-out retention or global optimality"}
    result = {"record": record, "state": state.clone(), "states": [state.clone()],
        "actions": np.zeros((0, p)), "old_losses": initial[None, :], "receipts": []}
    current, states, accepted, losses, receipts = state.clone(), [state.clone()], [], [initial], []
    for k, intended in enumerate(actions):
        following, action, receipt, step = _repair_step(current, train, panels, intended, anchors, dt, bound)
        step["step"] = k
        record["step_records"].append(step)
        record["verified_optimizer_steps"] += step["optimizer_updates"]
        record["panel_head_evaluations"] += step["attempted_panel_head_evaluations"]
        if step["status"] != "certified":
            record.update(status=step["status"], failed_at_step=k)
            break
        current = following
        states.append(current.clone())
        accepted.append(action)
        losses.append(np.asarray(step["old_losses"]))
        receipts.append(receipt)
        record["prospective_safe_steps"] += 1
        record["repaired_steps"] += int(step["repaired"])
    if len(accepted) == horizon:
        result.update(state=current, states=states, actions=np.asarray(accepted),
            old_losses=np.asarray(losses), receipts=receipts)
        record.update(status="certified", certified=True, certified_optimizer_steps=horizon,
            maximum_future_panel_excess=float(np.max(np.asarray(losses[1:])-anchors)))
    record.update(returned_state_sha256=result["state"].digest(),
        cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-began)
    if state.digest() != before:
        raise RuntimeError("joint filter mutated its input checkpoint")
    return result
