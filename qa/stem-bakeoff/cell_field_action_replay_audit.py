"""Independent artifact-only audit of every registered V3 cold replay.

No planner, replay implementation, or training-state implementation is imported.
Recorded unavailable/failed replays remain explicit outcomes; contradicted
completed claims or altered evidence raise rather than becoming successes.
"""

from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def inside(root, name):
    path = Path(name)
    if (path.is_absolute() or ".." in path.parts
            or path.name in ("validation_labels.json", "final_labels.json")):
        raise ValueError("invalid or withheld replay-audit path")
    result = root / path
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("replay audit path escaped the run")
    return result


def read_json(root, name):
    return json.loads(inside(root, name).read_bytes())


def arrays(root, name):
    with np.load(inside(root, name), allow_pickle=False) as archive:
        return {key: archive[key].copy() for key in archive.files}


def array_sha(value):
    value = np.ascontiguousarray(value)
    return sha(canonical([value.dtype.str, list(value.shape)]) + value.tobytes())


def checkpoint(root, directory):
    manifest = read_json(root, directory + "/manifest.json")
    payload = inside(root, directory + "/state.npz").read_bytes()
    values = arrays(root, directory + "/state.npz")
    names = [group + "__" + name for group in ("theta", "m", "v")
             for name in manifest["parameter_names"]]
    if (set(names) != set(values) or sha(payload) != manifest["payload_sha256"]
            or manifest["tensor_sha256"] != {key: array_sha(value) for key, value in values.items()}
            or any(value.dtype != np.float64 or not np.isfinite(value).all() for value in values.values())
            or sum(value.nbytes for value in values.values()) != manifest["retained_tensor_bytes"]):
        raise ValueError("replay checkpoint payload or tensor identity differs")
    vector = np.concatenate([values[name].ravel() for name in names])
    excluded = {"state_sha256", "payload_sha256", "tensor_sha256", "retained_tensor_bytes", "authority"}
    metadata = {key: value for key, value in manifest.items() if key not in excluded}
    if (sha(canonical(metadata) + bytes.fromhex(array_sha(vector))) != manifest["state_sha256"]
            or manifest["authority"] != "DENY_ALL"):
        raise ValueError("replay complete-state digest differs")
    return vector, manifest


def _completed(root, entry, record, initial, runs, plan):
    segment = entry["segment"]
    start = 0 if segment == "whole" else plan["evaluation_horizon"] // 2
    prefix = f"replay/{record['run_id']}-{segment}"
    expected_paths = {"result_path": prefix + ".json", "arrays_path": prefix + ".npz",
                      "job_path": prefix + ".job.json"}
    if any(entry.get(key) != value for key, value in expected_paths.items()):
        raise ValueError("registered replay artifact paths differ")
    job, result = read_json(root, entry["job_path"]), read_json(root, entry["result_path"])
    if (record["status"] != "completed" or job["record"] != record or job["initial"] != initial
            or job["protocol"] != plan or job["segment"] != segment or job["start"] != start
            or job["source_hashes"] != runs["sourcecode_hashes"] or job["output_prefix"] != prefix
            or result["run_id"] != record["run_id"] or result["segment"] != segment
            or result["start"] != start or result["authority"] != "DENY_ALL"
            or result["validation_labels_opened"] is not False or result["final_labels_opened"] is not False):
        raise ValueError("replay job/result identity or boundary differs")
    paths = record["paths"]
    required = {"inputs/protocol.json", "train_inputs.npz", "projected_features.npz",
                paths["reference"], paths["model"], paths["candidate"], paths["candidate_record"],
                paths["trajectory"], paths["receipts"], *initial["model_paths"].values()}
    for directory in (initial["checkpoint_path"], paths["midpoint"], paths["checkpoint"]):
        required.update({directory + "/manifest.json", directory + "/state.npz"})
    if set(job["inputs"]) != required or read_json(root, "inputs/protocol.json") != plan:
        raise ValueError("replay input census or stored protocol differs")
    for name, expected in job["inputs"].items():
        if sha(inside(root, name).read_bytes()) != expected:
            raise ValueError("replay input hash differs: " + name)
    for name, expected in job["source_hashes"].items():
        if sha(inside(root, "source/" + name).read_bytes()) != expected:
            raise ValueError("replay archived source hash differs: " + name)
    expected, replayed = arrays(root, paths["trajectory"]), arrays(root, entry["arrays_path"])
    keys = {"states", "observations", "actions", "fields"}
    if set(replayed) != keys or set(result["arrays"]) != keys:
        raise ValueError("replay array census differs")
    for key, value in replayed.items():
        wanted = expected[key][start:]
        identity = {"sha256": array_sha(value), "shape": list(value.shape), "dtype": value.dtype.str}
        if (value.dtype != wanted.dtype or not np.array_equal(value, wanted)
                or result["arrays"][key] != identity):
            raise ValueError("independent replay suffix/identity differs: " + key)
    receipts = read_json(root, paths["receipts"])
    if result["receipts"] != receipts[start:]:
        raise ValueError("replay transition receipts differ")
    original_vector, original_manifest = checkpoint(root, paths["checkpoint"])
    final_vector, final_manifest = checkpoint(root, prefix + ".checkpoint")
    initial_vector, initial_manifest = checkpoint(root, initial["checkpoint_path"])
    start_path = initial["checkpoint_path"] if start == 0 else paths["midpoint"]
    start_vector, start_manifest = checkpoint(root, start_path)
    wanted_start_digest = initial["state_sha256"] if start == 0 else receipts[start - 1]["state_sha256"]
    wanted_start_step = initial_manifest["step_count"] + start
    wanted_final_step = initial_manifest["step_count"] + plan["evaluation_horizon"]
    if (not np.array_equal(final_vector, replayed["states"][-1])
            or not np.array_equal(original_vector, final_vector) or final_manifest != original_manifest
            or not np.array_equal(start_vector, replayed["states"][0])
            or not np.array_equal(initial_vector, expected["states"][0])
            or job["start_checkpoint"] != start_path or job["start_state_sha256"] != wanted_start_digest
            or start_manifest["state_sha256"] != wanted_start_digest
            or final_manifest["state_sha256"] != record["final_state_sha256"]
            or result["state_sha256"] != record["final_state_sha256"]
            or start_manifest["step_count"] != wanted_start_step
            or result["start_step"] != wanted_start_step or entry["start_step"] != wanted_start_step
            or final_manifest["step_count"] != wanted_final_step
            or result["final_step"] != wanted_final_step or entry["final_step"] != wanted_final_step):
        raise ValueError("replay complete checkpoint, suffix boundary or step differs")
    flags = {"states", "observations", "actions", "fields", "transition_receipts",
             "final_state_digest", "complete_final_manifest"}
    if (set(result["matches"]) != flags or not all(value is True for value in result["matches"].values())
            or entry["matches"] != result["matches"]):
        raise ValueError("replay self-reported comparisons disagree with independent checks")
    recomputed = segment == "whole"
    if (result["candidate_recomputed"] is not recomputed or entry["candidate_recomputed"] is not recomputed
            or entry["candidate_arithmetic_equal_excluding_timing"] != result["candidate_arithmetic_equal_excluding_timing"]
            or (recomputed and (result["candidate_arithmetic_equal_excluding_timing"] is not True
                or result["both_model_predictions_equal"] != {"loss2": True, "full": True}))
            or (not recomputed and (result["candidate_arithmetic_equal_excluding_timing"] is not None
                                    or result["both_model_predictions_equal"] is not None))):
        raise ValueError("candidate recomputation or two-model claim differs")
    process = read_json(root, prefix + ".process.json")
    command = [process["command"][0], "-B", str(Path(job["source_directory"]) / "cell_field_action_replay.py"),
               "--job", str(Path(job["root"]) / entry["job_path"])]
    if (process["exit_code"] != 0 or process["command"] != command
            or process["wall_ns"] != entry["wall_ns_including_process"]):
        raise ValueError("replay process receipt differs")
    inside(root, prefix + ".stdout.log").read_bytes()
    inside(root, prefix + ".stderr.log").read_bytes()
    return {"run_id": record["run_id"], "segment": segment, "status": "completed",
            "arrays_verified": len(keys), "input_files_verified": len(required),
            "source_files_verified": len(job["source_hashes"]), "complete_manifest_equal": True,
            "candidate_recomputed": recomputed}


