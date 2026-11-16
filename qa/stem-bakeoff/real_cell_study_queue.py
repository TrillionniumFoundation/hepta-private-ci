"""Persist real training inputs, optimize new heads, and recover their results.

One worker trains a head at a time. SQLite publishes artifact references only
after new optimization and artifact verification. Input files remain available
to a replacement worker; no Encoder or held-out labels enter this stage.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from cell_scale_probe import measure_queue
from cell_training_queue import TrainingQueue


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_binding(payload, identity):
    return hashlib.sha256(canonical({"feature_identity": identity,
        "sources": list(zip(payload["training_source_ids"], payload["source_digests"], strict=True)),
        "input_archive_sha256": payload["input_sha256"]})).hexdigest()


def _inputs(root, job):
    payload = job["payload"]
    relative = Path(payload["input_path"])
    if (relative.is_absolute() or ".." in relative.parts
            or payload["feature_identity"] != job["feature_identity"]
            or _source_binding(payload, job["feature_identity"]) != job["source_digest"]):
        raise ValueError("queued input source or feature identity differs")
    path = root / relative
    if path.is_symlink() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("unbounded or linked queued input")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != payload["input_sha256"]:
        raise ValueError("queued input archive changed")
    with zipfile.ZipFile(io.BytesIO(raw)) as packed:
        if sum(entry.file_size for entry in packed.infolist()) > 4 * 1024**2:
            raise ValueError("queued input decompression exceeds quota")
    with np.load(io.BytesIO(raw), allow_pickle=False) as arrays:
        if set(arrays.files) != {"features", "labels"}:
            raise ValueError("unexpected queued training fields")
        x, y = arrays["features"], arrays["labels"]
    if (x.shape != (32, payload["width"]) or x.dtype != np.float32
            or y.shape != (32,) or y.dtype != np.int64 or not np.isfinite(x).all()
            or np.any(y < 0) or np.any(y > 1) or np.bincount(y, minlength=2).tolist() != [16, 16]):
        raise ValueError("queued inputs must retain the actual balanced n32 cohort")
    return x, y, path


def train_persisted_job(root, job):
    """Replacement workers may call this with a newly claimed durable job."""
    root = Path(root)
    x, y, input_path = _inputs(root, job)
    payload = job["payload"]
    head = NumpyCellHead(payload["width"], 2, "gated", rank=8, seed=7)
    training = head.train(x, y, steps=payload["steps"])
    relative = Path("artifacts") / (job["job_id"] + f"-attempt-{job['attempt']}")
    artifact = root / relative
    head.save(artifact, job["feature_identity"])
    restored = NumpyCellHead.load(artifact, job["feature_identity"])
    if restored.digest() != head.digest() or _sha(input_path) != payload["input_sha256"]:
        raise ValueError("training input or artifact changed before publication")
    return {"artifact": str(relative), "manifest_sha256": _sha(artifact / "manifest.json"),
        "tensor_sha256": head.digest(), "feature_identity": job["feature_identity"],
        "source_digest": job["source_digest"], "generation": job["generation"],
        "training": training, "training_feature_tensor_bytes": x.nbytes,
        "probe_logits": head.predict_logits(x[:1]).tolist(), "encoder_forward_calls": 0}


def verify_queue(root, identity):
    started = time.perf_counter_ns()
    verified, max_error, training_reports = [], 0.0, []
    with TrainingQueue(Path(root) / "training.sqlite", max_jobs=64) as queue:
        cells = [row[0] for row in queue.db.execute("SELECT cell_id FROM frontier ORDER BY cell_id")]
        if not 1 <= len(cells) <= 64:
            raise ValueError("unexpected recovered Cell population")
        for cell in cells:
            publication = queue.read_current(cell)
            if publication is None or publication["feature_identity"] != identity:
                raise ValueError("recovered publication is absent or stale")
            stored = queue.db.execute("SELECT * FROM jobs WHERE job_id=?", (publication["job_id"],)).fetchone()
            job = dict(stored)
            job["payload"] = json.loads(job["payload"])
            x, _, _ = _inputs(Path(root), job)
            result = publication["result"]
            if any(result[key] != publication[key] for key in ("feature_identity", "source_digest", "generation")):
                raise ValueError("artifact result differs from its atomic publication header")
            relative = Path(result["artifact"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("artifact must remain inside its owned queue directory")
            artifact = Path(root) / relative
            if _sha(artifact / "manifest.json") != result["manifest_sha256"]:
                raise ValueError("published artifact manifest changed")
            head = NumpyCellHead.load(artifact, identity)
            actual = head.predict_logits(x[:1])
            expected = np.asarray(result["probe_logits"])
            if (head.digest() != result["tensor_sha256"] or actual.shape != expected.shape
                    or not np.allclose(actual, expected, atol=1e-12, rtol=1e-12)):
                raise ValueError("freshly loaded published head differs from its training output")
            max_error = max(max_error, float(np.max(np.abs(actual - expected))))
            verified.append(cell)
            training_reports.append(result["training"])
    return {"verified_publications": len(verified), "verified_cell_ids": verified,
            "scalar_max_abs_error": max_error, "validation_wall_ns": time.perf_counter_ns() - started,
            "process_cpu_ns_so_far": time.process_time_ns(), "training_reports": training_reports}


def run_queue_stage(root, tasks, training_ids, rows, features, source_digests, identity, *, steps=200):
    root, tasks = Path(root), tuple(tasks)
    if (not 1 <= len(tasks) <= 64 or len(set(tasks)) != len(tasks)
            or any(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", task) is None for task in tasks)
            or type(steps) is not int or not 1 <= steps <= 5000
            or features.dtype != np.float32 or features.ndim != 2 or len(features) != len(rows)
            or len(source_digests) != len(rows) or re.fullmatch(r"[0-9a-f]{64}", identity) is None):
        raise ValueError("bounded real queue study inputs required")
    by_id = {row["source_id"]: i for i, row in enumerate(rows)}
    prepared = []
    for task in tasks:
        ids = list(training_ids[task])
        if len(ids) != 32 or len(set(ids)) != 32:
            raise ValueError("each queued task must use its actual 32 distinct training sources")
        indices = [by_id[source] for source in ids]
        labels = [rows[i]["labels"][task] for i in indices]
        if (any(rows[i]["split"] != "train" for i in indices)
                or any(type(label) is not int or label not in (0, 1) for label in labels)
                or labels.count(0) != 16 or labels.count(1) != 16):
            raise ValueError("held-out, unbalanced or invalid labels entered queued training")
        prepared.append((task, ids, indices, np.array(labels, dtype=np.int64)))
    root.mkdir(parents=True, exist_ok=False)
    (root / "inputs").mkdir()
    (root / "artifacts").mkdir()
    submissions, input_tensor_bytes = [], 0
    deadline = time.time_ns() + 3_600_000_000_000
    for task, ids, indices, labels in prepared:
        relative = Path("inputs") / (task + ".npz")
        x = np.ascontiguousarray(features[indices])
        with (root / relative).open("xb") as stream:
            np.savez_compressed(stream, features=x, labels=labels)
            stream.flush()
            os.fsync(stream.fileno())
        payload = {"input_path": str(relative), "input_sha256": _sha(root / relative),
            "feature_identity": identity, "training_source_ids": ids,
            "source_digests": [source_digests[i] for i in indices], "width": features.shape[1], "steps": steps}
        submissions.append({"cell_id": task, "generation": 1, "source_digest": _source_binding(payload, identity),
                            "feature_identity": identity, "payload": payload, "deadline_ns": deadline})
        input_tensor_bytes += x.nbytes + labels.nbytes
    receipt = measure_queue(root / "training.sqlite", submissions,
                            lambda job: train_persisted_job(root, job), lease_ns=600_000_000_000)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--verify", str(root),
                            "--identity", identity], check=True, capture_output=True, text=True, timeout=120,
                           env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    recovered = json.loads(child.stdout)
    if recovered["verified_cell_ids"] != sorted(tasks):
        raise ValueError("fresh process recovered a different task population")
    receipt["recovery"] = {"fresh_connection": receipt["recovery"],
        "fresh_process": True, "parent_wall_ns": time.perf_counter_ns() - began,
        "parent_cpu_ns": time.process_time_ns() - cpu,
        "child_cpu_ns": recovered["process_cpu_ns_so_far"], "validation": recovered,
        "power_loss_tested": False, "filesystem_isolation_claimed": False}
    receipt.update(task_count=len(tasks), training_rows_per_task=32, optimizer_steps_per_task=steps,
        input_tensor_bytes=input_tensor_bytes, encoder_forward_calls=0,
        stored_input_bytes=sum(path.stat().st_size for path in (root / "inputs").glob("*.npz")),
        stored_artifact_bytes=sum(path.stat().st_size for path in (root / "artifacts").rglob("*") if path.is_file()),
        concurrency=1, training_inputs="persisted source-bound n32 features and labels only")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", required=True)
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()
    print(json.dumps(verify_queue(Path(args.verify), args.identity), sort_keys=True))
