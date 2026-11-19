"""Independent actual-query/transition replay and atomic filter-result checks."""

import time

import numpy as np

from cell_field_filter_observer_v8 import array_hash, pair_key
from cell_field_state import dataset_digest
from cell_field_stop_inputs_v8 import require
from cell_learning_models import normalize_features


def old_losses(state, panels):
    return np.asarray([state.head.loss_gradients(normalize_features(x), y, 0.)[0] for x, y in panels])


def actual_errors(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "error" and item:
                yield item
            else:
                yield from actual_errors(item)
    elif isinstance(value, list):
        for item in value:
            yield from actual_errors(item)


def audit_observer(observer):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    require(not observer.overflow and not observer.observation_errors and not observer.head_errors and observer.raw_panel_calls == 0,
        "all observed queries captured with exact normalized panel identities")
    panels = [(normalize_features(x), y) for x, y in observer.old_panels]
    original = observer.origin
    for row in observer.queries:
        theta = observer.points[row["point"]]
        require(array_hash(theta) == row["parameter_sha256"] and row["l2"] == 0., "unmodified old-loss query parameters")
        head = original.head_from_vector(np.r_[theta, original.vector()[original.parameter_count:]])
        x, y = panels[row["panel"]]
        value, gradients = head.loss_gradients(x, y, 0.)
        gradient = np.concatenate([gradients[n].ravel() for n in original.names])
        require(np.isfinite(value) and value == row["loss"] and array_hash(gradient) == row["gradient_sha256"]
            and pair_key(x, y) == row["normalized_panel_sha256"], "every old-panel value and gradient independently reproduced")
    for row in observer.transitions:
        require(row["dataset_sha256"] == dataset_digest(*observer.train) and row["indices"] is None
            and row["mask"] is None, "all diagnostic Adam calls use the same full-batch context")
        replay = row["before"].clone()
        try:
            receipt = replay.advance(*observer.train, intervention=row["intervention"])
        except Exception as error:
            require(row["error"] == {"type": type(error).__name__, "message": str(error)}, "exact recorded optimizer exception")
        else:
            require(row["error"] is None and receipt == row["receipt"], "every actual optimizer receipt independently reproduced")
        require(replay.digest() == row["after"].digest() and np.array_equal(replay.vector(), row["after"].vector()),
            "every complete prospective Adam state independently reproduced")
    return {"status": "PASS", "old_value_gradient_queries_replayed": len(observer.queries),
        "actual_optimizer_transitions_replayed": len(observer.transitions),
        "observed_actual_errors": [row["error"] for row in observer.transitions if row["error"]],
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began}


def audit_filter(origin, train, panels, intended, anchors, result, observer, *, horizon, dt, action_bound, effort_price):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    query_audit = audit_observer(observer)
    record, actions = result["record"], np.asarray(result["actions"])
    p, before = origin.parameter_count, origin.digest()
    require(record["status"] in ("certified", "rejected", "unresolved")
        and record["certified"] == (record["status"] == "certified")
        and record["initial_state_sha256"] == before and record["original_old_anchors"] == anchors.tolist()
        and record["threshold_slack"] == 0. and record["horizon"] == horizon
        and record["dt"] == dt and record["action_bound"] == action_bound
        and record["committed_optimizer_steps"] == 0, "original zero-slack filter contract and diagnostic-only authority")
    require(record["verified_optimizer_steps"] == len(observer.transitions)
        and record["panel_head_evaluations"] == len(observer.queries), "actual optimizer and old-constraint query ledger agrees with self-report")
    expected = horizon if record["certified"] else 0
    require(actions.shape == (expected, p) and len(result["states"]) == expected+1
        and len(result["receipts"]) == expected and np.isfinite(actions).all()
        and np.all(np.abs(actions) <= action_bound/np.sqrt(p)), "atomic complete sequence and unchanged physical action box")
    values = np.asarray(result["old_losses"])
    require(values.shape == (expected+1, 4) and np.isfinite(values).all(), "finite actual retention path")
    current, vectors, digests = origin.clone(), [origin.vector()], [before]
    for step in range(expected+1):
        if step:
            receipt = current.advance(*train, intervention=dt*actions[step-1])
            require(receipt == result["receipts"][step-1], "complete independently replayed accepted receipt")
            vectors.append(current.vector()); digests.append(current.digest())
        require(current.digest() == result["states"][step].digest()
            and np.array_equal(current.vector(), result["states"][step].vector())
            and np.array_equal(old_losses(current, panels), values[step]), "exact accepted state and actual four-panel losses")
        if step:
            require(np.all(values[step] <= anchors), "all accepted steps satisfy all four original anchors without slack")
    require(current.digest() == result["state"].digest() == record["returned_state_sha256"], "returned complete state")
    if not record["certified"]:
        require(current.digest() == before and record["certified_optimizer_steps"] == 0, "no partial failed block adopted")
    errors = list(actual_errors(record))
    return {"status": "PASS", "actual_errors": errors,
        "accepted_steps": expected, "origin_state_sha256": before, "state_sha256": digests,
        "terminal_state_sha256": current.digest(), "maximum_future_old_excess": None if not expected else float((values[1:]-anchors).max()),
        "action_difference_l2": None if not expected else float(np.linalg.norm(actions-intended)),
        "parameter_action_penalty": float(.5*dt*effort_price*np.square(actions).sum()),
        "query_and_transition_replay": query_audit,
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began}, np.asarray(vectors)