def audit_replays(root, runs, plan):
    root = Path(root)
    before = read_json(root, "execution_result_before_replay.json")
    if (before["records"] != runs["records"] or before["record_count"] != len(runs["records"])
            or before["validation_labels_opened"] is not False or before["final_labels_opened"] is not False):
        raise ValueError("scientific execution outcomes changed during replay handling")
    declared = plan["replay"]
    targets = {}
    for seed, head in itertools.product(declared["seeds"], declared["heads"]):
        rows = [row for row in runs["records"] if row["seed"] == seed and row["head"] == head
                and row["anchor_offset"] == declared["anchor_offset"]
                and row["method_id"] == declared["method_id"]]
        if len(rows) != 1 or rows[0]["run_id"] in targets:
            raise ValueError("registered replay target census differs")
        targets[rows[0]["run_id"]] = rows[0]
    indexed = {}
    for entry in runs["replays"]:
        if entry["run_id"] not in targets:
            raise ValueError("unregistered replay target present")
        segments = [entry["segment"]] if "segment" in entry else ["whole", "midpoint"]
        if "segment" not in entry and entry["status"] not in ("failed", "unavailable"):
            raise ValueError("segment-free replay must retain an explicit failure")
        for segment in segments:
            key = (entry["run_id"], segment)
            if segment not in ("whole", "midpoint") or key in indexed:
                raise ValueError("duplicate or invalid replay segment")
            indexed[key] = entry
    outcomes = []
    for run_id, record in targets.items():
        for segment in ("whole", "midpoint"):
            entry = indexed.get((run_id, segment))
            if entry is None:
                outcomes.append({"run_id": run_id, "segment": segment, "status": "missing"})
            elif entry["status"] == "completed":
                initial = runs["initial_order"][record["initial_index"]]
                outcomes.append(_completed(root, entry, record, initial, runs, plan))
            elif entry["status"] in ("failed", "unavailable"):
                outcomes.append({"run_id": run_id, "segment": segment, "status": entry["status"],
                                 "scientific_execution_status": record["status"],
                                 "detail": entry.get("error", entry.get("reason"))})
            else:
                raise ValueError("unknown replay outcome status")
    census = dict(Counter(row["status"] for row in outcomes))
    failures = [row for row in outcomes if row["status"] != "completed"]
    return {"schema": "hepta.cell-action-independent-replay-audit.v3",
            "registered_targets": len(targets), "registered_segments": 2 * len(targets),
            "status_census": census, "all_registered_replays_passed": not failures,
            "outcomes": outcomes, "failures": failures, "scientific_records_preserved": True,
            "planner_imported": False, "training_state_imported": False, "replay_implementation_imported": False}
