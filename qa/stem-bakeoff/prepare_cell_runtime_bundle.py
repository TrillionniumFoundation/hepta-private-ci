"""Extract an exactly pinned, portable 770D systems-regression input bundle."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np

from cell_action_prepare import verify_action_prepared
from cell_learning_models import canonical
from cell_runtime_bundle import (MANIFEST_SCHEMA, MODES, SCHEMA, array_digest, inventory,
                                 load_serving_inputs, load_states, load_training_inputs, sha_file)


PREPARED = "learning-preparation/preparations/granite_clean_field770"
FEATURES = "features-inputs-granite-clean-field770"
INPUT_PINS = {
    "inputs/inputs.json": "42f2fa9ef5a19df8c43d2e39b4103c04bd421931c879f2f64c85aaff7b4c26ab",
    PREPARED+"/seal.json": "eebed3e3852a93c8099f60dc86ea1b34368cce8969d8cd88576374c3406bfdb0",
    FEATURES+"/report.json": "b1c3f24911f18d2c97561d666170987b23f087e2b89fedbf834f4384ad598dc6",
    FEATURES+"/features.npz": "985efc37dd99ff4de635bf79345dc0dd3a23d8a7975c7fe4423bd9c1b7e392f2",
    FEATURES+"/source-bindings.json": "2e2f890751d9e6e66a55f412af4369bdb25437dd3235bef853d28b4461fdd9f4",
    FEATURES+"/feature-availability.json": "def1d3f1bdfb22a69e6e743de1d21f40fb96a7996207735afce54f16df4fbeae",
}
IDENTITY = "00b09d213137fd60d33b39761d462f69b6e692155f51b7efd77896911cbd62c0"


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value)+b"\n")


def prepare(source, output):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    source, output = Path(source).absolute(), Path(output).absolute()
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("new nonsymlink output root required")
    for relative, expected in INPUT_PINS.items():
        if sha_file(source/relative) != expected:
            raise ValueError(f"frozen upstream pin differs: {relative}")
    prepared = source/PREPARED
    frozen = verify_action_prepared(prepared)
    plan = frozen["plan"]
    if plan["feature_identity"] != IDENTITY or (plan["width"], plan["classes"]) != (770, 2):
        raise ValueError("unexpected frozen native representation")
    feature_report = json.loads((source/FEATURES/"report.json").read_bytes())
    data = json.loads((source/"inputs/inputs.json").read_bytes())
    bindings = json.loads((source/FEATURES/"source-bindings.json").read_bytes())
    with np.load(source/FEATURES/"features.npz", allow_pickle=False) as archive:
        if set(archive.files) != {"features"}:
            raise ValueError("unexpected original feature archive")
        x = archive["features"]
    rows = data["rows"]
    if (data.get("all_labels_unobserved") is not True or len(rows) != 805
            or x.shape != (805, 770) or x.dtype != np.float32 or not np.isfinite(x).all()
            or feature_report["feature_identity"] != IDENTITY
            or hashlib.sha256(x.tobytes()).hexdigest() != feature_report["feature_tensor_sha256"]
            or len(bindings) != len(rows)):
        raise ValueError("exact pre-outcome input and native feature bank required")
    lookup, compact = {}, []
    for index, (row, binding, vector) in enumerate(zip(rows, bindings, x, strict=True)):
        text = row["text"].encode()
        record_digest = hashlib.sha256(canonical(binding)).hexdigest()
        if (row["source_id"] in lookup or row["source_id"] != binding["source_id"]
                or any(label is not None for label in row["labels"].values())
                or hashlib.sha256(text).hexdigest() != row["text_utf8_sha256"]
                or len(text) != row["text_utf8_bytes"]
                or record_digest != feature_report["source_record_digests"][index]):
            raise ValueError("pre-outcome source bytes, order or record identity differ")
        lookup[row["source_id"]] = index
        compact.append({"source_id": row["source_id"], "group_id": row["group_id"],
            "text_utf8_sha256": row["text_utf8_sha256"], "source_record_digest": record_digest,
            "feature_row_sha256": hashlib.sha256(vector.tobytes()).hexdigest()})
    selected = sorted(range(len(rows)), key=lambda i: hashlib.sha256(rows[i]["source_id"].encode()).hexdigest())[:64]
    run = next(r for r in frozen["runs"] if (r["seed"], r["budget"]) == (7, 32))
    training_root = prepared/run["directory"]
    original_training_rows = json.loads((training_root/"baseline_rows.json").read_bytes())
    with np.load(training_root/"baseline.npz", allow_pickle=False) as archive:
        train_x, train_y = archive["features"], archive["labels"]
    training_indices = [lookup[r["source_id"]] for r in original_training_rows]
    if (train_x.shape != (32, 770) or train_y.dtype != np.int64 or train_y.shape != (32,)
            or not np.array_equal(train_x, x[training_indices])
            or any(rows[i]["split"] != "train" for i in training_indices)
            or [rows[i]["source_id"] for i in training_indices] != run["training_source_ids"]
            or [rows[i]["group_id"] for i in training_indices] != run["training_group_ids"]
            or len(set(run["training_group_ids"])) != 32
            or any(r["text"] != rows[i]["text"] for r, i in zip(original_training_rows, training_indices, strict=True))):
        raise ValueError("unchanged source-bound TRAIN-only baseline required")
    output.mkdir(parents=True)
    (output/"provenance").mkdir()
    for name in ("frozen.json", "seal.json", "plan.json"):
        shutil.copyfile(prepared/name, output/"provenance"/name)
    write_json(output/"provenance/upstream-input-pins.json", INPUT_PINS)
    write_json(output/"provenance/feature-summary.json", {k: feature_report[k] for k in
        ("feature_identity", "feature_shape", "feature_tensor_sha256", "source_bindings_sha256",
         "encoder_instances", "encoder_forward_calls", "cost")})
    with (output/"serving.npz").open("xb") as stream:
        np.savez_compressed(stream, features=x[selected])
    shutil.copyfile(training_root/"baseline.npz", output/"training.npz")
    write_json(output/"serving-rows.json", [compact[i] for i in selected])
    write_json(output/"training-rows.json", [compact[i] for i in training_indices])
    source_indices = sorted(set(selected+training_indices))
    write_json(output/"sources.json", {rows[i]["source_id"]: {"input": rows[i], "binding": bindings[i]}
                                       for i in source_indices})
    states = []
    for run in sorted(frozen["runs"], key=lambda r: (r["seed"], r["budget"])):
        for mode in MODES:
            spec = run["arms"][mode]
            artifact = "heads/"+spec["artifact"]
            target = output/artifact
            target.mkdir(parents=True)
            for name in ("manifest.json", "weights.npz"):
                shutil.copyfile(prepared/spec["artifact"]/name, target/name)
            calibration = artifact+"/calibration.json"
            write_json(output/calibration, spec["calibration"])
            states.append({"seed": run["seed"], "budget": run["budget"], "mode": mode,
                "artifact": artifact, "calibration": calibration, "predictor_sha256": spec["predictor_sha256"],
                "calibration_sha256": hashlib.sha256(canonical(spec["calibration"])).hexdigest()})
    metadata = {"schema": SCHEMA, "feature_identity": IDENTITY, "generation": 1,
        "task_id": plan["task_id"], "width": 770, "classes": 2,
        "calibration_context_sha256": plan["cohorts"]["calibration"], "states": states,
        "source_archive": "sources.json", "source_record_count": len(source_indices),
        "upstream_source_pins": INPUT_PINS,
        "serving": {"archive": "serving.npz", "rows": "serving-rows.json", "labels_included": False,
            "selection": "first64 original pre-outcome inputs ordered by SHA256(source_id)",
            "feature_array_sha256": array_digest(x[selected]), "purpose": "systems_and_numeric_regression_only"},
        "training": {"archive": "training.npz", "rows": "training-rows.json", "role": "train",
            "seed": 7, "budget": 32, "source_ids": [rows[i]["source_id"] for i in training_indices],
            "feature_array_sha256": array_digest(train_x), "label_array_sha256": array_digest(train_y),
            "original_baseline_sha256": sha_file(training_root/"baseline.npz")},
        "encoder_calls_during_bundle_preparation": 0, "parameter_updates": 0,
        "quality_qualified": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    write_json(output/"bundle.json", metadata)
    write_json(output/"manifest.json", {"schema": MANIFEST_SCHEMA, "files": inventory(output)})
    manifest_sha = sha_file(output/"manifest.json")
    load_training_inputs(output, expected_manifest_sha256=manifest_sha)
    load_serving_inputs(output, expected_manifest_sha256=manifest_sha)
    for mode in MODES:
        load_states(output, metadata, mode)
    if verify_action_prepared(prepared) != frozen or any(sha_file(source/p) != h for p, h in INPUT_PINS.items()):
        raise ValueError("upstream inputs changed during portable bundle construction")
    return {"schema": "hepta.action-runtime-bundle-preparation.v1", "manifest_sha256": manifest_sha,
        "bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
        "source_records": len(source_indices), "frozen_states": len(states), "tasks": 1,
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "scope": "inclusive verification/copy/serialization/full reload; excludes this receipt write",
        "upstream_unchanged": True, "encoder_calls": 0, "gradient_updates": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    arguments = parser.parse_args()
    result = prepare(arguments.source, arguments.output)
    write_json(arguments.receipt, result)
    print(json.dumps(result))
