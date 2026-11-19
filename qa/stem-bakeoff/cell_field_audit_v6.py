"""V6 pre-label integrity audit replays every repaired action from full state.

The adopted optimizer trace, not a repair receipt alone, must reproduce every
state, Adam moment, clock, probability and original probe-threshold check.
"""

import itertools
from pathlib import Path
import time

import numpy as np

from cell_field_audit_v5 import read_json, read_arrays, verified_run, _training, _warmup
from cell_field_evaluate_v6 import TASKS, HEADS, SEEDS, POLICIES
from cell_field_features import file_hash
from cell_field_state import CellTrainingState
from cell_learning_models import normalize_features


GUARDED = set(POLICIES)-{"zero"}


def has_execution_error(value):
    if isinstance(value, dict):
        return bool(value.get("error")) or any(has_execution_error(item) for item in value.values())
    return isinstance(value, list) and any(has_execution_error(item) for item in value)


def audit_policy(path, warmup, projected, split, old_anchor, configuration):
    record = read_json(path/"result.json")
    policy = record["policy"]
    if has_execution_error(record) or record["status"] == "execution_failed":
        raise ValueError("recorded actual execution error")
    if (policy not in POLICIES or record["registered_steps"] != configuration["steps"]
            or type(record["completed_steps"]) is not int or not 0 <= record["completed_steps"] <= configuration["steps"]
            or not (record["status"] == "completed" or record["status"].startswith("not_executed_"))
            or (record["status"] == "completed") != (record["completed_steps"] == configuration["steps"])):
        raise ValueError("policy completion/status declaration differs")
    trajectory = read_arrays(path/"trajectory.npz")
    actions, n, p = trajectory["actions"], record["completed_steps"], warmup.parameter_count
    if (actions.shape != (n, p) or not np.isfinite(actions).all()
            or np.any(np.abs(actions) > configuration["action_bound"]/np.sqrt(p))
            or trajectory["states"].shape != (n+1, len(warmup.vector()))
            or trajectory["probabilities"].shape != (n+1, len(projected), 4)):
        raise ValueError("actual action/state/prediction census differs")
    state = warmup.clone()
    initial = CellTrainingState.load(path/"initial", state.bindings, state.protocol, state.contexts, state.digest())
    if initial.digest() != record["initial_state_sha256"]:
        raise ValueError("policy common initial checkpoint differs")
    receipts = read_json(path/"receipts.json")
    if len(receipts) != n:
        raise ValueError("missing actual transition receipt")
    losses, digests = [], []
    for k in range(n+1):
        if (not np.array_equal(state.vector(), trajectory["states"][k])
                or not np.array_equal(state.head.predict_proba(projected), trajectory["probabilities"][k])):
            raise ValueError("independent optimizer replay differs from sealed state/prediction")
        losses.append(float(state.head.loss_gradients(normalize_features(split["old_probe"][0]), split["old_probe"][1], 0.)[0]))
        digests.append(state.digest())
        if k < n:
            actual_receipt = state.advance(*split["current_train"], intervention=configuration["dt"]*actions[k])
            if actual_receipt != receipts[k]:
                raise ValueError("complete optimizer transition receipt differs")
    terminal = CellTrainingState.load(path/"terminal", state.bindings, state.protocol, state.contexts, state.digest())
    if (terminal.digest() != record["terminal_state_sha256"]
            or terminal.step_count != warmup.step_count+n
            or record.get("state_digests") != digests
            or not np.array_equal(trajectory["terminal_probabilities"], trajectory["probabilities"][-1])):
        raise ValueError("terminal state/clock/prediction is inconsistent")
    if (path/"midpoint").is_dir():
        mid = CellTrainingState.load(path/"midpoint", state.bindings, state.protocol, state.contexts)
        offset = mid.step_count-warmup.step_count
        if not 0 <= offset <= n or mid.digest() != digests[offset]:
            raise ValueError("midpoint complete metadata does not lie on actual replay")
    maximum = max(losses[1:])-old_anchor if n else None
    if policy in GUARDED and maximum is not None and maximum > 0:
        raise ValueError("exact guarded actual trace violates the original probe threshold")
    penalty = float(.5*configuration["dt"]*configuration["effort_price"]*np.square(actions).sum())
    if not np.isclose(record["parameter_action_penalty"], penalty, rtol=0, atol=1e-15):
        raise ValueError("recorded action penalty differs")
    return {"status": record["status"], "completed_steps": n, "registered_steps": record["registered_steps"],
        "cpu_ns": record["cpu_ns"], "wall_ns": record["wall_ns"], "valid_record": True,
        "replayed_transitions": n, "terminal_state_sha256": state.digest(),
        "maximum_future_probe_excess": maximum, "guarded": policy in GUARDED, "parameter_action_penalty": penalty}


def audit_run(root, data, protocol):
    root, data, protocol = map(Path, (root, data, protocol))
    seal = verified_run(root, protocol)
    plan, source_hashes = read_json(protocol), read_json(root/"executed_source.json")
    for name, digest in source_hashes.items():
        path = Path(__file__).parent/name
        if Path(name).name != name or path.is_symlink() or file_hash(path) != digest:
            raise ValueError("executed source differs before V6 label access: " + name)
    run = read_json(root/"run.json")
    expected = set(itertools.product(TASKS, HEADS, SEEDS))
    if {(r["task"], r["head"], r["seed"]) for r in run["fits"]} != expected or len(run["fits"]) != 12:
        raise ValueError("missing or duplicated fit census")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    rows = []
    for task in TASKS:
        inputs, projected, split = _training(root, data, task, seal["protocol_sha256"])
        for head, seed in itertools.product(HEADS, SEEDS):
            directory = root/task/f"seed{seed}-{head}"
            warmup, old_anchor = _warmup(directory, inputs, projected, split, plan, task, head, seed, source_hashes, seal["protocol_sha256"])
            for policy in POLICIES:
                row = {"task": task, "head": head, "seed": seed, "policy": policy}
                try:
                    row.update(audit_policy(directory/"mpc"/policy, warmup, projected, split, old_anchor, plan["policy_configuration"]))
                except Exception as error:
                    row.update(valid_record=False, audit_error={"type": type(error).__name__, "message": str(error)})
                rows.append(row)
    return {"schema": "hepta.cell-field-independent-pre-label-audit.v6", "rows": rows,
        "protocol_sha256": seal["protocol_sha256"], "pre_evaluation_seal_sha256": file_hash(root/"pre_evaluation_seal.json"),
        "registered_policy_outputs": 72, "valid_policy_outputs": sum(r["valid_record"] for r in rows),
        "all_replays_valid": all(r["valid_record"] for r in rows), "heldout_labels_opened": False,
        "audit_cpu_ns": time.process_time_ns()-cpu, "audit_wall_ns": time.perf_counter_ns()-began,
        "scope": "independent local numerical replay with source/code/state bindings; not a host signature or native capability",
        "authority": "DENY_ALL", "production_authority": False}
