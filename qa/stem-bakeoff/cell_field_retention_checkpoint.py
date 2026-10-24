"""Exclusive, checksummed local retention-run checkpoints; no execution authority.

Only a fully published paused run may resume. A failed run can be preserved for
diagnosis, but cannot be loaded as a successful/pause checkpoint. Complete Adam,
sampler, context and identity come from the unchanged CellTrainingState format.
"""

import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from cell_field_retention_run import RUN_PROFILE
from cell_field_state import CellTrainingState
from cell_learning_models import canonical


ARRAY_NAMES = ("states", "observations", "fields", "actions", "target", "legacy_target")
FILES = ("trajectory.npz", "run.json", "state/manifest.json", "state/state.npz")
SCHEMA = "hepta.cell-retention.checkpoint.v1"


def _file(path, maximum=32 * 1024**2):
    if (any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > maximum):
        raise ValueError("bounded regular checkpoint file required")
    data = path.read_bytes()
    return data, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def save_retention_run(directory, result):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    root = Path(directory)
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError("checkpoint symlink paths rejected")
    receipt, state = result["receipt"], result["state"]
    if (receipt["profile"] != RUN_PROFILE or receipt["authority"] != "DENY_ALL"
            or receipt["status"] not in ("paused", "failed", "completed")
            or type(state) is not CellTrainingState
            or state.digest() != receipt["actual_state_sha256"]):
        raise ValueError("actual run state and receipt identity required")
    root.mkdir(parents=True, exist_ok=False)
    state.save(root / "state")
    with (root / "trajectory.npz").open("xb") as stream:
        np.savez_compressed(stream, **{name: result[name] for name in ARRAY_NAMES})
    with (root / "run.json").open("xb") as stream:
        stream.write(canonical({"receipt": receipt, "steps": result["steps"],
                                "costs": result["costs"]}) + b"\n")
    files = {name: _file(root / name)[1] for name in FILES}
    manifest = {"schema": SCHEMA, "status": receipt["status"],
                "contract_sha256": receipt["contract_sha256"],
                "actual_state_sha256": state.digest(), "files": files,
                "write_wall_ns_before_manifest": time.perf_counter_ns() - started,
                "write_cpu_ns_before_manifest": time.process_time_ns() - cpu_started,
                "publication": "manifest written last; no existing directory is overwritten",
                "durability": "local completed writes; no fsync/power-loss guarantee",
                "authority": "DENY_ALL"}
    with (root / "manifest.json").open("xb") as stream:
        stream.write(canonical(manifest) + b"\n")
    return manifest


def load_retention_pause(directory, initial_state):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    root = Path(directory)
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError("checkpoint symlink paths rejected")
    manifest_data, _ = _file(root / "manifest.json", 1024**2)
    manifest = json.loads(manifest_data)
    if (manifest.get("schema") != SCHEMA or manifest.get("status") != "paused"
            or manifest.get("authority") != "DENY_ALL" or set(manifest["files"]) != set(FILES)
            or type(initial_state) is not CellTrainingState):
        raise ValueError("only a complete paused checkpoint may be loaded for replay")
    verified = {}
    for name, expected in manifest["files"].items():
        payload, identity = _file(root / name)
        if identity != expected:
            raise ValueError("checkpoint file checksum/size differs")
        verified[name] = payload
    if len(verified["run.json"]) > 8 * 1024**2:
        raise ValueError("bounded run receipt required")
    run = json.loads(verified["run.json"])
    receipt = run["receipt"]
    if (receipt.get("profile") != RUN_PROFILE or receipt.get("status") != "paused"
            or receipt.get("authority") != "DENY_ALL" or run["costs"] is not None
            or receipt["initial_state_sha256"] != initial_state.digest()
            or receipt["actual_state_sha256"] != manifest["actual_state_sha256"]
            or receipt["contract_sha256"] != manifest["contract_sha256"]
            or hashlib.sha256(canonical(receipt["contract"])).hexdigest()
            != manifest["contract_sha256"]):
        raise ValueError("paused run/checkpoint/original state identity differs")
    state = CellTrainingState.load(root / "state", initial_state.bindings,
        expected_protocol=initial_state.protocol, expected_contexts=initial_state.contexts,
        expected_state_digest=manifest["actual_state_sha256"])
    with zipfile.ZipFile(io.BytesIO(verified["trajectory.npz"])) as archive:
        if (len(archive.infolist()) != len(ARRAY_NAMES)
                or sum(item.file_size for item in archive.infolist()) > 16 * 1024**2):
            raise ValueError("bounded exact trajectory tensor archive required")
    with np.load(io.BytesIO(verified["trajectory.npz"]), allow_pickle=False) as values:
        if set(values.files) != set(ARRAY_NAMES):
            raise ValueError("unexpected checkpoint trajectory tensors")
        arrays = {name: values[name].copy() for name in ARRAY_NAMES}
    if any(v.dtype != np.float64 or not np.isfinite(v).all() for v in arrays.values()):
        raise ValueError("finite float64 checkpoint trajectories required")
    for name in ("state/manifest.json", "state/state.npz"):
        if _file(root / name)[1] != manifest["files"][name]:
            raise ValueError("state checkpoint changed during restoration")
    n, cursor, d = receipt["expected_steps"], receipt["applied_steps"], len(initial_state.vector())
    if (type(n) is not int or type(cursor) is not int or not 1 <= cursor < n <= 64
            or arrays["states"].shape != (cursor + 1, d)
            or arrays["observations"].shape != (cursor + 1, 4)
            or arrays["fields"].shape != (cursor + 1, 2)
            or arrays["target"].shape != (n + 1, 2)
            or arrays["legacy_target"].shape != (n + 1, 2)
            or arrays["actions"].ndim != 2 or arrays["actions"].shape[0] != cursor
            or not 1 <= arrays["actions"].shape[1] <= 128
            or not np.array_equal(arrays["states"][-1], state.vector())
            or state.step_count != initial_state.step_count + cursor
            or len(run["steps"]) != cursor):
        raise ValueError("checkpoint cursor or complete-state trajectory differs")
    return {**arrays, **run, "state": state,
            "checkpoint_cost": {"write_manifest": manifest,
                "load_wall_ns": time.perf_counter_ns() - started,
                "load_cpu_ns": time.process_time_ns() - cpu_started}}
