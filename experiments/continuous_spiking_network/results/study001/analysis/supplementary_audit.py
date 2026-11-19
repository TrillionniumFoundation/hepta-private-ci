"""Post-seal read-only audit; no fitting, case reselection or science-source edits.

The default replay sample is fixed from the preregistered inventory: every
representation-stage architecture/task at training seed 2201 (28 checkpoints).
Use --metadata-only to record that selection without importing torch or data.
"""

import argparse
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time


SELECTION_STAGE = "representation"
SELECTION_SEED = 2201
REPLAY_BATCH_SIZE = 64
REPLAY_ABSOLUTE_TOLERANCE = 1e-6


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    require(path.is_relative_to(root), f"Path escapes results/source root: {relative}")
    return path


def scientific_source(package):
    """Reproduce the frozen source filter without invoking the frozen auditor."""
    saved = read_json(package / "SOURCE_SEAL.json")
    current = {}
    for directory, names, files in os.walk(package):
        names[:] = [name for name in names if name not in {"results", "__pycache__"}]
        for name in files:
            path = Path(directory) / name
            if path.suffix == ".py" or name in {"PROTOCOL.json", "requirements.txt"}:
                current[str(path.relative_to(package))] = sha256(path)
    digest = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
    require(current == saved["files"] and digest == saved["sha256"], "Frozen scientific source changed.")
    return digest


