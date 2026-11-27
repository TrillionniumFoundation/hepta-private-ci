"""Independent pre-label replay of all recorded V5 optimizer transitions.

Only source metadata, training/probe arrays and sealed predictions are inputs.
The replay is an integrity check, separate from controller CPU measurements and
from independent heldout scientific outcomes. It grants no native authority.
"""

import itertools
import json
from pathlib import Path
import time

import numpy as np

from cell_field_evaluate_v4 import verify_pre_label_seal
from cell_field_evaluate_v5 import TASKS, HEADS, SEEDS, POLICIES
from cell_field_features import file_hash
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


GUARDED = {"myopic_guarded_h1", "loss2_h8", "response_h8_guarded"}


def read_json(path):
    return json.loads(Path(path).read_bytes())


def read_arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def verified_run(root, protocol):
    seal = verify_pre_label_seal(root, protocol)
    if seal.get("validation_labels_opened") is not False or read_json(Path(root)/"protocol.json") != read_json(protocol):
        raise ValueError("validation access flag or canonical protocol changed")
    return seal


def _training(root, data, task, protocol_hash):
    inputs = read_json(root/task/"inputs.json")
    receipt = inputs["data_receipt"]
    if receipt["protocol_sha256"] != protocol_hash:
        raise ValueError("data receipt protocol differs")
    for name in ("sources.json", "predictors.json", "train_labels.json", "data_receipt.json"):
        if file_hash(data/task/name) != inputs["input_hashes"][name]:
            raise ValueError("source or train payload changed")
    projected = read_arrays(root/task/"projected.npz")["features"]
    arrays = read_arrays(root/task/"training.npz")
    labels = read_json(data/task/"train_labels.json")["roles"]
    split = {}
    for role in ("old_train", "old_probe", "current_train", "current_probe"):
        values = labels[role]
        x, y = arrays[role+"_x"], arrays[role+"_y"]
        if not np.array_equal(x, projected[values["indices"]]) or not np.array_equal(y, values["labels"]):
            raise ValueError("training arrays disagree with source-labelled roles")
        split[role] = x, y
    return inputs, projected, split


def _warmup(directory, inputs, projected, split, plan, task, head, seed, source_hashes, protocol_hash):
    saved = directory/"warmup/checkpoint"
    manifest = read_json(saved/"manifest.json")
    bindings = manifest["bindings"]
    expected = {"protocol_sha256": protocol_hash, "task": task, "seed": seed, "head_mode": head,
                "sources_sha256": inputs["input_hashes"]["sources.json"], "executed_code_sha256": source_hashes,
                "feature_identity": inputs["feature_report"]["feature_identity"]}
    if bindings != expected:
        raise ValueError("warmup complete-source bindings differ")
    contexts = {role: dataset_digest(*split[role]) for role in ("old_train", "current_train")}
    terminal = CellTrainingState.load(saved, bindings, plan["optimizer"], contexts)
    actual = CellTrainingState(NumpyCellHead(8, 4, head, seed=seed), bindings=bindings,
        protocol=plan["optimizer"], seed=seed, contexts=contexts, active_context="old_train")
    recorded = read_arrays(directory/"warmup/warmup.npz")
    if recorded["states"].shape != (plan["warmup_steps"]+1, len(actual.vector())):
        raise ValueError("warmup trajectory count differs")
    for k in range(plan["warmup_steps"]+1):
        if not np.array_equal(actual.vector(), recorded["states"][k]):
            raise ValueError("warmup replay state differs")
        if k < plan["warmup_steps"]:
            actual.advance(*split["old_train"])
    actual.select_context("current_train")
    if actual.digest() != terminal.digest() or not np.array_equal(actual.head.predict_proba(projected), recorded["probabilities"]):
        raise ValueError("warmup terminal identity or prediction differs")
    old_anchor = float(actual.head.loss_gradients(normalize_features(split["old_probe"][0]), split["old_probe"][1], 0.)[0])
    if old_anchor != read_json(directory/"warmup/result.json")["old_anchor"]:
        raise ValueError("original retention threshold differs")
    return actual, old_anchor


def audit_policy(path, warmup, projected, split, old_anchor, configuration):
    record = read_json(path/"result.json")
    policy = record["policy"]
    if (record.get("error") or record["status"] == "execution_failed"
            or any(step.get("error") for step in record.get("steps", []))):
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
    return {"schema": "hepta.cell-field-independent-pre-label-audit.v5", "rows": rows,
        "protocol_sha256": seal["protocol_sha256"], "pre_evaluation_seal_sha256": file_hash(root/"pre_evaluation_seal.json"),
        "registered_policy_outputs": 72, "valid_policy_outputs": sum(r["valid_record"] for r in rows),
        "all_replays_valid": all(r["valid_record"] for r in rows), "heldout_labels_opened": False,
        "audit_cpu_ns": time.process_time_ns()-cpu, "audit_wall_ns": time.perf_counter_ns()-began,
        "scope": "independent local numerical replay with source/code/state bindings; not a host signature or native capability",
        "authority": "DENY_ALL", "production_authority": False}
