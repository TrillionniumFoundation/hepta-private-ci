"""V4 origin qualification: all adaptation precedes the sealed endpoint phase.

Importing this module opens no corpus and requires only NumPy. Torch and the
unchanged V3 numerical primitives are imported only inside scientific phases.
"""
from pathlib import Path
import hashlib
import gzip
import json
import time

import numpy as np

from ..field_bridge_v3_20261027.training_common import (Costs, Journal, configuration,
    file_hash, object_hash, require, write_json)
from ..field_bridge_v4_20261027_review.training_panel_origin import PANEL_INDICES, fit_origin, translate

SCHEMA = "hepta.field-bridge.v4"
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", "raw_field",
           "origin_field", "origin_generic", "origin_richer", "origin_h7")
SEEDS = (17, 29, 43)
ADAPTATION_ROLES = tuple("qualification_" + suffix for suffix in ("gradient", "rehearsal", "probe", "guard"))
ENDPOINT_ROLES = ("qualification_task", "qualification_clean")
OLD_PROTOCOL_SHA = "a267e91deb23aff25bdb27cf23f8274b5bfa8217c51ee962f3360297f6daa7c7"


def settings(protocol):
    p, q = configuration(protocol), protocol["qualification"]
    require(protocol["panel_origin"]["translated_indices"] == list(PANEL_INDICES)
            and protocol["panel_origin"]["calibration_context_values"] == 14
            and protocol["panel_origin"]["calibration_context_float64_payload_bytes"] == 112,
            "Calibration context differs from the fixed one-factor intervention")
    require(isinstance(protocol.get("study_id"), str) and protocol["study_id"]
            and "v4" in protocol["study_id"].lower(), "Explicit new V4 study_id required")
    require(protocol["old_training_protocol_sha256"] == OLD_PROTOCOL_SHA, "Old protocol identity changed")
    require(protocol["seeds"] == list(SEEDS) and q["methods"] == list(METHODS), "Fixed model/method inventory changed")
    require(q["schedule_ids"] == [14000, 14001, 14002, 14003], "Fresh paired schedule inventory changed")
    require(q["ordinary_action_indices"] == {"17": 2, "29": 3, "43": 3}
            and q["adaptive_comparator"] == "origin_richer", "Preselected comparators changed")
    require(q["bootstrap_seed"] == 271042 and q["bootstrap_samples"] == 4000
            and q["family_alpha"] == .05 and q["comparison_family"] == 6, "Qualification family changed")
    return p, q


def inventory(directory, exclude=()):
    root = Path(directory).resolve()
    return {str(path.relative_to(root)): file_hash(path) for path in sorted(root.rglob("*"))
            if path.is_file() and str(path.relative_to(root)) not in exclude}


def verify_files(directory, files):
    root = Path(directory).resolve()
    require(bool(files), "Empty evidence inventory")
    for name, identity in files.items():
        path = (root / name).resolve()
        require(path.is_relative_to(root) and path.is_file() and file_hash(path) == identity,
                "Missing, unsafe, or altered evidence: " + name)


def predict(head, raw):
    """Same operations/order as frozen V3 training_policy.predict, without Torch import."""
    projected = ((np.asarray(raw, dtype=np.float64) - head["raw_mean"]) / head["raw_scale"]) @ np.asarray(head["projection"])
    projected = (projected - head["projected_mean"]) / head["projected_scale"]
    result = np.concatenate((np.ones((*projected.shape[:-1], 1)), projected), axis=-1) @ np.asarray(head["coefficients"])
    require(result.shape == (4,) and np.isfinite(result).all(), "Invalid frozen-head prediction")
    return result


