"""Persist complete n32 training snapshots for bounded, restartable workers.

The existing SQLite queue publishes references after verification. A lost worker
restarts from persisted initial parameters: intermediate Adam moments are not
checkpointed. New parameter digests invalidate all prior probability calibrators.
This is a same-host research adapter, with no production or power-loss claim.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
import zipfile

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from cell_runtime_bundle import check_npz
from cell_training_queue import TrainingQueue


MODES = ("linear", "gated", "residual")
SCHEMA = "hepta.action-training-job.v1"
PAYLOAD_KEYS = {"schema", "bundle_manifest_sha256", "feature_identity", "generation",
    "task_id", "cell_id", "width", "classes", "mode", "rank", "seed", "steps",
    "learning_rate", "l2", "optimizer", "inputs", "sources", "initial_head",
    "initial_manifest_sha256", "initial_tensor_sha256"}


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("full immutable snapshot SHA256 required")
    return value


def owned_path(root, name):
    root, relative = Path(root).absolute(), Path(name)
    if (type(name) is not str or not name or not relative.parts or relative.is_absolute()
            or any(part in (".", "..") for part in relative.parts)
            or relative.as_posix() != name or "\\" in name or ":" in name):
        raise ValueError("ordinary relative path inside owned queue root required")
    result = root / relative
    if any(p.is_symlink() for p in (result, *result.parents)):
        raise ValueError("queue paths cannot traverse symbolic links")
    return result


def _write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read(root, record, limit):
    if (type(record) is not dict or set(record) != {"path", "sha256"}
            or type(record["path"]) is not str):
        raise ValueError("exact persisted input reference required")
    path = owned_path(root, record["path"])
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("missing or oversized persisted input")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _digest(record["sha256"]):
        raise ValueError("persisted input bytes changed")
    return raw, path


def _arrays(raw):
    expected = {"features.npy": ((32, 770), np.dtype("float32")),
                "labels.npy": ((32,), np.dtype("int64"))}
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if sorted(e.filename for e in entries) != sorted(expected):
            raise ValueError("exact queued feature/label arrays required")
        for entry in entries:
            if entry.file_size > 1024**2:
                raise ValueError("expanded queued array exceeds byte bound")
            data = archive.read(entry)
            stream = io.BytesIO(data)
            version = np.lib.format.read_magic(stream)
            if version != (1, 0):
                raise ValueError("bounded NumPy v1 array header required")
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
            if (shape, dtype) != expected[entry.filename] or fortran:
                raise ValueError("queued array shape, layout or dtype differs")
            if len(data) - stream.tell() != int(np.prod(shape))*dtype.itemsize:
                raise ValueError("queued array payload length differs")
            result[entry.filename] = np.load(io.BytesIO(data), allow_pickle=False)
    x, y = result["features.npy"], result["labels.npy"]
    if (not np.isfinite(x).all() or np.any((y < 0) | (y > 1))
            or np.bincount(y, minlength=2).tolist() != [16, 16]):
        raise ValueError("finite balanced binary n32 inputs required")
    return x, y


def _validate_payload(job):
    payload = job["payload"]
    if type(payload) is not dict or set(payload) != PAYLOAD_KEYS:
        raise ValueError("exact complete training snapshot payload required")
    if (payload["schema"] != SCHEMA or payload["mode"] not in MODES
            or any(type(payload[key]) is not int for key in
                   ("generation", "width", "classes", "rank", "seed", "steps"))
            or (payload["generation"], payload["width"], payload["classes"], payload["rank"], payload["steps"])
               != (1, 770, 2, 4, 20)
            or payload["seed"] != 1_000_000 + MODES.index(payload["mode"])
            or payload["learning_rate"] != .02 or payload["l2"] != .001
            or payload["optimizer"] != "adam-reset-from-persisted-initial-head"
            or payload["cell_id"] != "runtime-training-" + payload["mode"]
            or type(payload["task_id"]) is not str or not 1 <= len(payload["task_id"].encode()) <= 256):
        raise ValueError("training configuration differs from frozen runtime study")
    for key in ("bundle_manifest_sha256", "feature_identity", "initial_manifest_sha256", "initial_tensor_sha256"):
        _digest(payload[key])
    if (any(payload[k] != job[k] for k in ("cell_id", "generation", "feature_identity"))
            or hashlib.sha256(canonical(payload)).hexdigest() != job["source_digest"]
            or type(job["attempt"]) is not int or not 1 <= job["attempt"] <= 65536):
        raise ValueError("queue generation, feature or full snapshot binding differs")
    _digest(job["job_id"])
    return payload


def _load_head(root, relative, mode, identity):
    directory = owned_path(root, relative)
    weights = owned_path(root, relative + "/weights.npz")
    owned_path(root, relative + "/manifest.json")
    if not weights.is_file() or weights.stat().st_size > 2*1024**2:
        raise ValueError("bounded private parameter archive required")
    shapes = {"W": (770, 2), "b": (2,)}
    if mode != "linear":
        shapes.update(a=(770,), g=(770,))
    if mode == "residual":
        shapes.update(V=(770, 4), U=(4, 770))
    check_npz(weights, {name: (shape, np.float64) for name, shape in shapes.items()})
    head = NumpyCellHead.load(directory, identity)
    if (head.width, head.classes, head.mode, head.rank) != (770, 2, mode, 4):
        raise ValueError("fixed 770D private parameter architecture differs")
    return head


def load_job_inputs(root, job):
    payload = _validate_payload(job)
    raw, archive = _read(root, payload["inputs"], 1024**2)
    source_raw, source_path = _read(root, payload["sources"], 8*1024**2)
    rows = json.loads(source_raw)
    if (type(rows) is not list or len(rows) != 32
            or any(type(row) is not dict or any(type(row.get(k)) is not str
                   or not 1 <= len(row[k].encode()) <= 512 for k in ("source_id", "group_id")) for row in rows)
            or len({row["source_id"] for row in rows}) != 32
            or len({row["group_id"] for row in rows}) != 32):
        raise ValueError("32 distinct source and bug group bindings required")
    x, y = _arrays(raw)
    manifest = owned_path(root, payload["initial_head"] + "/manifest.json")
    weights = owned_path(root, payload["initial_head"] + "/weights.npz")
    if sha_file(manifest) != payload["initial_manifest_sha256"]:
        raise ValueError("initial head manifest changed")
    head = _load_head(root, payload["initial_head"], payload["mode"], payload["feature_identity"])
    if ((head.width, head.classes, head.mode, head.rank) != (770, 2, payload["mode"], 4)
            or head.digest() != payload["initial_tensor_sha256"] or head.report):
        raise ValueError("initial parameters are not the sealed untrained snapshot")
    pins = {str(path): sha_file(path) for path in (archive, source_path, manifest, weights)}
    return payload, x, y, head, pins


def persist_training_jobs(root, meta, features, labels, rows, *, bundle_manifest_sha256, deadline_ns):
    """Save one shared labelled bank and three independent initial Head snapshots."""
    identity = _digest(meta["feature_identity"])
    _digest(bundle_manifest_sha256)
    if (meta["generation"] != 1 or type(meta["generation"]) is not int
            or type(deadline_ns) is not int or deadline_ns <= 0
            or np.shape(features) != (32, 770) or np.asarray(features).dtype != np.float32
            or not np.isfinite(features).all() or np.shape(labels) != (32,)
            or np.asarray(labels).dtype != np.int64 or np.any((labels < 0) | (labels > 1))
            or np.bincount(labels, minlength=2).tolist() != [16, 16]):
        raise ValueError("exact feature-bound n32 runtime training bank required")
    root = Path(root).absolute()
    owned_path(root, "inputs.npz")
    root.mkdir(parents=True, exist_ok=False)
    (root / "initial").mkdir()
    (root / "artifacts").mkdir()
    with (root / "inputs.npz").open("xb") as stream:
        np.savez_compressed(stream, features=np.ascontiguousarray(features), labels=np.ascontiguousarray(labels))
        stream.flush()
        os.fsync(stream.fileno())
    _write(root / "sources.json", rows)
    submissions = []
    for index, mode in enumerate(MODES):
        head = NumpyCellHead(770, 2, mode, rank=4, seed=1_000_000+index)
        relative = "initial/" + mode
        head.save(root / relative, identity)
        for name in ("manifest.json", "weights.npz"):
            with (root / relative / name).open("rb") as stream:
                os.fsync(stream.fileno())
        payload = {"schema": SCHEMA, "bundle_manifest_sha256": bundle_manifest_sha256,
            "feature_identity": identity, "generation": 1, "task_id": meta["task_id"],
            "cell_id": "runtime-training-"+mode, "width": 770, "classes": 2,
            "mode": mode, "rank": 4, "seed": 1_000_000+index, "steps": 20,
            "learning_rate": .02, "l2": .001, "optimizer": "adam-reset-from-persisted-initial-head",
            "inputs": {"path": "inputs.npz", "sha256": sha_file(root / "inputs.npz")},
            "sources": {"path": "sources.json", "sha256": sha_file(root / "sources.json")},
            "initial_head": relative, "initial_manifest_sha256": sha_file(root / relative / "manifest.json"),
            "initial_tensor_sha256": head.digest()}
        submission = {"cell_id": payload["cell_id"], "generation": 1,
            "source_digest": hashlib.sha256(canonical(payload)).hexdigest(),
            "feature_identity": identity, "payload": payload, "deadline_ns": deadline_ns}
        load_job_inputs(root, {**submission, "job_id": "0"*64, "attempt": 1})
        submissions.append(submission)
    plan = {"schema": "hepta.action-training-queue-plan.v1", "submissions": submissions,
        "logical_tasks": 1, "distinct_training_configurations": 3, "train_rows": 32,
        "training_groups": 32, "concurrency": 1, "optimizer_steps_per_job": 20,
        "resume_semantics": "restart from persisted initial weights and inputs; no intermediate Adam checkpoint",
        "calibration_after_training": "unavailable; previous predictor-bound calibrators invalidated",
        "authority": "DENY_ALL", "quality_qualified": False, "encoder_forward_calls": 0}
    _write(root / "plan.json", plan)
    return {"plan": plan, "submissions": submissions}


def prepare_training_jobs(bundle_root, output_root, *, expected_manifest_sha256, deadline_ns):
    from cell_runtime_bundle import load_training_inputs
    meta, x, y, rows = load_training_inputs(bundle_root, expected_manifest_sha256=expected_manifest_sha256)
    return persist_training_jobs(output_root, meta, x, y, rows,
        bundle_manifest_sha256=expected_manifest_sha256, deadline_ns=deadline_ns)


def train_persisted_job(root, job):
    """Verify, train from the initial snapshot, and return an unpublished result."""
    payload, x, y, head, pins = load_job_inputs(root, job)
    report = head.train(x, y, steps=20, learning_rate=.02, l2=.001)
    relative = "artifacts/" + job["job_id"] + "-attempt-" + str(job["attempt"])
    directory = owned_path(root, relative)
    head.save(directory, payload["feature_identity"])
    for name in ("manifest.json", "weights.npz"):
        with (directory / name).open("rb") as stream:
            os.fsync(stream.fileno())
    restored = _load_head(root, relative, payload["mode"], payload["feature_identity"])
    expected, actual = head.predict_logits(x[:4]), restored.predict_logits(x[:4])
    if (restored.digest() != head.digest() or not np.array_equal(actual, expected)
            or any(sha_file(path) != digest for path, digest in pins.items())):
        raise ValueError("training snapshot or saved private parameters changed")
    return {"artifact": relative, "manifest_sha256": sha_file(directory / "manifest.json"),
        "tensor_sha256": head.digest(), "initial_tensor_sha256": payload["initial_tensor_sha256"],
        "feature_identity": payload["feature_identity"], "generation": payload["generation"],
        "source_digest": job["source_digest"], "task_id": payload["task_id"], "training": report,
        "probe_logits": expected.tolist(), "probe_training_row_indices": [0, 1, 2, 3],
        "calibration_status": "unavailable_after_parameter_update", "calibration": None,
        "encoder_forward_calls": 0, "quality_qualified": False, "authority": "DENY_ALL"}


def verify_queue_publications(root):
    """Reopen durable publications and compare persisted tensors and fixed logits."""
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    verified, parameters = [], 0
    with TrainingQueue(owned_path(root, "training.sqlite"), max_jobs=3) as queue:
        expected = sorted("runtime-training-" + mode for mode in MODES)
        cells = [r[0] for r in queue.db.execute("SELECT cell_id FROM frontier ORDER BY cell_id")]
        if cells != expected:
            raise ValueError("recovered runtime training population differs")
        for cell in cells:
            publication = queue.read_current(cell)
            if publication is None:
                raise ValueError("current trained publication missing")
            stored = queue.db.execute("SELECT * FROM jobs WHERE job_id=?", (publication["job_id"],)).fetchone()
            job = dict(stored)
            job["payload"], job["attempt"] = json.loads(job["payload"]), job["attempts"]
            payload, x, _, _, _ = load_job_inputs(root, job)
            result = publication["result"]
            if (any(result[k] != publication[k] for k in ("generation", "feature_identity", "source_digest"))
                    or result["task_id"] != payload["task_id"]
                    or result["initial_tensor_sha256"] != payload["initial_tensor_sha256"]
                    or result["authority"] != "DENY_ALL" or result["quality_qualified"] is not False
                    or result["encoder_forward_calls"] != 0
                    or result["probe_training_row_indices"] != [0, 1, 2, 3]
                    or result["calibration"] is not None
                    or result["calibration_status"] != "unavailable_after_parameter_update"):
                raise ValueError("trained result bindings or calibration status differ")
            manifest = owned_path(root, result["artifact"] + "/manifest.json")
            owned_path(root, result["artifact"] + "/weights.npz")
            if sha_file(manifest) != result["manifest_sha256"]:
                raise ValueError("published parameter manifest changed")
            head = _load_head(root, result["artifact"], payload["mode"], payload["feature_identity"])
            actual = head.predict_logits(x[:4])
            if (head.digest() != result["tensor_sha256"] or head.report != result["training"]
                    or not np.array_equal(actual, np.asarray(result["probe_logits"]))):
                raise ValueError("fresh-process trained tensors or fixed logits differ")
            verified.append({"cell_id": cell, "tensor_sha256": head.digest(), "mode": head.mode,
                             "optimizer_steps": head.report["optimizer_steps"], "logits_bitwise_equal": True})
            parameters += head.tensor_bytes
    return {"schema": "hepta.action-training-queue-verification.v1", "verified_publications": verified,
        "raw_trained_parameter_bytes": parameters, "wall_ns": time.perf_counter_ns()-began,
        "cpu_ns": time.process_time_ns()-cpu, "optimizer_updates": 0,
        "encoder_forward_calls": 0, "intermediate_optimizer_resume_tested": False,
        "power_loss_tested": False, "quality_qualified": False, "authority": "DENY_ALL"}
