"""Diagnose the failed V5 audit without granting admission or changing its gate.

The CLI requires committed diagnostic source before reading current endpoints.
The pure audit function has no Git dependency, enabling manifest-verified literal
restoration. Neither entrypoint constructs or evaluates a neural model.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import torch

from ..field_bridge_v3_20261027.training_common import file_hash, object_hash, require
from ..field_bridge_v4_20261027_review.training_panel_origin import fit_origin
from ..field_bridge_v5_20261027 import audit as frozen
from ..field_bridge_v5_20261027.calibration import load_saved
from ..field_bridge_v5_20261027.run import check_freeze


HERE = Path(__file__).resolve().parent
PORTFOLIO = HERE.parent
V5 = PORTFOLIO / "field_bridge_v5_20261027"
V3 = PORTFOLIO / "field_bridge_v3_20261027"
PROTOCOL = HERE / "DIAGNOSTIC_PROTOCOL.json"
SOURCE_NAMES = ("diagnostic_audit.py", "DIAGNOSTIC_PROTOCOL.json")


def read_json(path):
    return json.loads(Path(path).read_text())


def verify_registration(commit, repository):
    """Compare these local source bytes with a committed tree; load no live data."""
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "Invalid diagnostic registration commit")
    repository = Path(repository).resolve()
    prefix = "experiments/multimodal_output_portfolio/field_bridge_v5_20261027_review/"
    paths = [prefix + name for name in SOURCE_NAMES]
    output = subprocess.run(["git", "-C", str(repository), "ls-tree", "-rz", commit, "--", *paths],
                            check=True, capture_output=True).stdout
    tree = {}
    for row in output.split(b"\0"):
        if row:
            metadata, path = row.split(b"\t", 1)
            mode, kind, identity = metadata.split()
            require(mode == b"100644" and kind == b"blob", "Unexpected diagnostic source object")
            tree[path.decode()] = identity.decode()
    require(set(tree) == set(paths), "Diagnostic sources must be committed before execution")
    files = {}
    for name in SOURCE_NAMES:
        raw = (HERE / name).read_bytes()
        identity = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(identity == tree[prefix + name], "Diagnostic source differs from registered commit")
        files[name] = {"git_blob_sha": identity, "sha256": hashlib.sha256(raw).hexdigest()}
    return {"registered_commit": commit, "method": "local source bytes versus committed Git tree", "files": files}


def fixed_inputs(run, freeze_path, diagnostic):
    """Bind the known failure and every sealed phase, without redefining success."""
    require(file_hash(freeze_path) == diagnostic["scientific_source_freeze_sha256"], "Scientific freeze changed")
    require(file_hash(V5 / "PROTOCOL.json") == diagnostic["scientific_protocol_sha256"], "Scientific protocol changed")
    failed_path = run / diagnostic["failed_frozen_audit"]["filename"]
    require(file_hash(failed_path) == diagnostic["failed_frozen_audit"]["sha256"], "Original failed audit changed")
    failed = read_json(failed_path)
    require(all(failed.get(key) == diagnostic["failed_frozen_audit"][key]
                for key in ("integrity_status", "error_type", "error")), "Different frozen audit failure")
    require(failed["integrity_status"] == "FAIL", "This diagnostic requires the original FAIL")
    expected = {f"{phase}/{seed}" for phase in ("train", "evaluate") for seed in (17, 29, 43)}
    require(set(diagnostic["phase_seals"]) == expected, "Incomplete registered phase census")
    actual = {name: file_hash(run / name / "COMPLETE.json") for name in expected}
    require(actual == diagnostic["phase_seals"], "A registered phase seal changed")
    return failed, actual


def describe_difference(current, historical, observer_axis, observers):
    """Describe exact discrepancies; there is no approximate-equality pass gate."""
    current, historical = np.asarray(current), np.asarray(historical)
    require(current.shape == historical.shape and current.shape[observer_axis] == len(observers)
            and np.isfinite(current).all() and np.isfinite(historical).all(), "Incomparable historical arrays")
    delta = current - historical

    def summary(values):
        return {"values": int(values.size), "changed_values": int(np.count_nonzero(values)),
                "mean_signed_difference": float(values.mean()),
                "maximum_absolute_difference": float(np.abs(values).max()),
                "mean_absolute_difference": float(np.abs(values).mean()),
                "rmse": float(np.sqrt(np.square(values).mean())),
                "minimum_signed_difference": float(values.min()), "maximum_signed_difference": float(values.max())}

    return {"exact": bool(np.array_equal(current, historical)), "shape": list(delta.shape),
            **summary(delta), "per_observer": {name: summary(np.take(delta, index, axis=observer_axis))
                                               for index, name in enumerate(observers)},
            "tolerance_pass": None}


def historical_differences(protocol, endpoints, run):
    """Compare old arrays without calling or altering the failing regression gate."""
    selection = read_json(V3 / "evidence/DEVELOPMENT_SELECTION.json")
    runtime = read_json(V3 / "evidence/ARCHIVE_RUNTIME_ENVIRONMENT.json")
    seeds = {}
    sources = ("field_bridge_v3_20261027/learning.py", "field_bridge_20261027/adapters.py",
               "v6/neural.py", "v6/data.py", "v6/observer.py")
    for seed, current in zip(protocol["seeds"], endpoints, strict=True):
        old = V3 / "evidence/development" / str(seed)
        path = old / "ENDPOINTS.npz"
        require(file_hash(path) == selection["endpoint_file_sha256"][str(seed)], "Historical endpoint identity changed")
        start = read_json(old / "START.json")
        with np.load(path, allow_pickle=False) as packed:
            previous = {key: packed[key].copy() for key in packed.files}
        panel_ids = read_json(run / "evaluate" / str(seed) / "PANELS.json")
        require(previous["schedule_ids"].tolist() == protocol["schedules"]
                and previous["observer_names"].tolist() == protocol["observers"], "Historical axes changed")
        action = protocol["baseline_actions"][str(seed)]
        require(selection["ordinary_action_indices"][str(seed)] == action, "Historical ordinary action changed")
        old_method, current_method = "ordinary_" + str(action), "ordinary_48"
        old_index = previous["methods"].tolist().index(old_method)
        current_index = protocol["methods"].index(current_method)
        data = {}
        for endpoint in ("task", "clean"):
            require(str(previous[endpoint + "_panel_identity"]) == panel_ids[endpoint]["sha256"],
                    "Old/current panel identities differ")
            old_frozen, new_frozen = previous["original_" + endpoint], current["frozen_" + endpoint]
            old_ordinary = previous[endpoint + "_values"][old_index]
            new_ordinary = current[endpoint][current_index]
            data[endpoint] = {
                "frozen": describe_difference(new_frozen, old_frozen, 0, protocol["observers"]),
                "ordinary": describe_difference(new_ordinary, old_ordinary, 1, protocol["observers"]),
                "ordinary_minus_frozen_gain": describe_difference(
                    new_ordinary - new_frozen[None], old_ordinary - old_frozen[None], 1, protocol["observers"])}
        seeds[str(seed)] = {"old_endpoint_sha256": file_hash(path), "old_method": old_method,
                           "current_method": current_method, "endpoints": data,
                           "core_source_matches": {name: file_hash(PORTFOLIO / name) == start["source_files"][name]
                                                   for name in sources}}
    runtime_match = (runtime["torch"] == protocol["runtime"]["torch"]
                     and runtime["numpy"] == protocol["runtime"]["numpy"]
                     and runtime["training_torch_threads"] == protocol["runtime"]["torch_threads"]
                     and runtime["interop_threads"] == protocol["runtime"]["interop_threads"])
    return {"status": "FAIL", "exact_regression_gate_unchanged": True, "tolerance_pass_threshold": None,
            "causal_attribution": "UNDETERMINED", "recorded_old_runtime": runtime,
            "recorded_runtime_matches": runtime_match, "seeds": seeds}


def audit(run, freeze_path, diagnostic_registered_commit):
    """Pure artifact computation; caller must independently validate registration.

    Literal restore callers must verify the full manifest first and execute this
    restored module in a new process. All scientific sources/old inputs resolve
    relative to this module; no Git repository or live source is consulted here.
    """
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    require(re.fullmatch(r"[0-9a-f]{40}", diagnostic_registered_commit) is not None, "Missing diagnostic registration")
    run, freeze_path = Path(run).resolve(), Path(freeze_path).resolve()
    diagnostic = read_json(PROTOCOL)
    require(diagnostic["schema"] == "hepta.field-bridge.v5.failure-diagnostic-protocol.1", "Unknown diagnostic protocol")
    source_ids = {name: file_hash(HERE / name) for name in SOURCE_NAMES}
    failed, seals = fixed_inputs(run, freeze_path, diagnostic)
    protocol, freeze = check_freeze(freeze_path)
    require(freeze["registered_commit"] == diagnostic["scientific_registered_commit"]
            and protocol["study_id"] == diagnostic["study_id"]
            and protocol["observers"] == ["reward", "audit"]
            and protocol["descriptive_comparisons"] == diagnostic["descriptive_comparisons"]
            and protocol["development_entry"] == diagnostic["numeric_development_entry_rule"], "Diagnostic changed scientific scope")
    require(torch.__version__ == protocol["runtime"]["torch"] and np.__version__ == protocol["runtime"]["numpy"],
            "Pinned runtime mismatch")
    training = read_json(V3 / "PROTOCOL.json")["training"]
    calibration = read_json(V5 / "evidence/CALIBRATION.json")["seeds"]
    stages, starts = {}, {}
    for phase in ("train", "evaluate"):
        require({item.name for item in (run / phase).iterdir() if item.is_dir()}
                == {str(seed) for seed in protocol["seeds"]}, "Incomplete seed census")
        for seed in protocol["seeds"]:
            key, directory = f"{phase}/{seed}", run / phase / str(seed)
            sealed, start = frozen.verify_stage(directory), read_json(directory / "START.json")
            require(start["phase"] == phase and start["seed"] == seed and start["new_holdout_access"] is False
                    and start["study_id"] == protocol["study_id"] and start["freeze_sha256"] == file_hash(freeze_path)
                    and start["protocol_sha256"] == diagnostic["scientific_protocol_sha256"]
                    and start["registered_commit"] == freeze["registered_commit"], "Stage registration mismatch")
            require(start["torch"] == protocol["runtime"]["torch"] and start["numpy"] == protocol["runtime"]["numpy"]
                    and sealed["completed_unix_ns"] >= start["started_unix_ns"], "Stage runtime/clock mismatch")
            stages[key], starts[key] = sealed, start
    require(min(starts[f"evaluate/{seed}"]["started_unix_ns"] for seed in protocol["seeds"])
            >= max(stages[f"train/{seed}"]["completed_unix_ns"] for seed in protocol["seeds"]), "Endpoint barrier violated")
    paths, endpoints = [], []
    for seed in protocol["seeds"]:
        destination, sealed = run / "train" / str(seed), stages[f"train/{seed}"]
        expected = {f"{method}/{schedule}" for method in protocol["methods"] for schedule in protocol["schedules"]}
        require({row["path"] for row in sealed["paths"]} == expected
                and sealed["train_paths"] == len(sealed["paths"]) == len(expected)
                and sealed["endpoint_access"] is False, "Incomplete training census")
        for binding in sealed["paths"]:
            require(file_hash(destination / binding["path"] / "PATH.json") == binding["record_sha256"], "Path binding mismatch")
        bank, fitted, _ = load_saved(V3 / "evidence", seed)
        rows = [frozen.audit_path(destination / method / str(schedule), protocol, training, seed, method,
                                 schedule, fitted, fit_origin(bank), calibration[str(seed)]["tau"])
                for method in protocol["methods"] for schedule in protocol["schedules"]]
        require(len({object_hash(row["initial"]) for row in rows}) == 1
                and len({row["frozen_base_sha256"] for row in rows}) == 1, "Unequal path initialization/base")
        paths.extend(rows)
        evaluation = stages[f"evaluate/{seed}"]
        require(evaluation["new_holdout_access"] is False and evaluation["training_seals"]
                == {str(item): seals[f"train/{item}"] for item in protocol["seeds"]}, "Evaluation training seals differ")
        endpoints.append(frozen.audit_endpoints(run / "evaluate" / str(seed), protocol))
    require(len(paths) == diagnostic["expected_paths"] == protocol["paths"] == 72, "Incomplete global census")
    numeric = frozen.comparisons(protocol, endpoints, paths)
    numerical_entry = numeric.pop("development_entry")
    entry = {**numerical_entry, "numeric_passed": numerical_entry["passed"], "passed": False,
             "admission": False, "new_holdout_authorized": False,
             "override_reason": "Original frozen historical-regression audit remains FAIL; numeric checks are diagnostic only"}
    differences = historical_differences(protocol, endpoints, run)
    for name in seals:
        frozen.verify_stage(run / name)
    fixed_inputs(run, freeze_path, diagnostic)
    check_freeze(freeze_path)
    require(source_ids == {name: file_hash(HERE / name) for name in SOURCE_NAMES}, "Diagnostic source changed during analysis")
    return {"schema": "hepta.field-bridge.v5.failed-audit-diagnostic.1", "within_run_integrity": "PASS",
            "overall_status": "FAIL", "historical_regression_status": "FAIL", "admission": False,
            "new_holdout_access": False, "new_holdout_authorized": False, "certificate": False,
            "study_id": protocol["study_id"], "diagnostic_registered_commit": diagnostic_registered_commit,
            "scientific_registered_commit": freeze["registered_commit"], "diagnostic_sources": source_ids,
            "failed_frozen_audit_sha256": diagnostic["failed_frozen_audit"]["sha256"], "failed_frozen_audit": failed,
            "source_freeze_sha256": diagnostic["scientific_source_freeze_sha256"],
            "protocol_sha256": diagnostic["scientific_protocol_sha256"], "phase_seals": seals,
            "scope": "Post-failure artifact diagnosis only; no replacement of frozen audit or acceptance criterion",
            "new_model_evaluations": 0, "scientific_retries": 0, "paths": paths,
            "phase_resources": {phase: [{key: stages[f"{phase}/{seed}"][key]
                                          for key in ("seed", "resources", "cpu_ns", "wall_ns")}
                                         for seed in protocol["seeds"]] for phase in ("train", "evaluate")},
            "development_entry": entry, "historical_descriptive_differences": differences,
            **numeric, "diagnostic_cpu_ns": time.process_time_ns() - cpu,
            "diagnostic_wall_ns": time.perf_counter_ns() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--registered-commit", required=True)
    parser.add_argument("--registration-repository", type=Path, default=HERE.parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.output.resolve() == (args.run_root / "WITHIN_RUN_AUDIT.json").resolve(), "Diagnostic output name is fixed")
    require(not args.output.exists(), "Refusing diagnostic overwrite")
    registration = verify_registration(args.registered_commit, args.registration_repository)
    try:
        report = audit(args.run_root, args.freeze, args.registered_commit)
        require(verify_registration(args.registered_commit, args.registration_repository) == registration,
                "Diagnostic registration changed during analysis")
    except Exception as error:
        diagnostic = read_json(PROTOCOL)
        report = {"schema": "hepta.field-bridge.v5.failed-audit-diagnostic.1", "within_run_integrity": "FAIL",
                  "overall_status": "FAIL", "historical_regression_status": "FAIL", "admission": False,
                  "new_holdout_access": False, "new_holdout_authorized": False,
                  "diagnostic_registered_commit": args.registered_commit,
                  "failed_frozen_audit_sha256": diagnostic["failed_frozen_audit"]["sha256"],
                  "source_freeze_sha256": diagnostic["scientific_source_freeze_sha256"],
                  "error_type": type(error).__name__, "error": str(error),
                  "development_entry": {"passed": False, "numeric_passed": None, "new_holdout_authorized": False}}
        with args.output.open("x") as stream:
            json.dump({**report, "source_registration": registration}, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        raise
    with args.output.open("x") as stream:
        json.dump({**report, "source_registration": registration}, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("within_run_integrity", "overall_status", "historical_regression_status", "admission")}))


if __name__ == "__main__":
    main()