def policies(fitted, bank, protocol, scope):
    p, q = settings(protocol)
    require(fitted["schema"] == "hepta.field-bridge.v3.fitted-terminal-controllers.1"
            and bank["schema"] == "hepta.field-bridge.v3.terminal-reference-bank.1", "Unknown frozen head/bank")
    require(fitted["seed"] == bank["seed"] and fitted["seed"] in SEEDS, "Frozen seed mismatch")
    require(fitted["training_configuration_sha256"] == bank["training_configuration_sha256"] == object_hash(p),
            "Original training configuration changed")
    require(fitted["bank_sha256"] == scope["bank_sha256"] and fitted["reference_sha256"] == bank["reference_sha256"] == scope["reference_file_sha256"],
            "Controller bank/reference binding differs")
    origin, result = fit_origin(bank), []
    for name in q["methods"]:
        constant = name.startswith("ordinary_")
        mode = None if constant else ("field" if name == "raw_field" else name.removeprefix("origin_"))
        head = None if constant else fitted["controllers"][mode]
        if head is not None:
            require(head["mode"] == mode and head["ridge"] == 1.0, "A frozen head changed")
        identity = {"schema": SCHEMA + ".policy.1", "study_id": protocol["study_id"], "seed": fitted["seed"],
            "method": name, "action_index": int(name[-1]) if constant else None,
            "head_sha256": None if head is None else object_hash(head), "scope": scope,
            "panel_indices": list(PANEL_INDICES), "fit_initial": origin.tolist(),
            "transform": "raw[I]-(observed_initial[I]-fit_initial[I]); other coordinates unchanged",
            "uses_translated_prediction_state": name.startswith("origin_"),
            "observed_initial_rule": "existing first step-zero probe/guard measurement; immutable through rejection",
            "predictor": "frozen V3 two normalizations, projection, linear head; np.argmax first tie",
            "ordinary_constant_full_path": constant, "steps": p["steps"], "macro_steps": p["macro_steps"]}
        result.append({"name": name, "head": head, "identity": identity, "base_policy_sha256": object_hash(identity)})
    return result


def choose(policy, raw, observed_initial):
    raw = np.asarray(raw, dtype=np.float64)
    mapped = translate(raw, observed_initial, policy["identity"]["fit_initial"])
    state = mapped if policy["identity"]["uses_translated_prediction_state"] else raw
    prediction = None if policy["head"] is None else predict(policy["head"], state)
    action = policy["identity"]["action_index"] if prediction is None else int(np.argmax(prediction))
    return mapped, prediction, action


def save_checkpoint(path, model, optimizer, protocol, metadata):
    import torch
    from ..field_bridge_v3_20261027.learning import snapshot
    from ..field_bridge_20261027.adapters import frozen_base_hash
    require(not Path(path).exists(), "Checkpoint overwrite refused")
    record = {"schema": SCHEMA + ".complete-adapter.1", "study_id": protocol["study_id"],
              "state": snapshot(model, optimizer), "training_configuration": configuration(protocol),
              "frozen_base_sha256": frozen_base_hash(model), "metadata": metadata}
    torch.save(record, path)
    reread = torch.load(path, map_location="cpu", weights_only=True)
    require(reread["state"]["identity"] == record["state"]["identity"]
            and all(torch.equal(value, reread["state"]["parameters"][name])
                    for name, value in record["state"]["parameters"].items()), "Checkpoint serialization mismatch")
    return {"file_sha256": file_hash(path), **record["state"]["identity"], "metadata": metadata}


def load_checkpoint(path, original, seed, protocol, expected_policy):
    import torch
    from ..field_bridge_v3_20261027.learning import make_model, new_optimizer, restore
    from ..field_bridge_20261027.adapters import frozen_base_hash
    record = torch.load(path, map_location="cpu", weights_only=True)
    require(record["schema"] == SCHEMA + ".complete-adapter.1" and record["study_id"] == protocol["study_id"]
            and record["training_configuration"] == configuration(protocol), "Wrong checkpoint study/configuration")
    require(record["metadata"]["seed"] == seed and record["metadata"]["policy_sha256"] == expected_policy,
            "Checkpoint seed/policy identity mismatch")
    model = make_model(original, seed, protocol)
    optimizer = new_optimizer(model, protocol)
    restore(model, optimizer, record["state"])
    require(frozen_base_hash(model) == record["frozen_base_sha256"], "Original model identity mismatch")
    return model, optimizer


