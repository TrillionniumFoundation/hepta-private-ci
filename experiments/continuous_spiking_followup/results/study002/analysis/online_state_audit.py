"""Read-only numeric snapshot and original native archive integrity checks."""

import hashlib
import io
import json
from pathlib import PurePosixPath
import tarfile

import numpy as np

from online_audit_common import canonical, check, sha


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checkpoint_model_digest(directory):
    """Rebuild the streaming binding directly from retained tensor bytes."""
    manifest = json.loads((directory / "manifest.json").read_text())
    parts = []
    for part in manifest["parts"]:
        path = directory / part["file"]
        check(sha(path) == part["sha256"], "checkpoint shard identity")
        with np.load(path, allow_pickle=False) as arrays:
            parts.append(arrays["bytes"].tobytes())
    raw, offset, tensors = b"".join(parts), 0, {}
    for tensor in manifest["tensors"]:
        check(tensor["offset"] == offset, "checkpoint packed range")
        value = raw[offset : offset + tensor["nbytes"]]
        dtype = np.dtype(tensor["dtype"])
        check(not dtype.hasobject, "numeric checkpoint dtype")
        check(
            int(np.prod(tensor["shape"])) * dtype.itemsize == len(value),
            "checkpoint shape size",
        )
        check(digest(value) == tensor["sha256"], "checkpoint tensor identity")
        tensors[tensor["name"]] = (tensor, value, dtype.name)
        offset += tensor["nbytes"]
    check(offset == len(raw), "complete checkpoint packed bytes")
    result = hashlib.sha256(json.dumps(manifest["config"], sort_keys=True).encode())
    for name, (tensor, value, dtype) in sorted(tensors.items()):
        metadata = [name, "torch." + dtype, tensor["shape"]]
        result.update(json.dumps(metadata, separators=(",", ":")).encode())
        result.update(value)
    return result.hexdigest()


def read_native_archive(directory, receipt):
    path = directory / receipt["path"]
    check(path.stat().st_size == receipt["bytes"], "native archive size")
    check(sha(path) == receipt["sha256"], "native archive SHA")
    files = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            check(member.isfile(), "native archive contains only ordinary files")
            check(not name.is_absolute() and ".." not in name.parts, "archive path")
            check(member.name not in files, "no duplicate archive member")
            raw = archive.extractfile(member).read()
            check(len(raw) == member.size, "native member complete read")
            files[member.name] = raw
    actual = {
        name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in files.items()
    }
    check(actual == receipt["files"], "every original native file hash/size")
    check(
        sum(map(len, files.values())) == receipt["uncompressed_file_bytes"],
        "native expanded bytes",
    )
    return files


def audit_stream_snapshot(manifest_raw, payload, model_sha256, cursor, batch=1):
    manifest = json.loads(manifest_raw)
    snapshot = manifest["snapshot"]
    check(snapshot["format"] == "hcsn-incremental-state-v2", "stream schema v2")
    check(snapshot["model_sha256"] == model_sha256, "exact neural model binding")
    check(
        snapshot["steps"] == cursor and snapshot["batch_size"] == batch,
        "stream cursor/batch",
    )
    check(snapshot["processed_rows"] == cursor * batch, "uncompacted snapshot work")
    check(digest(payload) == manifest["payload_sha256"], "state payload SHA")
    check(len(payload) == manifest["payload_bytes"], "state serialized size")
    total = 0
    with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
        check(set(arrays.files) == set(manifest["arrays"]), "snapshot array inventory")
        for name, record in manifest["arrays"].items():
            value = arrays[name]
            check(
                not value.dtype.hasobject and np.isfinite(value).all(),
                "finite numeric snapshot",
            )
            check(
                list(value.shape) == record["shape"]
                and str(value.dtype) == record["dtype"],
                "snapshot shape/dtype",
            )
            check(
                value.nbytes == record["bytes"]
                and digest(value.tobytes()) == record["sha256"],
                "snapshot tensor bytes/SHA",
            )
            total += value.nbytes
        check(arrays["elapsed"].dtype == np.float64, "float64 elapsed accumulator")
    return {
        "manifest_sha256": digest(manifest_raw),
        "payload_sha256": digest(payload),
        "serialized_bytes": len(manifest_raw) + len(payload),
        "state_tensor_bytes": total,
    }


def audit_python_replay(directory, receipt, record, x, dt, policy, result):
    task = json.loads((directory / "task.json").read_text())
    identity = canonical(
        {
            "temperature": policy["temperature"],
            "fixed_threshold": policy["fixed"]["threshold"],
            "direct": policy["direct"]["parameters"],
            "solver_grid": np.linspace(-12, 12, 257).tolist(),
            "transition": "known Gaussian observation log-likelihood increments",
        }
    )
    check(
        sha(directory / "task.json") == receipt["task_sha256"],
        "Python task snapshot SHA",
    )
    expected = {
        "episode_id": record["episode_id"],
        "cursor": 1,
        "model_sha256": result["actor_model_sha256"],
        "mode": record["mode"],
        "input_sha256": digest(x.tobytes() + dt.tobytes()),
        "temperature": policy["temperature"],
        "policy_sha256": identity,
        "snr": float(x[0, 1]),
        "cost": float(x[0, 2]),
        "horizon": len(x),
    }
    check(
        {key: task[key] for key in expected} == expected,
        "complete Python task/policy binding",
    )
    state = audit_stream_snapshot(
        (directory / "neural/manifest.json").read_bytes(),
        (directory / "neural/state.npz").read_bytes(),
        result["actor_model_sha256"],
        1,
    )
    check(
        task["neural_manifest_sha256"] == state["manifest_sha256"]
        and task["neural_payload_sha256"] == state["payload_sha256"],
        "task-bound neural files",
    )
    return state
