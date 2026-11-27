"""Bounded exact prospective Head/Adam probe verification, with no publication.

The numerical certificate covers one frozen future action sequence and the
supplied old probe, not unseen examples or subsequently replanned actions.
Every trial clones the complete optimizer/sampler state. A zero intervention
still advances Adam and must pass the same check; rejection never advances it.
The caller must retain the original warmup threshold, not re-anchor after drift.
"""

import hashlib
import time

import numpy as np

from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import normalize_features


def verify_action(state, development, candidate, old_anchor, *, horizon=8, dt=0.02,
                  action_bound=None, backtracking=(1.0, 0.5, 0.25, 0.125, 0.0),
                  candidate_status="qualified", rollback_state=None, commit_steps=1):
    """Return a certified frozen rollout, or an explicit no-advance outcome.

    ``candidate`` is a p-vector velocity (one impulse then zero suffix), or an
    H-by-p velocity sequence. Each trial scales the entire sequence. The first
    passing trial is accepted; up to nine predeclared scales are permitted.
    ``action_bound`` has the V4 box convention abs(u_i)<=bound/sqrt(p).

    On certification, ``state`` is the complete terminal state and ``next_state``
    is the complete first-step state for MPC. ``commit_state`` is the complete
    checkpoint after ``commit_steps`` (default one). All H future probe losses must be
    <=old_anchor, with no numerical or scientific slack. The initial loss is
    reported separately: recovery does not retroactively certify an unsafe past.
    On rejection, both returned states preserve the input exactly. An explicit
    compatible rollback checkpoint may instead be restored if its probe passes;
    that is a stopped optimizer, not a certified H-step continuation. No caller
    state, optimizer clock, sampler or context is mutated by this function.
    The caller must pin that rollback to a predeclared prior checkpoint (normally
    warmup); compatibility and an earlier clock alone do not prove its history.
    """
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    if (type(state) is not CellTrainingState or not 1 <= state.parameter_count <= 4096
            or type(horizon) is not int or not 1 <= horizon <= 8
            or type(commit_steps) is not int or not 1 <= commit_steps <= horizon
            or type(dt) not in (int, float) or not np.isfinite(dt) or not 0 < dt <= 1
            or type(old_anchor) not in (int, float) or not np.isfinite(old_anchor) or old_anchor < 0
            or not isinstance(development, dict)
            or set(development) != {"current_train", "old_probe"}
            or candidate_status not in ("qualified", "tangent_infeasible", "unresolved")):
        raise ValueError("bounded complete state, original threshold and training/probe-only inputs required")
    pairs = {key: tuple(np.asarray(a).copy() for a in pair) for key, pair in development.items()}
    identities = {key: dataset_digest(*pair) for key, pair in pairs.items()}
    if (state.active_context != "current_train"
            or state.contexts.get("current_train") != identities["current_train"]
            or any(x.shape[1] != state.head.width or np.any(y >= state.head.classes)
                   for x, y in pairs.values())):
        raise ValueError("training context and probe class/feature coordinates must match the checkpoint")
    scales = np.asarray(backtracking, dtype=np.float64)
    if (scales.ndim != 1 or not 1 <= len(scales) <= 9 or not np.isfinite(scales).all()
            or scales[0] != 1 or np.any(scales < 0) or np.any(np.diff(scales) >= 0)):
        raise ValueError("one to nine decreasing nonnegative scales beginning at one required")
    p, before = state.parameter_count, state.digest()
    if action_bound is not None and (type(action_bound) not in (int, float)
            or not np.isfinite(action_bound) or action_bound <= 0):
        raise ValueError("positive finite action box required")
    actions = None
    if candidate_status == "qualified":
        actions = np.asarray(candidate, dtype=np.float64).copy()
        if actions.shape == (p,):
            actions = np.vstack((actions, np.zeros((horizon - 1, p))))
        if (actions.shape != (horizon, p) or not np.isfinite(actions).all()
                or (action_bound is not None and np.any(np.abs(actions) > action_bound / np.sqrt(p)))):
            raise ValueError("finite frozen action sequence within its declared box required")
    elif candidate is not None:
        raise ValueError("an unavailable upstream plan must not contain an executable action")
    normalized, labels = normalize_features(pairs["old_probe"][0]), pairs["old_probe"][1]

    def loss(current):
        value = float(current.head.loss_gradients(normalized, labels, 0.0)[0])
        if not np.isfinite(value):
            raise ValueError("nonfinite old-probe loss")
        return value

    initial_loss = loss(state)
    record = {"schema": "hepta.cell-field-prospective-safety.v5", "status": "rejected",
        "candidate_status": candidate_status, "certified": False, "horizon": horizon,
        "dt": dt, "old_anchor": float(old_anchor), "threshold_slack": 0.0,
        "requested_commit_steps": commit_steps, "parameter_count": p,
        "initial_state_sha256": before, "initial_old_loss": initial_loss,
        "initial_old_excess": initial_loss - old_anchor,
        "initial_within_threshold": initial_loss <= old_anchor,
        "data_sha256": identities, "backtracking": scales.tolist(),
        "action_bound": action_bound, "attempts": [], "verified_optimizer_steps": 0,
        "certified_optimizer_steps": 0, "committed_optimizer_steps": 0,
        "authority": "DENY_ALL", "production_authority": False,
        "scope": "numerical future probe certificate for identical context, sampler and frozen actions"}
    fallback, fallback_loss = state.clone(), initial_loss
    if rollback_state is not None:
        if (type(rollback_state) is not CellTrainingState or rollback_state.bindings != state.bindings
                or rollback_state.protocol != state.protocol or rollback_state.contexts != state.contexts
                or rollback_state.active_context != state.active_context
                or rollback_state.names != state.names or rollback_state.parameter_count != p
                or any(getattr(rollback_state.head, key) != getattr(state.head, key)
                       for key in ("width", "classes", "mode", "rank", "max_parameters"))
                or rollback_state.step_count > state.step_count):
            raise ValueError("rollback must be an explicitly supplied compatible complete prior checkpoint")
        rollback_loss = loss(rollback_state)
        record["rollback_checkpoint_sha256"] = rollback_state.digest()
        record["rollback_old_loss"] = rollback_loss
        record["rollback_provenance"] = "caller-pinned prior checkpoint; historical ancestry not independently verified"
        if rollback_loss <= old_anchor:
            fallback, fallback_loss = rollback_state.clone(), rollback_loss
    result = {"record": record, "state": fallback, "next_state": fallback.clone(),
        "commit_state": fallback.clone(),
        "arrays": {"states": fallback.vector()[None, :], "old_losses": np.array([fallback_loss]),
                   "actions": np.zeros((0, p))}, "receipts": []}
    if candidate_status != "qualified":
        record["status"] = "not_executed_" + candidate_status
    else:
        record["candidate_actions_sha256"] = hashlib.sha256(actions.tobytes()).hexdigest()
        for scale in (scales if np.any(actions) else scales[:1]):
            trial_start, trial_cpu = time.perf_counter_ns(), time.process_time_ns()
            current, sequence = state.clone(), scale * actions
            vectors, losses, receipts = [current.vector()], [initial_loss], []
            next_state, commit_state = None, None
            attempt = {"scale": float(scale), "status": "unresolved", "completed_steps": 0}
            try:
                for k in range(horizon):
                    receipts.append(current.advance(*pairs["current_train"], intervention=dt * sequence[k]))
                    attempt["completed_steps"] += 1
                    vectors.append(current.vector())
                    losses.append(loss(current))
                    if k == 0:
                        next_state = current.clone()
                    if k + 1 == commit_steps:
                        commit_state = current.clone()
                maximum = max(losses[1:]) - old_anchor
                passed = all(value <= old_anchor for value in losses[1:])
                attempt.update(status="certified" if passed else "unsafe", maximum_future_excess=maximum,
                               terminal_state_sha256=current.digest())
                if passed:
                    result.update(state=current, next_state=next_state, commit_state=commit_state, receipts=receipts,
                        arrays={"states": np.asarray(vectors), "old_losses": np.asarray(losses),
                                "actions": sequence.copy()})
                    record.update(status="certified", certified=True, accepted_scale=float(scale),
                                  certified_optimizer_steps=horizon, maximum_future_excess=maximum,
                                  first_step_state_sha256=next_state.digest(),
                                  commit_state_sha256=commit_state.digest(),
                                  accepted_actions_sha256=hashlib.sha256(sequence.tobytes()).hexdigest())
            except Exception as error:
                attempt["error"] = {"type": type(error).__name__, "message": str(error)}
            attempt.update(old_losses=losses, cpu_ns=time.process_time_ns() - trial_cpu,
                           wall_ns=time.perf_counter_ns() - trial_start)
            record["verified_optimizer_steps"] += attempt["completed_steps"]
            record["attempts"].append(attempt)
            if record["certified"]:
                break
        if not record["certified"] and any(a["status"] == "unresolved" for a in record["attempts"]):
            record["status"] = "unresolved"
    if not record["certified"] and fallback.digest() != before:
        record.update(status="rolled_back", rejected_plan_status=record["status"],
                      rollback_scope="complete prior optimizer state restored; no optimizer advance")
    record.update(returned_state_sha256=result["state"].digest(),
                  returned_state_within_threshold=bool(result["arrays"]["old_losses"][-1] <= old_anchor),
                  cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - began)
    if state.digest() != before:
        raise RuntimeError("prospective verification mutated its common checkpoint")
    return result