def train_path(context, policy, out, schedule_id):
    from ..field_bridge_v3_20261027.learning import guarded_block, make_model, new_optimizer, schedule, state_identity
    from ..field_bridge_v3_20261027.training_features import measure_state
    p, _ = settings(context.protocol)
    out, started, cpu = Path(out), time.perf_counter_ns(), time.process_time_ns()
    out.mkdir(parents=True, exist_ok=False)
    before = context.costs.snapshot()
    model, origin, decisions = make_model(context.original, context.seed, context.protocol), None, []
    optimizer = new_optimizer(model, context.protocol)
    with Journal(out / "decisions-and-outcomes.jsonl.gz") as journal:
        for step in range(0, p["steps"], p["macro_steps"]):
            raw, current, measurement = measure_state(context, model, optimizer, step, schedule_id)
            transform_started, transform_cpu = time.perf_counter_ns(), time.process_time_ns()
            if origin is None:
                require(step == 0, "Origin must be captured exactly once at step zero")
                origin = np.asarray(raw, dtype=np.float64)[list(PANEL_INDICES)].copy()
                origin.setflags(write=False)
                realized_identity = {**policy["identity"], "observed_initial": list(raw), "schedule_id": schedule_id}
                policy_sha = object_hash(realized_identity)
                context.costs.add("panel_origin_captures")
                context.costs.add("panel_origin_calibration_context_values", origin.size)
                context.costs.add("panel_origin_calibration_context_bytes", origin.nbytes)
            helper_origin = np.asarray(raw, dtype=np.float64).copy()
            helper_origin[list(PANEL_INDICES)] = origin
            mapped, predictions, action = choose(policy, raw, helper_origin)
            context.costs.add("panel_origin_translation_calls")
            context.costs.add("panel_origin_coordinates", len(PANEL_INDICES))
            context.costs.add("policy_prediction_calls", int(predictions is not None))
            context.costs.add("policy_control_wall_ns", time.perf_counter_ns() - transform_started)
            context.costs.add("policy_control_cpu_ns", time.process_time_ns() - transform_cpu)
            before_identity = state_identity(model, optimizer)
            decision = journal.append({"schema": SCHEMA + ".decision.1", "study_id": context.protocol["study_id"],
                "kind": "decision_before_update", "seed": context.seed, "method": policy["name"], "step": step,
                "schedule_id": schedule_id, "before": before_identity, "action_index": action,
                "raw_state": list(raw), "mapped_state": mapped.tolist(), "observed_initial": realized_identity["observed_initial"],
                "calibration_context": origin.tolist(),
                "fit_initial": policy["identity"]["fit_initial"], "panel_indices": list(PANEL_INDICES),
                "predictions": None if predictions is None else predictions.tolist(),
                "prediction_state_kind": "mapped" if policy["identity"]["uses_translated_prediction_state"] else "raw",
                "base_policy_sha256": policy["base_policy_sha256"], "policy_sha256": policy_sha,
                "schedule_sha256": object_hash(schedule(context.seed, schedule_id, step, p["macro_steps"], context.protocol)),
                "feature_receipt": measurement, "current_reward_values": current["values"]["reward"].tolist(),
                "current_output_sha256": current["output_sha256"]})
            receipt = guarded_block(context, model, optimizer, step, action, schedule_id)
            require(receipt["before"] == before_identity, "A decision altered the optimizer before its block")
            if not receipt["accepted"]:
                require(receipt["after"] == receipt["before"], "Rejected block failed complete rollback")
            journal.append({"schema": SCHEMA + ".block-outcome.1", "study_id": context.protocol["study_id"],
                            "kind": "block_outcome", "decision_sha256": decision, "policy_sha256": policy_sha, "receipt": receipt})
            decisions.append({"step": step, "action_index": action, "accepted": receipt["accepted"], "decision_sha256": decision})
    context.costs.add("training_trace_bytes", (out / "decisions-and-outcomes.jsonl.gz").stat().st_size)
    metadata = {"study_id": context.protocol["study_id"], "seed": context.seed, "method": policy["name"],
        "schedule_id": schedule_id, "policy_sha256": policy_sha, "base_policy_sha256": policy["base_policy_sha256"],
        "source_roles": list(ADAPTATION_ROLES), "endpoint_accessed": False}
    checkpoint_started = time.perf_counter_ns()
    checkpoint = save_checkpoint(out / "checkpoint.pt", model, optimizer, context.protocol, metadata)
    context.costs.add("checkpoint_serialization_wall_ns", time.perf_counter_ns() - checkpoint_started)
    context.costs.add("checkpoint_bytes", (out / "checkpoint.pt").stat().st_size)
    record = {"schema": SCHEMA + ".trained-path.1", **metadata, "policy_identity": realized_identity,
        "decisions": decisions, "checkpoint": checkpoint, "final_step": p["steps"], "final_identity": state_identity(model, optimizer),
        "best_step_selection": False, "resources": context.costs.since(before),
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "files": inventory(out)}
    write_json(out / "COMPLETE.json", record)
    return record


