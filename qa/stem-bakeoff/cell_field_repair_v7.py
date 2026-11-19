"""Atomic nonlinear sequence verification against four original old panels.

All four inequalities must hold at every accepted Adam transition. A finite
repair search that fails remains unresolved as to global nonlinear feasibility.
Panels are reused empirical controller data, never independent certificates.
"""

import hashlib
import time

import numpy as np

from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import normalize_features


def panel_losses(head, panels):
    return np.asarray([head.loss_gradients(normalize_features(x), y, 0.)[0] for x, y in panels])


def _repair_step(state, train, panels, intended, anchors, dt, bound):
    p = state.parameter_count
    record = {"status": "unresolved", "trials": [], "optimizer_updates": 0,
        "initial_state_sha256": state.digest(), "repaired": False}

    def measure(vector, action, kind, length=None):
        if len(record["trials"]) >= 16:
            raise RuntimeError("fixed sixteen-panel-batch trial cap exceeded")
        head = state.head_from_vector(vector)
        values, gradients = [], []
        for x, y in panels:
            loss, g = head.loss_gradients(x, y, 0.)
            values.append(float(loss))
            gradients.append(np.concatenate([g[n].ravel() for n in state.names]))
        values, gradients = np.asarray(values), np.asarray(gradients)
        if not np.isfinite(values).all() or not np.isfinite(gradients).all():
            raise ValueError("nonfinite actual old-panel loss or gradient")
        record["trials"].append({"kind": kind, "length": length,
            "action_sha256": hashlib.sha256(action.tobytes()).hexdigest(),
            "old_losses": values.tolist(), "within_threshold": bool(np.all(values <= anchors))})
        return values, gradients

    def advance(action):
        current = state.clone()
        receipt = current.advance(*train, intervention=dt*action)
        record["optimizer_updates"] += 1
        return current, receipt

    try:
        first, receipt = advance(intended)
        values, gradients = measure(first.vector(), intended, "intended")
        if np.all(values <= anchors):
            record.update(status="certified", old_losses=values.tolist(), accepted_kind="intended")
            return first, intended.copy(), receipt, record
        base, _ = advance(np.zeros(p))
        base_vector = base.vector()
        planned = base_vector.copy()
        planned[:p] += dt*intended
        if not np.array_equal(planned, first.vector()):
            raise RuntimeError("prospective actions did not share the same Adam base")
        excess = np.maximum(values-anchors, 0.)
        gradient = (excess/excess.sum())@gradients
        magnitude = float(np.max(np.abs(gradient)))
        selected, selected_vector, selected_values, selected_length = None, None, None, None

        def trial(length, kind):
            action = np.clip(intended-length*gradient/magnitude, -bound, bound)
            vector = base_vector.copy()
            vector[:p] += dt*action
            losses, _ = measure(vector, action, kind, float(length))
            return action, vector, losses

        if magnitude > 0:
            left = 0.
            for j in range(12):
                length = bound*2.**j/64.
                action, vector, values = trial(length, "gradient_grid")
                if np.all(values <= anchors):
                    selected, selected_vector, selected_values, selected_length = action, vector, values, length
                    right = length
                    for _ in range(2):
                        middle = (left+right)/2
                        action, vector, values = trial(middle, "gradient_bisect")
                        if np.all(values <= anchors):
                            right = middle
                            selected, selected_vector, selected_values, selected_length = action, vector, values, middle
                        else:
                            left = middle
                    break
                left = length
        if selected is None:
            hold = (state.parameter_vector()-base_vector[:p])/dt
            record["parameter_hold_within_box"] = bool(np.isfinite(hold).all() and np.all(np.abs(hold) <= bound))
            if record["parameter_hold_within_box"]:
                vector = base_vector.copy()
                vector[:p] += dt*hold
                values, _ = measure(vector, hold, "parameter_hold")
                if np.all(values <= anchors):
                    selected, selected_vector, selected_values = hold, vector, values
        if selected is None:
            record.update(status="rejected", reason="bounded panel search exhausted; global feasibility unknown")
            return None, None, None, record
        current, receipt = advance(selected)
        expected = base.clone()
        expected.set_vector(selected_vector)
        if current.digest() != expected.digest():
            raise RuntimeError("selected repair differs from its complete prospective checkpoint")
        values, _ = measure(current.vector(), selected, "selected_replay", selected_length)
        if not np.array_equal(values, selected_values) or np.any(values > anchors):
            raise RuntimeError("selected repair failed exact four-panel replay")
        record.update(status="certified", repaired=True, old_losses=values.tolist(),
            accepted_kind="parameter_hold" if selected_length is None else "gradient_line",
            accepted_length=selected_length, terminal_state_sha256=current.digest())
        return current, selected, receipt, record
    except Exception as error:
        record.update(status="unresolved", error={"type": type(error).__name__, "message": str(error)})
        return None, None, None, record


def repair_sequence(state, train, old_panels, candidate, old_anchors, *, horizon=8,
                    dt=.02, action_bound=4.):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    anchors, actions = np.asarray(old_anchors, dtype=np.float64), np.asarray(candidate, dtype=np.float64)
    if (type(state) is not CellTrainingState or type(horizon) is not int or not 1 <= horizon <= 8
            or len(old_panels) != 4 or anchors.shape != (4,) or not np.isfinite(anchors).all()
            or np.any(anchors < 0) or not np.isfinite([dt, action_bound]).all()
            or not 0 < dt <= 1 or not 0 < action_bound <= 1e6
            or state.contexts.get(state.active_context) != dataset_digest(*train)):
        raise ValueError("complete selected training context and four fixed original thresholds required")
    p, bound, before = state.parameter_count, action_bound/np.sqrt(state.parameter_count), state.digest()
    if actions.shape != (horizon, p) or not np.isfinite(actions).all() or np.any(np.abs(actions) > bound):
        raise ValueError("finite intended H-by-p actions already inside the declared box required")
    identities = [dataset_digest(*panel) for panel in old_panels]
    panels = [(normalize_features(x), np.asarray(y)) for x, y in old_panels]
    initial = panel_losses(state.head, old_panels)
    record = {"schema": "hepta.cell-field-panel-repair.v7", "status": "rejected", "certified": False,
        "horizon": horizon, "dt": dt, "action_bound": action_bound,
        "initial_state_sha256": before, "original_old_anchors": anchors.tolist(),
        "initial_old_losses": initial.tolist(), "initial_within_threshold": bool(np.all(initial <= anchors)),
        "old_panel_sha256": identities, "threshold_slack": 0., "step_records": [],
        "verified_optimizer_steps": 0, "panel_head_evaluations": 4, "repaired_steps": 0,
        "prospective_safe_steps": 0, "certified_optimizer_steps": 0, "committed_optimizer_steps": 0,
        "trial_panel_batch_cap_per_step": 16, "authority": "DENY_ALL", "production_authority": False,
        "scope": "reused empirical four-panel finite search; no held-out retention or global feasibility claim"}
    result = {"record": record, "state": state.clone(), "states": [state.clone()],
        "actions": np.zeros((0, p)), "old_losses": initial[None, :], "receipts": []}
    current, states, accepted, losses, receipts = state.clone(), [state.clone()], [], [initial], []
    for k, intended in enumerate(actions):
        following, action, receipt, step = _repair_step(current, train, panels, intended, anchors, dt, bound)
        step["step"] = k
        record["step_records"].append(step)
        record["verified_optimizer_steps"] += step["optimizer_updates"]
        record["panel_head_evaluations"] += 4*len(step["trials"])
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
        raise RuntimeError("panel verifier mutated its input checkpoint")
    return result