def array_fingerprint(arrays):
    import numpy as np
    digest = hashlib.sha256()
    for name in sorted(arrays):
        array = np.ascontiguousarray(arrays[name])
        digest.update(json.dumps([name, array.dtype.str, array.shape]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def load_npz(path):
    import numpy as np
    with np.load(path, allow_pickle=False) as values:
        return {key: values[key] for key in values.files}


def execution_history(results, plans):
    """Retain nonzero historical exits even when no FAILED.json was produced."""
    attempts, failures, errors = [], [], []
    planned_ids = set(plans)
    for path in sorted(results.rglob("EXECUTION_*.json")):
        run_id = str(path.parent.relative_to(results))
        try:
            receipt = read_json(path)
            require(run_id in planned_ids and receipt["run_id"] == run_id, "Execution receipt run ID is not planned or disagrees with its directory.")
            require(isinstance(receipt["exit_code"], int), "Noninteger process exit code.")
            row = {"run_id": run_id, "file": str(path.relative_to(results)), "sha256": sha256(path),
                   "exit_code": receipt["exit_code"], "status": receipt.get("status"),
                   "elapsed_seconds": receipt.get("elapsed_seconds"),
                   "result_exists": (path.parent / "RESULT.json").exists()}
            attempts.append(row)
            if receipt["exit_code"] != 0 or receipt.get("status") != "completed":
                failures.append(row)
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append({"file": str(path.relative_to(results)), "error": str(error)})
    retained = []
    for path in sorted(results.rglob("FAILED.json")):
        try:
            details = read_json(path)
        except (OSError, ValueError) as error:
            details = {"unreadable_record": str(error)}
        retained.append({"run_id": str(path.parent.relative_to(results)), "file": str(path.relative_to(results)),
                         "sha256": sha256(path), "result_exists": (path.parent / "RESULT.json").exists(), "details": details})
    witnessed = {row["run_id"] for row in attempts}
    completed = {name for name in planned_ids if (inside(results, name) / "RESULT.json").exists()}
    return {"attempts": attempts, "nonzero_or_failed_attempts": failures,
            "retained_failed_json": retained, "errors": errors,
            "completed_without_execution_receipt": sorted(completed - witnessed)}


def reconstruction_key(spec):
    return (spec["task"], spec["length"], spec.get("test_size", 1024), spec.get("data_seed", 7123))


def rebuild_test(key, cache_dir):
    from experiments.continuous_spiking_network.data import load_data
    task, length, test_size, data_seed = key
    # The frozen data contract fixes heldout generation independently of train/val
    # sizes. Tiny unused splits avoid rebuilding large training tensors.
    return load_data(task, train_size=1, val_size=1, test_size=test_size,
                     context_length=length, seed=data_seed, cache_dir=cache_dir).test


def verify_labels_and_batches(directory, spec, rebuilt, result, torch):
    import numpy as np
    predictions = load_npz(directory / "predictions.npz")
    source_path = directory / "split_sources.npz"
    require(sha256(source_path) == result["split_sources_sha256"], "Source NPZ hash differs from RESULT.")
    sources = load_npz(source_path)
    for field in ("labels", "sample_ids", "group_ids"):
        expected = rebuilt.y if field == "labels" else getattr(rebuilt, field)
        require(np.array_equal(predictions[field], expected), f"Rebuilt test {field} differ from saved predictions.")
    for field in ("sample_ids", "group_ids"):
        require(np.array_equal(sources[f"test_{field}"], getattr(rebuilt, field)), f"Rebuilt test {field} differ from saved source NPZ.")
    metadata_fields = ("image_source_ids", "audio_source_ids", "query_modalities", "image_labels", "audio_labels")
    checked = []
    for field in metadata_fields:
        if field in rebuilt.metadata:
            require(np.array_equal(sources[f"test_{field}"], np.asarray(rebuilt.metadata[field])), f"Rebuilt source metadata differ: {field}.")
            checked.append(field)
    require(torch.__version__ == result["environment"]["torch"], "Torch version differs from the training record.")
    generator = torch.Generator().manual_seed(spec["seed"] + 777)
    expected = torch.randint(spec["train_size"], (spec["updates"], spec.get("batch_size", 32)), generator=generator).numpy()
    saved = load_npz(directory / "batch_indices.npz")["indices"]
    require(np.array_equal(expected, saved), "Independent minibatch RNG reconstruction differs.")
    unique = int(np.unique(expected).size)
    require(result["training_examples_seen"] == int(expected.size), "Training draw count mismatch.")
    require(result["unique_training_examples_seen"] == unique, "Unique training exposure mismatch.")
    return {"test_cases": len(rebuilt.y), "test_labels_exact": True, "test_ids_exact": True,
            "source_fields_exact": checked, "minibatch_indices_exact": True,
            "training_draws": int(expected.size), "unique_training_episode_indices": unique,
            "predictions_sha256": sha256(directory / "predictions.npz"),
            "batch_indices_sha256": sha256(directory / "batch_indices.npz"),
            "split_sources_sha256": sha256(source_path)}


def replay_checkpoint(directory, rebuilt, result, torch):
    """Decode model tensors independently; replay the full test set in eval mode."""
    import numpy as np
    from experiments.continuous_spiking_network.models import SequenceClassifier
    checkpoint = directory / "checkpoint"
    require(sha256(checkpoint / "manifest.json") == result["checkpoint_manifest_sha256"], "Replay checkpoint manifest hash mismatch.")
    manifest = read_json(checkpoint / "manifest.json")
    require(manifest["format"] == "concatenated_state_v1", "Replay checkpoint format is unsupported.")
    chunks = []
    for part in manifest["parts"]:
        path = inside(checkpoint, part["file"])
        require(sha256(path) == part["sha256"], "Replay checkpoint chunk hash mismatch.")
        chunks.append(load_npz(path)["bytes"].tobytes())
    packed = b"".join(chunks)
    state, offset = {}, 0
    for item in manifest["tensors"]:
        require(item["offset"] == offset, "Replay checkpoint layout is not contiguous.")
        raw = packed[offset:offset + item["nbytes"]]
        require(hashlib.sha256(raw).hexdigest() == item["sha256"], "Replay tensor hash mismatch.")
        dtype = np.dtype(item["dtype"])
        require(not dtype.hasobject, "Object checkpoint tensor dtype.")
        state[item["name"]] = torch.from_numpy(np.frombuffer(raw, dtype=dtype).reshape(item["shape"]).copy())
        offset += item["nbytes"]
    require(offset == len(packed), "Replay checkpoint contains unassigned bytes.")
    model = SequenceClassifier(**manifest["config"])
    expected_state = model.state_dict()
    require(set(state) == set(expected_state), "Replay model state keys differ.")
    require(all(state[key].dtype == expected_state[key].dtype for key in state), "Replay would coerce checkpoint tensor dtype.")
    model.load_state_dict(state, strict=True)
    model.eval()
    x, dt = torch.from_numpy(rebuilt.x), torch.from_numpy(rebuilt.dt)
    cpu, wall = time.process_time(), time.perf_counter()
    outputs = []
    with torch.no_grad():
        for start in range(0, len(x), REPLAY_BATCH_SIZE):
            logits, _ = model(x[start:start + REPLAY_BATCH_SIZE], dt[start:start + REPLAY_BATCH_SIZE])
            outputs.append(logits.cpu().numpy())
    replayed = np.concatenate(outputs)
    stored = load_npz(directory / "predictions.npz")["logits"]
    require(replayed.shape == stored.shape and np.isfinite(replayed).all(), "Replay prediction shape or finiteness failed.")
    error = float(np.max(np.abs(replayed.astype(np.float64) - stored.astype(np.float64))))
    require(error <= REPLAY_ABSOLUTE_TOLERANCE, f"Full-test replay maximum absolute error {error} exceeds tolerance.")
    return {"test_cases": len(x), "all_logits_bitwise_equal": bool(np.array_equal(replayed, stored)),
            "max_absolute_logit_error": error, "absolute_tolerance": REPLAY_ABSOLUTE_TOLERANCE,
            "all_predicted_classes_equal": bool(np.array_equal(replayed.argmax(1), stored.argmax(1))),
            "batch_size": REPLAY_BATCH_SIZE, "replay_cpu_seconds": time.process_time() - cpu,
            "replay_wall_seconds": time.perf_counter() - wall,
            "checkpoint_manifest_sha256": result["checkpoint_manifest_sha256"]}


def audit(args):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    package, results = args.package.resolve(), args.results.resolve()
    report = {"schema": "hcsn-post-seal-supplementary-audit-v1",
              "audit_role": "Post-seal independent checks; the frozen primary auditor is unchanged.",
              "script_sha256": sha256(__file__), "script_path": str(Path(__file__).resolve()),
              "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "metadata_only": args.metadata_only, "errors": []}
    seal = scientific_source(package)
    protocol, inventory = read_json(package / "PROTOCOL.json"), read_json(results / "RUNS.json")
    require(inventory["source_seal"] == seal, "RUNS and scientific source seals differ.")
    require(canonical_sha(inventory["runs"]) == protocol["runs_sha256"], "Inventory differs from frozen protocol.")
    plans = {entry["run_id"]: entry["spec"] for entry in inventory["runs"]}
    require(len(plans) == len(inventory["runs"]), "Duplicate planned run IDs.")
    classification = {name: spec for name, spec in plans.items() if spec["stage"] != "boundary"}
    selected = sorted(name for name, spec in classification.items() if spec["stage"] == SELECTION_STAGE and spec["seed"] == SELECTION_SEED)
    require(len(selected) == len(protocol["representation"]["architectures"]) * len(protocol["representation"]["tasks"]), "Prespecified replay selection is incomplete.")
    require(len(selected) == 28, "Expected the prespecified 28 replay checkpoints.")
    if args.replay == "all":
        selected = sorted(classification)
    elif args.replay == "none":
        selected = []
    report["source_seal"] = seal
    report["runs_sha256"] = protocol["runs_sha256"]
    report["selection"] = {"mode": args.replay,
                           "rule": "All frozen representation tasks/architectures at seed 2201; selected by specs, never test scores." if args.replay == "prespecified" else "All classification runs." if args.replay == "all" else "No inference replay.",
                           "run_ids": selected, "run_ids_sha256": canonical_sha(selected), "count": len(selected)}
    completed = {name for name in plans if (inside(results, name) / "RESULT.json").exists()}
    actual = {str(path.parent.relative_to(results)) for path in results.rglob("RESULT.json")}
    missing = sorted(set(classification) - completed)
    report["inventory"] = {"planned": len(plans), "classification_planned": len(classification),
                           "classification_completed": len(set(classification) & completed), "all_completed": len(completed),
                           "missing_classification": missing, "unexpected_completed": sorted(actual - set(plans))}
    report["selection_path_status"] = [{"run_id": name, "result": (inside(results, name) / "RESULT.json").exists(),
                                        "predictions": (inside(results, name) / "predictions.npz").exists(),
                                        "checkpoint_manifest": (inside(results, name) / "checkpoint/manifest.json").exists()} for name in selected]
    report["execution_history"] = execution_history(results, plans)
    if args.metadata_only:
        report["status"] = "metadata_verified_no_data_or_checkpoint_replay"
        report["elapsed_seconds"] = time.perf_counter() - started_wall
        return report
    if missing:
        report["status"] = "incomplete_classification_replay_not_started"
        return report
    require(not report["inventory"]["unexpected_completed"], "Unexpected RESULT.json outside the frozen inventory.")
    # Imports happen only after the metadata/complete-classification gates.
    sys.path.insert(0, str(package.parents[1]))
    import numpy as np
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    report["environment"] = {"python": sys.version, "numpy": np.__version__, "torch": torch.__version__, "threads": torch.get_num_threads()}
    cache, rebuilt_records = {}, []
    for key in sorted({reconstruction_key(spec) for spec in classification.values()}):
        cpu, wall = time.process_time(), time.perf_counter()
        split = rebuild_test(key, args.cache_dir)
        cache[key] = split
        rebuilt_records.append({"key": {"task": key[0], "length": key[1], "test_size": key[2], "data_seed": key[3]},
                                "input_shape": list(split.x.shape),
                                "input_and_target_sha256": array_fingerprint({"x": split.x, "dt": split.dt, "y": split.y, "sample_ids": split.sample_ids, "group_ids": split.group_ids}),
                                "source_counts": {k: split.metadata[k] for k in ("unique_images", "unique_recordings", "episodes") if k in split.metadata},
                                "rebuild_cpu_seconds": time.process_time() - cpu, "rebuild_wall_seconds": time.perf_counter() - wall})
    report["reconstructed_test_sets"] = rebuilt_records
    report["reconstruction_scope"] = "Re-execution of the frozen data contract with independent heldout generation; not a second mathematical implementation of each generator. Train/val sizes are one because they do not affect heldout generation."
    checked, loaded_results = [], {}
    for name, spec in sorted(classification.items()):
        directory = inside(results, name)
        try:
            result = read_json(directory / "RESULT.json")
            require(result["spec"] == spec and result["source_seal"] == seal, "RESULT spec/source differs from the frozen plan.")
            check = verify_labels_and_batches(directory, spec, cache[reconstruction_key(spec)], result, torch)
            checked.append({"run_id": name, "status": "verified", **check})
            loaded_results[name] = result
        except Exception as error:
            report["errors"].append({"scope": "labels_sources_minibatches", "run_id": name, "type": type(error).__name__, "error": str(error)})
            checked.append({"run_id": name, "status": "invalid"})
    report["classification_checks"] = checked
    replays = []
    for name in selected:
        if name not in loaded_results:
            replays.append({"run_id": name, "status": "blocked_by_metadata_failure"})
            continue
        try:
            checked_replay = replay_checkpoint(inside(results, name), cache[reconstruction_key(classification[name])], loaded_results[name], torch)
            replays.append({"run_id": name, "status": "verified", **checked_replay})
        except Exception as error:
            report["errors"].append({"scope": "checkpoint_replay", "run_id": name, "type": type(error).__name__, "error": str(error)})
            replays.append({"run_id": name, "status": "invalid"})
    report["checkpoint_replays"] = replays
    report["execution_history"] = execution_history(results, plans)
    for error in report["execution_history"]["errors"]:
        report["errors"].append({"scope": "execution_receipt", **error})
    if report["execution_history"]["completed_without_execution_receipt"]:
        report["errors"].append({"scope": "execution_receipt", "error": "Completed runs lack execution receipts.", "run_ids": report["execution_history"]["completed_without_execution_receipt"]})
    historical_failures = report["execution_history"]["nonzero_or_failed_attempts"] or report["execution_history"]["retained_failed_json"]
    report["status"] = "failed" if report["errors"] else "passed_with_retained_failure_history" if historical_failures else "passed"
    report["summary"] = {"reconstructed_test_sets": len(cache), "classification_verified": sum(row["status"] == "verified" for row in checked),
                         "checkpoint_replays_verified": sum(row["status"] == "verified" for row in replays),
                         "replayed_test_cases": sum(row.get("test_cases", 0) for row in replays),
                         "replay_architectures": dict(Counter(classification[row["run_id"]]["architecture"] for row in replays if row["status"] == "verified"))}
    report["scientific_source_unchanged_after_audit"] = scientific_source(package) == seal
    report["total_cpu_seconds"] = time.process_time() - started_cpu
    report["total_wall_seconds"] = time.perf_counter() - started_wall
    report["limits"] = ["No retraining or optimizer-state reconstruction.", "Checkpoint replay covers the declared fixed sample, unless --replay all was explicitly used.",
                        "Boundary policy mathematics remains covered by the original math tests and primary artifact auditor, not re-solved here.",
                        "This audit does not change uncertainty intervals, test-set reuse, dataset scope or scientific conclusions."]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--replay", choices=("prespecified", "all", "none"), default="prespecified")
    args = parser.parse_args()
    try:
        report = audit(args)
    except Exception as error:
        report = {"schema": "hcsn-post-seal-supplementary-audit-v1", "status": "failed", "script_sha256": sha256(__file__),
                  "errors": [{"type": type(error).__name__, "error": str(error)}]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "output": str(args.output), "selection_count": report.get("selection", {}).get("count"), "summary": report.get("summary")}), flush=True)
    raise SystemExit(0 if report["status"].startswith(("passed", "metadata_verified")) else 1)


if __name__ == "__main__":
    main()