def train_seed(context, fitted, bank, scope, out):
    _, q = settings(context.protocol)
    require(fitted["seed"] == context.seed and context.group == "qualification" and tuple(context.corpus.splits) == ADAPTATION_ROLES
            and list(context.observers) == ["reward"], "Training must load only adaptation roles and reward observer")
    out, started = Path(out), time.perf_counter_ns()
    paths = {}
    for policy in policies(fitted, bank, context.protocol, scope):
        for schedule_id in q["schedule_ids"]:
            path = out / policy["name"] / ("schedule-" + str(schedule_id))
            record = train_path(context, policy, path, schedule_id)
            paths[str(path.relative_to(out))] = {"complete_sha256": file_hash(path / "COMPLETE.json"),
                                                "policy_sha256": record["policy_sha256"]}
            print(f"train seed={context.seed} method={policy['name']} schedule={schedule_id} complete", flush=True)
    record = {"schema": SCHEMA + ".trained-seed.1", "study_id": context.protocol["study_id"], "seed": context.seed,
        "source_roles": list(ADAPTATION_ROLES), "observer_names": ["reward"], "methods": list(METHODS),
        "schedule_ids": q["schedule_ids"], "scope": scope, "paths": paths, "endpoint_accessed": False,
        "baseline_guard": {"source_ids": context.baseline_guard["source_ids"],
            "values": context.baseline_guard["values"]["reward"].tolist(),
            "output_sha256": context.baseline_guard["output_sha256"], "mean": context.baseline_guard["means"]["reward"]},
        "resources": context.costs.snapshot(), "wall_ns": time.perf_counter_ns() - started, "files": inventory(out)}
    write_json(out / "COMPLETE.json", record)
    return record


