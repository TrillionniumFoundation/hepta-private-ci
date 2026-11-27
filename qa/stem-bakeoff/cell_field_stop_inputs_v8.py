"""Pinned planning-only inputs and all98 original stopped full optimizer states."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from cell_field_state import CellTrainingState, dataset_digest


ORIGINS_SHA = "929d43714529995317be8aa8b7da4e6e0c57ef07418ea533b9d843bc605eb03c"
PLANNING_SHA = "fee97efebd8b20ef2a996cecc3ccc97e901b1272fceecde8e4671749000a0b26"
METHODS = {"myopic_h1": ("full", 1), "loss2_h8": ("loss2", 8), "future_field_h8": ("future_field", 8)}


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


def read(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "ordinary pinned file required: "+str(path))
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def pin_files(directory, pins):
    directory = Path(directory)
    for name, pin in pins.items():
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "relative identity path")
        path = directory/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin["bytes"]
            and file_hash(path) == pin["sha256"], "unchanged input bytes: "+name)


def verify_source_freeze(freeze_path, protocol_path):
    freeze = read(freeze_path)
    require(freeze["protocol_sha256"] == file_hash(protocol_path)
        and len(freeze["source_commit"]) == 40 and freeze["remotely_published"] is True,
        "published protocol and source identity required before diagnostic")
    source = Path(__file__).parent
    hashes = freeze["source_hashes"]
    required = {"cell_field_stop_inputs_v8.py", "cell_field_filter_observer_v8.py", "cell_field_filter_audit_v8.py",
        "cell_field_stop_run_v8.py", "cell_field_proposal_v8.py", "cell_field_safety_v8.py",
        "cell_field_joint_search_v8.py", "cell_field_repair_v7.py", "cell_field_state.py", "cell_learning_models.py",
        "cell_field_response_v7.py", "cell_field_response_v5.py", "cell_field_observable_v7.py",
        "cell_field_qp_v7.py", "cell_learning_metrics.py"}
    require(required <= set(hashes), "complete directly used diagnostic source closure")
    for name, value in hashes.items():
        require(Path(name).name == name and file_hash(source/name) == value, "frozen local source: "+name)
    return freeze


def load_origin_manifest(directory):
    directory = Path(directory)
    require(file_hash(directory/"manifest.json") == ORIGINS_SHA, "exact frozen98-origin manifest")
    manifest = read(directory/"manifest.json")
    rows = manifest["rows"]
    require(manifest["status"] == "PASS" and len(rows) == len({r["slot"] for r in rows}) == 98
        and sum(r["attempted_horizon"] == 1 for r in rows) == 18
        and sum(r["attempted_horizon"] == 8 for r in rows) == 80, "complete18H1/80H8 origin census")
    for row in rows:
        require((row["original_method"], row["attempted_horizon"]) == METHODS[row["policy"]]
            and row["slot"] == f"config{row['configuration_index']:02d}/{row['fit_id']}/{row['policy']}"
            and ".." not in Path(row["slot"]).parts, "registered original method/horizon/source identity")
    return manifest


def load_planning(directory, version, task):
    directory = Path(directory)
    require(file_hash(directory/"index.json") == PLANNING_SHA, "exact previous planning-only data index")
    package = directory/f"{version}-{task}"
    entry = next(r for r in read(directory/"index.json")["packages"] if Path(r["directory"]).name == package.name)
    require(file_hash(package/"manifest.json") == entry["manifest_sha256"], "pinned package manifest")
    meta = read(package/"manifest.json")
    require(meta["selection_labels_included"] is False and (meta["version"], meta["task"]) == (version, task), "planning-only role boundary")
    pin_files(package, meta["files"])
    names = ["current_train"]+[f"{role}_panel_{k}" for role in ("current", "old") for k in range(4)]
    with np.load(package/"arrays.npz", allow_pickle=False) as arrays:
        require(set(arrays.files) == {n+s for n in names for s in ("_x", "_y")}, "no selection arrays")
        pairs = {name: (arrays[name+"_x"], arrays[name+"_y"]) for name in names}
    for name, pair in pairs.items():
        require(dataset_digest(*pair) == meta["contexts"][name]["dataset_sha256"]
            and len(pair[0]) == (256 if name == "current_train" else 96), "exact input panel bytes and counts")
        for array in pair:
            array.flags.writeable = False
    return {"train": pairs["current_train"], "current": [pairs[f"current_panel_{k}"] for k in range(4)],
        "old": [pairs[f"old_panel_{k}"] for k in range(4)], "manifest_sha256": file_hash(package/"manifest.json")}


def load_origin(directory, row, data):
    directory = Path(directory)/row["slot"]
    pin_files(directory, row["files"])
    meta = read(directory/"state/manifest.json")
    state = CellTrainingState.load(directory/"state", meta["bindings"], meta["protocol"], meta["contexts"], row["origin_state_sha256"])
    require(state.protocol["sampler"] == "full_batch" and state.step_count == row["optimizer_step_count"]
        and dataset_digest(*data["train"]) == row["training_sha256"] == state.contexts[state.active_context]
        and [dataset_digest(*p) for p in data["old"]] == row["old_panel_sha256"]
        and [dataset_digest(*p) for p in data["current"]] == row["current_panel_sha256"], "complete physical and data identity")
    snapshot = read(directory/"original-stopped-controller.json")
    require(digest(snapshot) == row["controller_sha256"] and snapshot["run_status"] == "stopped"
        and snapshot["full_state_sha256"] == state.digest(), "original stopped controller stays stopped")
    return state
