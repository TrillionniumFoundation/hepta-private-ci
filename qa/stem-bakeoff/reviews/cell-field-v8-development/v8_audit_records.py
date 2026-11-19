"""Independent V8 physical traces, retained controller preimages and source scores.

No policy planner or safety search is executed. Replays use the frozen physical
Adam/head only; controller and billing predicates below are independently stated.
"""

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path, compressed=False):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "ordinary recorded file required: "+str(path))
    with (gzip.open if compressed else open)(path, "rb") as stream:
        payload = stream.read((32 << 20)+1)
    require(len(payload) <= 32 << 20, "expanded record bound")
    return json.loads(payload)


def array_hash(value):
    value = np.ascontiguousarray(value)
    return digest(canonical([value.dtype.str, list(value.shape)])+value.tobytes())


def pair_hash(pair):
    return digest([array_hash(np.asarray(pair[0], dtype=np.float64)), array_hash(np.asarray(pair[1], dtype=np.int64))])


def errors(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "error" and item:
                yield item
            else:
                yield from errors(item)
    elif isinstance(value, list):
        for item in value:
            yield from errors(item)


def panel_losses(state, panels):
    values = []
    for x, y in panels:
        x = np.asarray(x, dtype=np.float64)
        x = x/np.maximum(np.sqrt(np.square(x).sum(axis=1, keepdims=True)), 1e-12)*np.sqrt(x.shape[1])
        values.append(state.head.loss_gradients(x, y, 0.)[0])
    return np.asarray(values)


def losses(state, pair):
    x, y = pair
    p = state.head.predict_proba(x)
    require(p.shape == (len(y), 4) and np.isfinite(p).all() and np.all(p >= 0)
        and np.allclose(p.sum(axis=1), 1., atol=1e-12, rtol=0), "finite normalized probabilities")
    return -np.log(np.maximum(p[np.arange(len(y)), y], np.finfo(float).tiny))


def expected_contract(warmup, inputs, anchors, policy, configuration, protocol_sha, source_sha):
    return {"schema": "hepta.cell-field-controller-contract.v8", "policy": policy,
        "protocol_sha256": protocol_sha, "controller_source_sha256": source_sha,
        "optimizer_origin_protocol_sha256": warmup.bindings["protocol_sha256"],
        "original_warmup_state_sha256": warmup.digest(), "warmup_step_count": warmup.step_count,
        "registered_steps": configuration["steps"], "parameter_count": warmup.parameter_count,
        "configuration": configuration, "training_sha256": pair_hash(inputs["split"]["current_train"]),
        "current_panel_sha256": [pair_hash(p) for p in inputs["current_panels"]],
        "old_panel_sha256": [pair_hash(p) for p in inputs["old_panels"]],
        "original_old_anchors": anchors.tolist(), "independent_online_certificate": False,
        "checkpoint_boundary": "committed step inside certified prefix; forecast tail is discarded at next plan",
        "forecast_tail_safety_claimed": False, "safety_filter": "single_ray_then_joint_v8",
        "proposal_rule": "risk_effort_box_v8"}


def check_portfolio(record):
    attempts = record["attempts"]
    require(record["schema"] == "hepta.cell-field-fixed-portfolio.v8" and 1 <= len(attempts) <= 2
        and [a["filter"] for a in attempts] == ["single_ray_v7", "joint_actual_old_v8"][:len(attempts)]
        and record["attempt_order"] == ["single_ray_v7", "joint_actual_old_v8"], "fixed old-first attempt order")
    require((len(attempts) == 1) == bool(attempts[0]["record"]["certified"]),
        "second filter is invoked exactly when first certificate fails")
    for attempt in attempts:
        inner = attempt["record"]
        require(inner["initial_state_sha256"] == record["initial_state_sha256"]
            and inner["original_old_anchors"] == record["original_old_anchors"]
            and inner["threshold_slack"] == record["threshold_slack"] == 0.
            and all(inner[k] == record[k] for k in ("horizon", "dt", "action_bound")),
            "all portfolio attempts use same origin and original zero-slack contract")
    selected = attempts[-1]
    require(record["selected_filter"] == selected["filter"]
        and all(record[k] == selected["record"][k] for k in
            ("status", "certified", "returned_state_sha256", "certified_optimizer_steps", "prospective_safe_steps")),
        "portfolio returns the selected complete sequence")
    for key in ("verified_optimizer_steps", "panel_head_evaluations"):
        require(record[key] == sum(a["record"][key] for a in attempts), "all failed filter workload remains charged")
    require(record["cpu_ns"] >= sum(a["record"]["cpu_ns"] for a in attempts) > 0
        and record["wall_ns"] >= sum(a["record"]["wall_ns"] for a in attempts) > 0,
        "whole portfolio includes each original paid attempt")
    require(record["discarded_safe_prefix_steps"] == sum(a["record"]["prospective_safe_steps"]
        for a in attempts if not a["record"]["certified"]), "discarded prefixes remain explicit")
    return {"attempts": len(attempts), "fallback": len(attempts) == 2,
        "selected": record["selected_filter"], "panel_queries": record["panel_head_evaluations"],
        "optimizer_calls": record["verified_optimizer_steps"]}


def check_snapshot(snapshot, state, step, contract, trace, record, actions):
    require(snapshot["schema"] == "hepta.cell-field-controller.v8" and snapshot["contract"] == contract,
        "complete immutable V8 contract")
    for key in ("policy", "protocol_sha256", "original_warmup_state_sha256", "warmup_step_count", "registered_steps"):
        require(snapshot[key] == contract[key], "contract duplicate: "+key)
    require(snapshot["full_state_sha256"] == state.digest() and snapshot["absolute_step"] == step
        and state.step_count == contract["warmup_step_count"]+step
        and snapshot["authority"] == "DENY_ALL" and snapshot["production_authority"] is False,
        "complete optimizer state, clock and denied authority")
    origin, cursor, horizon = [snapshot[k] for k in ("plan_origin_step", "action_cursor", "plan_horizon")]
    stride = 1 if contract["policy"] == "myopic_h1" else contract["configuration"]["commit_stride"]
    require(all(type(v) is int for v in (origin, cursor, horizon)) and 0 <= origin <= step
        and horizon in (0, stride) and origin % stride == 0 and 0 <= cursor <= horizon
        and origin+cursor == step and origin+horizon <= len(actions) and (horizon != 0 or step == 0),
        "installed certified prefix cursor")
    require(snapshot["plan_origin_state_sha256"] == trace["state_sha256"][origin]
        and snapshot["plan_state_sha256"] == trace["state_sha256"][origin:origin+horizon+1]
        and snapshot["plan_receipt_sha256"] == [digest(r) for r in trace["receipts"][origin:origin+horizon]],
        "installed complete plan state/receipt census")
    arrays = {}
    for kind in ("intended", "resolved", "forecast"):
        count = min(1 if contract["policy"] == "myopic_h1" else 8, 32-origin) if kind == "forecast" and horizon else horizon
        arrays[kind] = np.asarray(snapshot[kind+"_actions"], dtype=np.float64).reshape(count, state.parameter_count)
        require(np.isfinite(arrays[kind]).all()
            and np.all(np.abs(arrays[kind]) <= contract["configuration"]["action_bound"]/np.sqrt(state.parameter_count))
            and array_hash(arrays[kind]) == snapshot[kind+"_plan_sha256"], "canonical physical "+kind+" plan")
    require(snapshot["forecast_horizon"] == len(arrays["forecast"])
        and np.array_equal(arrays["forecast"][:horizon], arrays["intended"])
        and np.array_equal(arrays["resolved"], actions[origin:origin+horizon]), "forecast prefix and retained resolved action identity")
    chain = digest([])
    for receipt in trace["receipts"][:step]:
        chain = digest([chain, digest(receipt)])
    require(snapshot["receipt_chain"] == {"count": step, "sha256": chain}, "complete cumulative receipt chain")
    installed = [r for r in record["steps"] if r.get("committed_steps", 0) and r["at_step"] < step]
    certificates = [{"origin_step": r["at_step"], "origin_state_sha256": trace["state_sha256"][r["at_step"]],
        "plan_sha256": digest(r["plan"]), "repair_sha256": digest(r["repair"]),
        "resolved_plan_sha256": array_hash(actions[r["at_step"]:r["at_step"]+r["committed_steps"]]),
        "forecast_plan_sha256": array_hash(np.asarray(r["forecast_actions"], dtype=np.float64))} for r in installed]
    require(snapshot["certificate_chain"] == certificates, "installed certificate history binds all raw paid plans")
    if horizon:
        require(np.array_equal(arrays["forecast"], np.asarray(installed[-1]["forecast_actions"])), "original forecast retained without replanning")
    counters = snapshot["counters"]
    expected = {"plans": len(installed), "proposal_calls": len(installed),
        "response_optimizer_steps": sum(r["plan"]["reference_optimizer_steps"] for r in installed),
        "qp_calls": 0, "actual_merit_rollout_steps": 0,
        "repair_optimizer_updates": sum(r["repair"]["verified_optimizer_steps"] for r in installed),
        "repair_panel_evaluations": sum(r["repair"]["panel_head_evaluations"] for r in installed),
        "resume_verification_updates": 0, "committed_steps": step}
    require(all(type(v) is int and v >= 0 for v in counters.values())
        and all(counters.get(k) == v for k, v in expected.items()), "installed-plan counter census")
    terminal = step == len(actions)
    stopped = terminal and record["status"] != "completed"
    require(snapshot["run_status"] == ("stopped" if stopped else "completed" if step == 32 else "active"), "typed run status")
    ledger = [{"origin_absolute_step": 0, "stopped_absolute_step": step, "status": record["status"],
        "paid_cpu_ns": record["cpu_ns"], "paid_wall_ns": record["wall_ns"],
        "execution_record_sha256": digest(record["steps"]), "error": record["error"]}] if stopped else []
    require(snapshot["failure_ledger"] == ledger and (not stopped or cursor == horizon), "exact terminal paid stop ledger")
    if terminal:
        require(counters["controller_cpu_ns"] == record["cpu_ns"], "terminal controller charges complete original core CPU")


def inspect_case(directory, warmup, inputs, configuration, policy, protocol_sha, source_sha, *, restore_directory=None):
    from cell_field_state import CellTrainingState
    directory = Path(directory)
    header = read(directory/"result.json")
    if header["status"] == "unavailable_execution_error":
        require(header["error"] and header["audit_passed"] is False and header["completed_steps"] is None
            and header["future_mean_nll"] is None and header["old_mean_difference"] is None, "unavailable slot retained")
        return {"header": header, "available": False, "actual_errors": [header["error"]], "cuts": [], "workload": []}
    record, trace, cuts = [read(directory/name, True) for name in
        ("policy-record.json.gz", "trace.json.gz", "controller-checkpoints.json.gz")]
    for name, key in (("policy-record.json.gz", "policy_record"), ("trace.json.gz", "trace_file"), ("controller-checkpoints.json.gz", "controller_file")):
        require(file_hash(directory/name) == header[key]["sha256"], "compressed evidence identity")
    with np.load(directory/"compact.npz", allow_pickle=False) as data:
        require(set(data.files) == {"actions", "terminal_vector", "future_losses", "old_differences"}, "compact array census")
        actions, vector, future, old = (data[k] for k in ("actions", "terminal_vector", "future_losses", "old_differences"))
    count, p = len(actions), warmup.parameter_count
    require(actions.shape == (count, p) and 0 <= count <= 32 and np.isfinite(actions).all()
        and np.all(np.abs(actions) <= configuration["action_bound"]/np.sqrt(p)), "bounded physical trace")
    require(record["policy"] == header["policy"] == policy and record["status"] == header["status"]
        and record["completed_steps"] == record["newly_committed_steps"] == header["completed_steps"] == count
        and record["origin_absolute_step"] == 0 and record["registered_steps"] == 32
        and record["status"] in {"completed", "not_executed_rejected", "not_executed_unresolved"}
        and (record["status"] != "completed" or count == 32), "all finite complete/stopped statuses retained")
    require(len(trace["receipts"]) == count and len(trace["state_sha256"]) == len(trace["controller_sha256"]) == count+1
        and trace["state_sha256"][0] == record["initial_state_sha256"] == warmup.digest(), "exact initial trace")
    require(set(cuts) == {str(k) for k in (0, 16, 17, 32, count) if k <= count}, "registered cuts plus actual terminal preimage")
    anchors, current = panel_losses(warmup, inputs["old_panels"]), warmup.clone()
    contract = expected_contract(warmup, inputs, anchors, policy, configuration, protocol_sha, source_sha)
    workload = [check_portfolio(r["repair"]) for r in record["steps"] if "repair" in r]
    maximum, snapshots, vectors = None, [], []
    for step in range(count+1):
        if step:
            receipt = current.advance(*inputs["split"]["current_train"], intervention=configuration["dt"]*actions[step-1])
            require(receipt == trace["receipts"][step-1] and current.digest() == trace["state_sha256"][step], "exact actual Adam/clock/RNG/receipt replay")
            excess = panel_losses(current, inputs["old_panels"])-anchors
            require(np.isfinite(excess).all() and np.all(excess <= 0.), "every committed old-panel constraint, zero slack")
            maximum = float(excess.max()) if maximum is None else max(maximum, float(excess.max()))
        vectors.append(current.vector())
        if str(step) not in cuts:
            continue
        controller = cuts[str(step)]
        require(digest(controller) == trace["controller_sha256"][step], "canonical controller hash preimage")
        check_snapshot(controller, current, step, contract, trace, record, actions)
        row = {"step": step, "state_sha256": current.digest(), "controller_sha256": digest(controller),
            "run_status": controller["run_status"], "pending_actions": controller["plan_horizon"]-controller["action_cursor"], "restore_checked": False}
        if restore_directory is not None and step in (0, 16, 17, 32):
            target = Path(restore_directory)/str(step)
            require((target/"controller.json").read_bytes() == canonical(controller), "selected exact original controller bytes")
            restored = CellTrainingState.load(target/"state", warmup.bindings, warmup.protocol, warmup.contexts, current.digest())
            require(np.array_equal(restored.vector(), current.vector()), "selected full optimizer checkpoint restores exactly")
            if controller["run_status"] != "stopped":
                for k in range(step, count):
                    require(restored.advance(*inputs["split"]["current_train"], intervention=configuration["dt"]*actions[k])
                        == trace["receipts"][k] and restored.digest() == trace["state_sha256"][k+1], "stored-action suffix after selected restore")
            row.update(restore_checked=True, suffix_steps_checked=count-step if controller["run_status"] != "stopped" else 0)
        snapshots.append(row)
    require(current.digest() == record["terminal_state_sha256"] == header["terminal_state_sha256"]
        and np.array_equal(current.vector(), vector), "terminal full state")
    computed_future = losses(current, inputs["selection"]["future"])
    computed_old = losses(current, inputs["selection"]["old"])-losses(warmup, inputs["selection"]["old"])
    require(future.shape == old.shape == (512,) and np.array_equal(future, computed_future)
        and np.array_equal(old, computed_old), "all terminal per-source scores independently reproduced")
    require(header["future_mean_nll"] == float(future.mean()) and header["old_mean_difference"] == float(old.mean()), "scalar mean scores")
    require(type(header["cpu_ns"]) is int and header["cpu_ns"] >= record["cpu_ns"] > 0
        and header["policy_core_cpu_ns"] == record["cpu_ns"] and header["wall_ns"] >= record["wall_ns"] > 0, "whole-call/core CPU and wall accounting")
    penalty = float(.5*configuration["dt"]*configuration["effort_price"]*np.square(actions).sum())
    require(penalty == record["parameter_action_penalty"], "physical action cost")
    actual_errors = list(errors(record))
    require(header["audit_passed"] == (not actual_errors)
        and header["audit"]["maximum_empirical_old_panel_excess"] == maximum, "original integrity/old-panel result matches independent replay")
    return {"header": header, "available": True, "future_losses": future, "old_differences": old,
        "actual_errors": actual_errors, "maximum_panel_excess": maximum, "cuts": snapshots,
        "actions": actions, "state_vectors": np.asarray(vectors), "workload": workload}