def verify_trace(path, done):
    with gzip.open(path, "rt") as stream:
        rows = [json.loads(line) for line in stream]
    require(len(rows) == 12 and [row["record_index"] for row in rows] == list(range(12)), "Incomplete journal")
    origin = np.asarray(done["policy_identity"]["observed_initial"], dtype=np.float64)
    reference = done["policy_identity"]["fit_initial"]
    base_identity = {k: v for k, v in done["policy_identity"].items() if k not in {"observed_initial", "schedule_id"}}
    require(object_hash(base_identity) == done["base_policy_sha256"], "Base policy identity mismatch")
    previous_after = None
    for index, step in enumerate(range(0, 288, 48)):
        decision, outcome = rows[2 * index:2 * index + 2]
        require(decision["schema"] == SCHEMA + ".decision.1" and decision["kind"] == "decision_before_update"
                and decision["study_id"] == done["study_id"] and decision["seed"] == done["seed"]
                and decision["method"] == done["method"] and decision["schedule_id"] == done["schedule_id"]
                and decision["step"] == step and decision["policy_sha256"] == done["policy_sha256"], "Decision identity mismatch")
        require(previous_after is None or decision["before"] == previous_after, "State changed between blocks")
        require(decision["base_policy_sha256"] == done["base_policy_sha256"], "Decision base policy mismatch")
        if decision["predictions"] is not None:
            values = np.asarray(decision["predictions"])
            require(values.shape == (4,) and np.isfinite(values).all()
                    and int(np.argmax(values)) == decision["action_index"], "Prediction/action mismatch")
        else:
            require(done["policy_identity"]["action_index"] == decision["action_index"], "Constant action changed")
        require(np.array_equal(decision["observed_initial"], origin)
                and np.array_equal(decision["fit_initial"], reference)
                and decision["panel_indices"] == list(PANEL_INDICES)
                and np.array_equal(decision["mapped_state"], translate(decision["raw_state"], origin, reference)),
                "Origin translation changed within a path")
        if step == 0:
            require(np.array_equal(decision["raw_state"], origin), "Origin is not the first measured state")
        digest, receipt = object_hash(decision), outcome["receipt"]
        require(outcome["schema"] == SCHEMA + ".block-outcome.1" and outcome["kind"] == "block_outcome"
                and outcome["decision_sha256"] == digest == done["decisions"][index]["decision_sha256"]
                and outcome["policy_sha256"] == done["policy_sha256"], "Unbound block outcome")
        require(receipt["start"] == step and receipt["end"] == step + 48
                and receipt["schedule_id"] == done["schedule_id"] and receipt["schedule_sha256"] == decision["schedule_sha256"]
                and receipt["action_index"] == decision["action_index"] == done["decisions"][index]["action_index"]
                and receipt["accepted"] == done["decisions"][index]["accepted"]
                and receipt["before"] == decision["before"], "Decision/block pairing differs")
        if not receipt["accepted"] or receipt["action_index"] == 0:
            require(receipt["after"] == receipt["before"], "Rollback or zero-action invariance failed")
        previous_after = receipt["after"]
    require(rows[-1]["receipt"]["after"] == done["final_identity"], "Final path identity differs")


def verify_training(root, protocol):
    _, q = settings(protocol)
    root, records = Path(root), {}
    for seed in SEEDS:
        directory = root / "train" / str(seed)
        require(not (directory / "FAILED.json").exists(), "Training phase recorded a failure")
        record = json.loads((directory / "COMPLETE.json").read_text())
        require(record["schema"] == SCHEMA + ".trained-seed.1" and record["study_id"] == protocol["study_id"]
                and record["seed"] == seed and record["endpoint_accessed"] is False, "Invalid trained-seed receipt")
        require(record["methods"] == list(METHODS) and record["schedule_ids"] == q["schedule_ids"]
                and record["source_roles"] == list(ADAPTATION_ROLES) and record["observer_names"] == ["reward"],
                "Training role/method/observer inventory mismatch")
        verify_files(directory, record["files"])
        require(record["files"] == inventory(directory, ("COMPLETE.json",)), "Unlisted or changed training file")
        expected = {f"{method}/schedule-{sid}" for method in METHODS for sid in q["schedule_ids"]}
        require(set(record["paths"]) == expected, "Incomplete 36-path model training")
        for relative, identity in record["paths"].items():
            path = directory / relative
            require(file_hash(path / "COMPLETE.json") == identity["complete_sha256"], "Path receipt changed")
            done = json.loads((path / "COMPLETE.json").read_text())
            require(done["schema"] == SCHEMA + ".trained-path.1" and done["study_id"] == protocol["study_id"]
                    and done["seed"] == seed and done["final_step"] == 288 and done["endpoint_accessed"] is False
                    and relative == f"{done['method']}/schedule-{done['schedule_id']}",
                    "Invalid complete path")
            require(done["policy_sha256"] == identity["policy_sha256"] == object_hash(done["policy_identity"]),
                    "Realized policy identity changed")
            require([d["step"] for d in done["decisions"]] == list(range(0, 288, 48)), "Incomplete six-block path")
            verify_files(path, done["files"])
            require(done["files"] == inventory(path, ("COMPLETE.json",)), "Unlisted or changed path file")
            verify_trace(path / "decisions-and-outcomes.jsonl.gz", done)
            require(done["checkpoint"]["file_sha256"] == file_hash(path / "checkpoint.pt"), "Checkpoint mismatch")
        records[str(seed)] = record
    return records


