"""Execute every frozen Cell parameter-field condition before final-label access.

This research runner consumes real shared Encoder features and only training /
controller-probe labels. It records failed conditions as well as successful ones.
All matrices, checkpoints and predictions are sealed before independent scoring.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback

import numpy as np

from cell_field_control import build_reference, diagnose_tangent, fit_controller, run_nonlinear
from cell_field_features import file_hash, load_features
from cell_field_replay import verify_replay
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, canonical


SOURCE_FILES = ("cell_field_run.py", "cell_field_replay.py", "cell_field_state.py",
                "cell_field_control.py", "cell_field_features.py",
                "cell_learning_models.py", "cell_learning_metrics.py")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def save_arrays(path, arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def source_hashes():
    return {name: file_hash(Path(__file__).parent / name) for name in SOURCE_FILES}


def _deny_final_labels(event, arguments):
    if event == "open" and arguments and isinstance(arguments[0], (str, bytes)):
        name = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        if Path(name).name == "final_labels.json":
            raise PermissionError("final scoring labels are not an input to the training runner")


def _inputs(data, feature_dir, protocol):
    plan, protocol_hash = json.loads(protocol.read_bytes()), file_hash(protocol)
    receipt = json.loads((data / "data_receipt.json").read_bytes())
    for name in ("train_labels.json", "sources.json"):
        if file_hash(data / name) != receipt["files"][name]["sha256"]:
            raise ValueError("training/source metadata differs from its preparation receipt")
    labels = json.loads((data / "train_labels.json").read_bytes())
    sources = json.loads((data / "sources.json").read_bytes())["rows"]
    features, feature_report = load_features(feature_dir, protocol_hash)
    if (set(labels["roles"]) != {"old_train", "old_probe", "current_train", "current_probe"}
            or labels["classes"] != plan["classes"]
            or receipt["source_archive_sha256"] != plan["source_archive_sha256"]
            or feature_report["plan"]["data_receipt_sha256"] != file_hash(data / "data_receipt.json")
            or len(features) != len(sources)
            or feature_report["plan"]["source_ids"] != [row["source_id"] for row in sources]
            or plan["optimizer"]["sampler"] != "full_batch"):
        raise ValueError("data, feature and frozen experiment identities disagree")
    seen = set()
    for role, values in labels["roles"].items():
        indices, y = np.asarray(values["indices"]), np.asarray(values["labels"])
        if (indices.dtype.kind not in "iu" or y.dtype.kind not in "iu"
                or indices.ndim != 1 or y.shape != indices.shape
                or np.any(indices < 0) or np.any(indices >= len(features))
                or len(set(indices.tolist())) != len(indices) or seen.intersection(indices.tolist())
                or set(y.tolist()) != set(range(plan["classes"]))
                or values["source_ids"] != [sources[i]["source_id"] for i in indices]
                or any(sources[i]["role"] != role for i in indices)):
            raise ValueError("training role labels/source indices are inconsistent")
        seen.update(indices.tolist())
    return plan, protocol_hash, receipt, labels, sources, features, feature_report


def _project(features, plan):
    rng = np.random.default_rng(plan["projection"]["seed"])
    width = plan["projection"]["width"]
    q, r = np.linalg.qr(rng.normal(size=(features.shape[1], width)), mode="reduced")
    q *= np.where(np.diag(r) < 0, -1.0, 1.0)
    projected = features.astype(np.float64) @ q
    if not np.isfinite(projected).all() or q.shape != (features.shape[1], width):
        raise ValueError("invalid fixed projection")
    return projected, q


def _split_arrays(features, labels):
    return {role: (features[np.asarray(values["indices"], dtype=np.int64)],
                   np.asarray(values["labels"], dtype=np.int64))
            for role, values in labels["roles"].items()}


def _environment():
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy")}}
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["peak_rss_bytes"] = value if sys.platform == "darwin" else value * 1024
    except ImportError:
        result["peak_rss_bytes"] = None
    return result


def _condition(output, initial_id, initial_index, state, reference, controller, oracle,
               projected, feature_identity):
    run_id = f"{initial_id}-{controller.mask}-{controller.mode}"
    paths = {"reference": f"references/{initial_id}.npz",
             "controller": f"controllers/{run_id}.npz",
             "trajectory": f"trajectories/{run_id}.npz",
             "tangent": f"tangent/{run_id}.npz",
             "receipts": f"receipts/{run_id}.json",
             "checkpoint": f"checkpoints/{run_id}", "head": f"heads/{run_id}"}
    record = {"run_id": run_id, "initial_index": initial_index, "mask": controller.mask,
              "policy": controller.mode, "status": "failed", "paths": paths,
              "policy_build_wall_ns": controller.build_wall_ns}
    probabilities = np.full((len(projected), state.head.classes), np.nan)
    try:
        save_arrays(output / paths["controller"], controller.arrays())
        before = state.digest()
        rollout = run_nonlinear(state, reference, controller)
        if state.digest() != before:
            raise ValueError("counterfactual policy changed the common initial state")
        save_arrays(output / paths["trajectory"], {key: rollout[key] for key in
                    ("states", "observations", "fields", "actions")})
        write_json(output / paths["receipts"], rollout["receipts"])
        rollout["state"].save(output / paths["checkpoint"])
        rollout["state"].head.save(output / paths["head"], feature_identity)
        persist_done = time.perf_counter_ns()
        probabilities = rollout["state"].head.predict_proba(projected)
        restored = NumpyCellHead.load(output / paths["head"], feature_identity)
        if not np.array_equal(probabilities, restored.predict_proba(projected)):
            raise ValueError("serving Head restoration changed predictions")
        prediction_ns = time.perf_counter_ns() - persist_done
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        tangent = diagnose_tangent(reference, controller, oracle=oracle)
        tangent_time = {"wall_ns": time.perf_counter_ns() - began,
                        "cpu_ns": time.process_time_ns() - cpu}
        save_arrays(output / paths["tangent"], {key: value for key, value in tangent.items()
                                               if isinstance(value, np.ndarray)})
        summary = {key: value for key, value in tangent.items() if not isinstance(value, np.ndarray)}
        record.update(status="completed", cost=rollout["cost"], tangent=summary,
            tangent_diagnostic_time=tangent_time, wall_ns=rollout["wall_ns"], cpu_ns=rollout["cpu_ns"],
            prediction_and_serving_roundtrip_wall_ns=prediction_ns,
            probe_initial=rollout["observations"][0, :2].tolist(),
            probe_final=rollout["observations"][-1, :2].tolist(),
            final_state_sha256=rollout["state"].digest(), serving_roundtrip_equal=True,
            physical_intervention_squared_norm=rollout["physical_intervention_squared_norm"],
            max_physical_intervention_l2=rollout["max_physical_intervention_l2"])
        if controller.mask == "all" and controller.mode == "loss2":
            recovery_path = f"recovery/{initial_id}"
            record["paths"]["recovery"] = recovery_path
            record["recovery"] = verify_replay(output / recovery_path, state, reference, controller, rollout)
        # Finite states can still overflow quadratic costs or a transfer bound.
        # Reject that condition here, before its summary can abort the census.
        canonical(record)
    except Exception as error:
        record = {key: value for key, value in record.items() if key in
                  ("run_id", "initial_index", "mask", "policy", "paths", "policy_build_wall_ns")}
        record.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        write_json(output / f"failures/{run_id}.json", {"error": record["error"],
                                                     "traceback": traceback.format_exc()})
        probabilities.fill(np.nan)
    return record, probabilities


def execute(data, features, protocol, output):
    sys.addaudithook(_deny_final_labels)
    data, features, protocol, output = map(Path, (data, features, protocol, output))
    start = datetime.now(timezone.utc).isoformat()
    began, cpu_began, hashes = time.perf_counter_ns(), time.process_time_ns(), source_hashes()
    input_paths = {**{f"data/{name}": data / name for name in
                     ("data_receipt.json", "train_labels.json", "sources.json")},
                   **{f"features/{name}": features / name for name in ("report.json", "features.npz")},
                   "protocol.json": protocol}
    input_hashes = {name: file_hash(path) for name, path in input_paths.items()}
    plan, protocol_hash, receipt, labels, sources, matrix, feature_report = _inputs(data, features, protocol)
    output.mkdir(parents=True, exist_ok=False)
    projected, projection = _project(matrix, plan)
    save_arrays(output / "projected_features.npz", {"features": projected, "projection": projection})
    projection_identity = {"method": plan["projection"],
                           "matrix_sha256": hashlib.sha256(projection.tobytes()).hexdigest(),
                           "projected_tensor_sha256": hashlib.sha256(projected.tobytes()).hexdigest(),
                           "input_feature_sha256": feature_report["tensor_sha256"]}
    feature_identity = {"shared_feature_identity": feature_report["feature_identity"],
                        "encoder_identity": feature_report["encoder_identity"],
                        "projection": projection_identity}
    split = _split_arrays(projected, labels)
    contexts = {name: dataset_digest(*split[name]) for name in ("old_train", "current_train")}
    count = len(plan["seeds"]) * len(plan["head_modes"])
    condition_count = count * len(plan["action_masks"]) * len(plan["policies"])
    predictions = np.full((condition_count, len(projected), plan["classes"]), np.nan)
    initial_predictions = np.full((count, len(projected), plan["classes"]), np.nan)
    records, initials, references, row = [], [], [], 0
    for initial_index, (seed, mode) in enumerate((seed, mode) for seed in plan["seeds"]
                                                for mode in plan["head_modes"]):
        initial_id = f"seed{seed}-{mode}"
        initial = {"seed": seed, "head": mode, "run_id": initial_id,
                   "path": f"initial/{initial_id}", "status": "failed"}
        reference_record = {"initial_id": initial_id, "status": "failed"}
        try:
            bindings = {"protocol_sha256": protocol_hash, "feature_identity": feature_identity,
                        "sources_sha256": receipt["files"]["sources.json"]["sha256"],
                        "train_labels_sha256": receipt["files"]["train_labels.json"]["sha256"],
                        "task": plan["task"], "topology": "one privately trained Cell", "seed": seed,
                        "head_mode": mode, "executed_code_sha256": hashes}
            head = NumpyCellHead(plan["projection"]["width"], plan["classes"], mode, seed=seed)
            state = CellTrainingState(head, bindings=bindings, protocol=plan["optimizer"], seed=seed,
                                      contexts=contexts, active_context="old_train")
            warm_wall, warm_cpu, warm_states, warm_receipts = time.perf_counter_ns(), time.process_time_ns(), [state.vector()], []
            for _ in range(plan["warmup_steps"]):
                warm_receipts.append(state.advance(*split["old_train"]))
                warm_states.append(state.vector())
            warmup_cost = {"wall_ns": time.perf_counter_ns() - warm_wall,
                           "cpu_ns": time.process_time_ns() - warm_cpu}
            save_arrays(output / f"warmup/{initial_id}.npz", {"states": np.asarray(warm_states)})
            write_json(output / f"warmup/{initial_id}-receipts.json", warm_receipts)
            state.select_context("current_train")
            state.save(output / initial["path"])
            initial_predictions[initial_index] = state.head.predict_proba(projected)
            initial.update(status="completed", state_sha256=state.digest(), warmup=warmup_cost,
                           parameter_count=state.parameter_count, optimizer_state_dimension=3 * state.parameter_count,
                           parameter_bytes=state.parameter_vector().nbytes,
                           complete_numeric_state_bytes=state.vector().nbytes)
            ref_cpu = time.process_time_ns()
            reference = build_reference(state, *split["current_train"],
                probes=(split["current_probe"], split["old_probe"]), horizon=plan["horizon"], dt=plan["h"])
            reference_record.update(status="completed", path=f"references/{initial_id}.npz",
                build_wall_ns=reference.build_wall_ns, build_cpu_ns=time.process_time_ns() - ref_cpu,
                derivative_audit=reference.derivative_audit)
            save_arrays(output / reference_record["path"], reference.arrays())
            target = np.column_stack([np.full(plan["horizon"] + 1, plan["current_target_displacement"]),
                                      reference.observations[0, 1] - reference.observations[:, 1]])
            oracles = {mask: fit_controller(reference, mask=mask, mode="full", target=target,
                                           effort_price=plan["effort_price"]) for mask in plan["action_masks"]}
            oracle_values = {mask: float(policy.riccati["constant"][0]) for mask, policy in oracles.items()}
            reference_record["oracle_values"] = oracle_values
            reference_record["bias_actuation_penalty"] = oracle_values["bias"] - oracle_values["all"]
            canonical(reference_record)
            for mask in plan["action_masks"]:
                for policy in plan["policies"]:
                    controller = oracles[mask] if policy == "full" else fit_controller(
                        reference, mask=mask, mode=policy, target=target, effort_price=plan["effort_price"])
                    record, probability = _condition(output, initial_id, initial_index, state,
                                                     reference, controller, oracles[mask], projected, feature_identity)
                    record.update(seed=seed, head=mode)
                    predictions[row] = probability
                    records.append(record)
                    row += 1
                    print(json.dumps({"run_id": record["run_id"], "status": record["status"],
                                      "cost": record.get("cost"), "error": record.get("error")}), flush=True)
        except Exception as error:
            failure = {"type": type(error).__name__, "message": str(error)}
            reference_record = {"initial_id": initial_id, "status": "failed", "error": failure}
            write_json(output / f"failures/{initial_id}.json", {"error": failure, "traceback": traceback.format_exc()})
            seen = {(record["mask"], record["policy"]) for record in records if record["initial_index"] == initial_index}
            for mask in plan["action_masks"]:
                for policy in plan["policies"]:
                    if (mask, policy) not in seen:
                        records.append({"run_id": f"{initial_id}-{mask}-{policy}", "seed": seed, "head": mode,
                                        "mask": mask, "policy": policy, "initial_index": initial_index,
                                        "status": "failed", "error": failure, "failure_stage": "initial_or_policy_setup"})
                        row += 1
        initials.append(initial)
        references.append(reference_record)
        write_json(output / "progress.json", {"completed_conditions": row, "records": records})
    if len(records) != condition_count or row != condition_count:
        raise ValueError("registered condition census is incomplete")
    if source_hashes() != hashes or file_hash(protocol) != protocol_hash:
        raise ValueError("source or protocol changed during scientific execution")
    if {name: file_hash(path) for name, path in input_paths.items()} != input_hashes:
        raise ValueError("training inputs changed during scientific execution")
    save_arrays(output / "predictions.npz", {"probabilities": predictions, "initial_probabilities": initial_predictions})
    report = {"schema": "hepta.cell-field-runs.v1", "protocol_sha256": protocol_hash,
        "data_receipt_sha256": file_hash(data / "data_receipt.json"),
        "feature_report_sha256": file_hash(features / "report.json"), "source_ids": [r["source_id"] for r in sources],
        "row_roles": [r["role"] for r in sources], "initial_order": initials, "records": records,
        "references": references, "projection_identity": projection_identity,
        "feature_identity": feature_identity, "feature_report": feature_report,
        "protocol": plan, "sourcecode_hashes": hashes, "input_hashes": input_hashes, "environment": _environment(),
        "execution": {"started_at_utc": start, "wall_ns": time.perf_counter_ns() - began,
                      "parent_cpu_ns": time.process_time_ns() - cpu_began, "recovery_child_cpu_measured": False},
        "record_count": len(records), "completed": sum(r["status"] == "completed" for r in records),
        "failed": sum(r["status"] != "completed" for r in records), "final_labels_opened": False,
        "noise_model": plan["noise_model"], "authority": "DENY_ALL", "production_authority": False}
    write_json(output / "runs.json", report)
    for name in SOURCE_FILES:
        (output / "source").mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).parent / name, output / "source" / name)
    (output / "inputs").mkdir(exist_ok=True)
    for name in ("data_receipt.json", "sources.json", "train_labels.json"):
        shutil.copyfile(data / name, output / "inputs" / name)
    shutil.copyfile(protocol, output / "inputs" / "protocol.json")
    shutil.copyfile(features / "report.json", output / "inputs" / "feature-report.json")
    inventory = {str(path.relative_to(output)): {"sha256": file_hash(path), "bytes": path.stat().st_size}
                 for path in sorted(output.rglob("*")) if path.is_file()}
    seal = {"schema": "hepta.cell-field-pre-evaluation-seal.v1", "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
            "protocol_sha256": protocol_hash, "data_receipt_sha256": report["data_receipt_sha256"],
            "feature_report_sha256": report["feature_report_sha256"], "sourcecode_hashes": hashes,
            "environment": report["environment"], "record_count": len(records),
            "initial_state_sha256": [item.get("state_sha256") for item in initials],
            "projection_identity": projection_identity, "files": inventory,
            "final_labels_opened": False, "authority": "DENY_ALL"}
    write_json(output / "pre_evaluation_seal.json", seal)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "features", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    result = execute(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("record_count", "completed", "failed", "protocol_sha256")}))