def training_inventory(root, protocol):
    root = Path(root)
    files = {"train/" + name: value for name, value in inventory(root / "train").items()}
    paths = {path.name: path for path in (root / "PHASE_RECEIPTS").glob("train-*.json")}
    require(set(paths) == {f"train-{seed}.json" for seed in SEEDS},
            "All three successful training postflight receipts are required")
    for seed in SEEDS:
        path = paths[f"train-{seed}.json"]
        receipt = json.loads(path.read_text())
        completed = root / "train" / str(seed) / "COMPLETE.json"
        trained = json.loads(completed.read_text())
        require(receipt["schema"] == SCHEMA + ".phase-cost-receipt.1"
                and receipt["study_id"] == protocol["study_id"] and receipt["phase"] == "train"
                and receipt["seed"] == seed and receipt["scope"] == trained["scope"]
                and receipt["complete_sha256"] == file_hash(completed),
                "Training postflight receipt is not bound to its seed, scope, and completion")
        files[str(path.relative_to(root))] = file_hash(path)
    return files


def seal_training(root, protocol, scope):
    root = Path(root)
    records = verify_training(root, protocol)
    require(not (root / "evaluate").exists(), "Endpoint phase started before the all-path seal")
    record = {"schema": SCHEMA + ".training-seal.1", "study_id": protocol["study_id"], "scope": scope,
        "paths": len(SEEDS) * len(METHODS) * 4, "gradient_microsteps": 31104, "gradient_examples": 2985984,
        "all_training_completed_before_any_endpoint": True, "observer_names_during_training": ["reward"],
        "sealed_unix_ns": time.time_ns(),
        "model_seed_complete_sha256": {seed: file_hash(root / "train" / seed / "COMPLETE.json") for seed in records},
        "files": training_inventory(root, protocol)}
    write_json(root / "TRAINING_SEAL.json", record)
    return record


def verify_seal(root, protocol):
    root = Path(root)
    seal = json.loads((root / "TRAINING_SEAL.json").read_text())
    require(seal["schema"] == SCHEMA + ".training-seal.1" and seal["study_id"] == protocol["study_id"]
            and seal["paths"] == 108 and seal["all_training_completed_before_any_endpoint"] is True,
            "Missing complete independent training seal")
    verify_files(root, seal["files"])
    verify_training(root, protocol)
    require(seal["files"] == training_inventory(root, protocol),
            "Training file inventory changed after seal")
    return seal


def panel_identity(panel):
    result = []
    for part in panel:
        observation, target = part.batch.observation, part.batch.target
        public = b"".join(t.contiguous().numpy().tobytes() for t in (observation.pixels, observation.mask, observation.text_tokens))
        truth = b"".join(t.contiguous().numpy().tobytes() for t in (target.pixels, target.text_tokens, target.labels))
        result.append({"condition": part.condition, "noise_seed": part.noise_seed, "source_ids": part.batch.source_ids,
                       "public_sha256": hashlib.sha256(public).hexdigest(), "target_sha256": hashlib.sha256(truth).hexdigest()})
    return {"batches": result, "sha256": object_hash(result)}


def evaluate_seed(original, corpus, observers, seed, protocol, root, out, scope):
    from ..field_bridge_v3_20261027.learning import hard_panel, panels, save_hard
    p, q = settings(protocol)
    require(tuple(corpus.splits) == ENDPOINT_ROLES and list(observers) == ["reward", "audit"],
            "Evaluation must load only endpoint roles and both observers")
    verify_seal(root, protocol)
    root, out, started, costs = Path(root), Path(out), time.perf_counter_ns(), Costs()
    endpoint_panels = {"task": panels(corpus, ENDPOINT_ROLES[0], seed, p["conditions"], protocol),
                       "clean": panels(corpus, ENDPOINT_ROLES[1], seed, ["clean"], protocol)}
    identities = {key: panel_identity(value) for key, value in endpoint_panels.items()}
    originals = {key: hard_panel(original, panel, observers, p["fixed_actions"][str(seed)], protocol,
                                costs, "qualification_original_" + key, retain=True) for key, panel in endpoint_panels.items()}
    for name, score in originals.items():
        save_hard(out / ("original-" + name + ".npz"), score)
    arrays, paths = {"task": [], "clean": []}, {}
    for method in METHODS:
        method_arrays = {"task": [], "clean": []}
        for sid in q["schedule_ids"]:
            trained = root / "train" / str(seed) / method / ("schedule-" + str(sid))
            done = json.loads((trained / "COMPLETE.json").read_text())
            model, optimizer = load_checkpoint(trained / "checkpoint.pt", original, seed, protocol, done["policy_sha256"])
            destination = out / method / ("schedule-" + str(sid))
            destination.mkdir(parents=True, exist_ok=False)
            before, path_started = costs.snapshot(), time.perf_counter_ns()
            for name, panel in endpoint_panels.items():
                score = hard_panel(model, panel, observers, p["fixed_actions"][str(seed)], protocol,
                                   costs, "qualification_endpoint_" + name, retain=True)
                require(score["source_ids"] == originals[name]["source_ids"] and score["conditions"] == originals[name]["conditions"],
                        "Endpoint source pairing changed")
                save_hard(destination / (name + ".npz"), score)
                method_arrays[name].append(np.stack([score["values"][observer] for observer in observers]))
            receipt = {"schema": SCHEMA + ".evaluated-path.1", "study_id": protocol["study_id"], "seed": seed,
                "method": method, "schedule_id": sid, "policy_sha256": done["policy_sha256"],
                "trained_checkpoint_sha256": file_hash(trained / "checkpoint.pt"), "source_roles": list(ENDPOINT_ROLES),
                "resources": costs.since(before), "wall_ns": time.perf_counter_ns() - path_started, "files": inventory(destination)}
            write_json(destination / "COMPLETE.json", receipt)
            paths[f"{method}/schedule-{sid}"] = file_hash(destination / "COMPLETE.json")
            print(f"evaluate seed={seed} method={method} schedule={sid} complete", flush=True)
            del model, optimizer
        for name in arrays:
            arrays[name].append(np.stack(method_arrays[name]))
    require({key: panel_identity(value) for key, value in endpoint_panels.items()} == identities, "Endpoint mutation")
    with (out / "ENDPOINTS.npz").open("xb") as stream:
        np.savez_compressed(stream, methods=np.asarray(METHODS), schedule_ids=np.asarray(q["schedule_ids"]),
            observer_names=np.asarray(list(observers)), task_values=np.stack(arrays["task"]), clean_values=np.stack(arrays["clean"]),
            original_task=np.stack([originals["task"]["values"][o] for o in observers]),
            original_clean=np.stack([originals["clean"]["values"][o] for o in observers]),
            task_source_ids=np.asarray(originals["task"]["source_ids"]), clean_source_ids=np.asarray(originals["clean"]["source_ids"]),
            task_conditions=np.asarray(originals["task"]["conditions"]), clean_conditions=np.asarray(originals["clean"]["conditions"]))
    write_json(out / "ENDPOINT_IDENTITIES.json", identities)
    record = {"schema": SCHEMA + ".evaluated-seed.1", "study_id": protocol["study_id"], "seed": seed, "scope": scope,
        "paths": paths, "training_seal_sha256": file_hash(root / "TRAINING_SEAL.json"), "source_roles": list(ENDPOINT_ROLES),
        "resources": costs.snapshot(), "wall_ns": time.perf_counter_ns() - started, "files": inventory(out)}
    write_json(out / "COMPLETE.json", record)
    return record

