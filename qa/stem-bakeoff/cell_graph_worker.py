"""Bounded cold inference worker: stdin request, stdout receipt; no network or task labels.

Exact readout arithmetic is frozen from the original NumPy Cell implementation.
This script never opens a model checkpoint file or creates a subprocess. Its wall clock
starts after importing time; only the external owner observes full cold dispatch.
"""

import time

_ENTRY_WALL = time.perf_counter_ns()
_ENTRY_CPU = time.process_time_ns()

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import resource
import sys

# Fixed before importing NumPy in the executable, not when imported for helpers.
if __name__ == "__main__":
    for _key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[_key] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))

import numpy as np

_IMPORT_WALL = time.perf_counter_ns() - _ENTRY_WALL
_IMPORT_CPU = time.process_time_ns() - _ENTRY_CPU
MAX_INPUT = 1_048_576
MAX_OUTPUT = 196_608
HEAD_IDS = tuple(f"seed{seed}-{mode}" for seed in (7, 17, 29) for mode in ("linear", "gated"))
SCHEMA = "hepta.fixed-cell-graph.worker.v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    def invalid(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)


def tensor(value):
    array = np.ascontiguousarray(value, dtype="<f8")
    if not np.isfinite(array).all():
        raise ValueError("finite tensor required")
    data = array.tobytes(order="C")
    return {"shape": list(array.shape), "dtype": "<f8", "bytes": len(data),
            "sha256": sha(data), "base64": base64.b64encode(data).decode("ascii")}


def array(item, shape):
    size = int(np.prod(shape)) * 8
    if (set(item) != {"shape", "dtype", "bytes", "sha256", "base64"}
            or item["shape"] != list(shape) or item["dtype"] != "<f8"
            or type(item["bytes"]) is not int or item["bytes"] != size
            or type(item["base64"]) is not str or len(item["base64"]) != 4 * ((size + 2) // 3)):
        raise ValueError("exact bounded portable tensor required")
    data = base64.b64decode(item["base64"], validate=True)
    if len(data) != size or sha(data) != item["sha256"]:
        raise ValueError("portable tensor bytes differ")
    result = np.frombuffer(data, dtype="<f8").reshape(shape).copy()
    if not np.isfinite(result).all():
        raise ValueError("nonfinite tensor")
    return result


def load_head(head):
    mode = head["mode"]
    if mode not in ("linear", "gated") or set(head["params"]) != ({"W", "b"} if mode == "linear" else {"W", "b", "a", "g"}):
        raise ValueError("exact linear/gated head required")
    values = {name: array(item, (8, 4) if name == "W" else (4,) if name == "b" else (8,))
              for name, item in head["params"].items()}
    digest = hashlib.sha256(canonical([8, 4, mode, 8]))
    for name, value in sorted(values.items()):
        digest.update(canonical([name, list(value.shape), value.dtype.str]))
        digest.update(value.tobytes(order="C"))
    if digest.hexdigest() != head["tensor_sha256"]:
        raise ValueError("original head tensor identity differs")
    return values


def infer_loaded(features, mode, values):
    """Original normalize_features, gated forward, and probabilities arithmetic."""
    norm = np.sqrt(np.square(features).sum(axis=1, keepdims=True))
    if not np.isfinite(norm).all():
        raise ValueError("normalization magnitude exceeds range")
    x = features / np.maximum(norm, 1e-12) * np.sqrt(features.shape[1])
    u = x
    if mode == "gated":
        gate = 1 / (1 + np.exp(-np.clip(x * values["a"] + values["g"], -40, 40)))
        u = x * gate
    logits = u @ values["W"] + values["b"]
    if not np.isfinite(logits).all():
        raise ValueError("nonfinite prediction")
    logits = np.asarray(logits, dtype=np.float64) / 1.0
    logits -= logits.max(axis=1, keepdims=True)
    weights = np.exp(logits)
    return weights / weights.sum(axis=1, keepdims=True)


def infer(features, head):
    return infer_loaded(features, head["mode"], load_head(head))


def inventory():
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        np.show_config()
    config = capture.getvalue()
    if len(config.encode()) > 16384:
        raise ValueError("NumPy configuration exceeds receipt bound")
    # platform.platform() may spawn uname -p; use the uname syscall so this
    # bounded worker's full process tree really contains no child process.
    uname = os.uname()
    result = {"python": platform.python_version(), "python_executable": sys.executable,
        "numpy": np.__version__, "system": {key: getattr(uname, key) for key in ("sysname", "release", "version", "machine")},
        "byteorder": sys.byteorder, "hostname_sha256": sha(uname.nodename.encode()),
        "cpu_count": os.cpu_count(), "numpy_config": config,
        "thread_environment": {key: os.environ[key] for key in
            ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "CUDA_VISIBLE_DEVICES")},
        "worker_source_sha256": sha(Path(__file__).read_bytes()),
        "model_checkpoint_or_task_labels_opened": False}
    return result


def own_cgroup_limits():
    """Read only this process's known unified-cgroup kernel metadata."""
    membership = Path("/proc/self/cgroup").read_bytes()
    if len(membership) > 8192:
        raise ValueError("oversized self cgroup membership")
    matches = [line[3:] for line in membership.decode("utf-8").splitlines() if line.startswith("0::")]
    if len(matches) != 1 or not matches[0].startswith("/") or ".." in Path(matches[0]).parts:
        raise ValueError("one unambiguous own cgroup-v2 path required")
    root = Path("/sys/fs/cgroup")
    own = root / matches[0].lstrip("/")
    if not own.resolve().is_relative_to(root.resolve()):
        raise ValueError("own cgroup path left known kernel hierarchy")
    cpu, memory = (own / "cpu.max").read_bytes(), (own / "memory.max").read_bytes()
    if len(cpu) > 128 or len(memory) > 128:
        raise ValueError("oversized self cgroup limit")
    pieces = cpu.decode("ascii").strip().split()
    if len(pieces) != 2 or not pieces[1].isdigit() or int(pieces[1]) <= 0:
        raise ValueError("invalid own cpu.max")
    quota = None if pieces[0] == "max" else int(pieces[0])
    period = int(pieces[1])
    memory_value = memory.decode("ascii").strip()
    maximum = None if memory_value == "max" else int(memory_value)
    return {"membership_sha256": sha(membership), "path_sha256": sha(matches[0].encode()),
        "cpu_max": cpu.decode("ascii").strip(), "memory_max": memory_value,
        "cpu_quota_us": quota, "cpu_period_us": period, "memory_max_bytes": maximum,
        "affinity_cpu_count": len(os.sched_getaffinity(0)),
        "scope": "own configured cgroup ceilings only; ancestors/global contention not measured"}


def execute(payload, expected_request_sha256):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    if len(payload) > MAX_INPUT or sha(payload) != expected_request_sha256:
        raise ValueError("request exceeds bound or differs from frozen bytes")
    request = strict_json(payload)
    required = {"schema", "request_id", "graph_sha256", "protocol_sha256", "environment_sha256",
                "features", "heads", "head_indices", "resource_limits", "authority"}
    indices = request.get("head_indices")
    if (set(request) != required or request["schema"] != SCHEMA or request["authority"] != "DENY_ALL"
            or type(indices) is not list or len(indices) not in (3, 6)
            or any(type(i) is not int or not 0 <= i < 6 for i in indices)
            or indices != sorted(set(indices)) or len(request["heads"]) != len(indices)
            or type(request["request_id"]) is not str or not 1 <= len(request["request_id"]) <= 100):
        raise ValueError("bounded fixed graph request required")
    env = inventory()
    if sha(canonical(env)) != request["environment_sha256"]:
        raise ValueError("worker environment differs from pre-inference freeze")
    expected_limits = {"cpu_quota_percent": 200 if len(indices) == 6 else 100,
                       "memory_max_bytes": 2_147_483_648 if len(indices) == 6 else 1_073_741_824}
    if request["resource_limits"] != expected_limits:
        raise ValueError("exact frozen per-shard local resource ceilings required")
    cgroup = own_cgroup_limits()
    if (cgroup["cpu_quota_us"] is None
            or cgroup["cpu_quota_us"] * 100 != expected_limits["cpu_quota_percent"] * cgroup["cpu_period_us"]
            or cgroup["memory_max_bytes"] != expected_limits["memory_max_bytes"]):
        raise ValueError("own cgroup ceilings differ from frozen request: " + canonical(cgroup).decode())
    features = array(request["features"], (480, 8))
    for i, head in zip(indices, request["heads"], strict=True):
        if (set(head) != {"id", "mode", "tensor_sha256", "params"}
                or head["id"] != HEAD_IDS[i] or head["mode"] != ("linear" if i % 2 == 0 else "gated")):
            raise ValueError("exact original head census/order required")
    parameters = [load_head(head) for head in request["heads"]]
    loaded_wall, loaded_cpu = time.perf_counter_ns(), time.process_time_ns()
    results = [infer_loaded(features, head["mode"], values)
               for head, values in zip(request["heads"], parameters, strict=True)]
    compute_wall, compute_cpu = time.perf_counter_ns(), time.process_time_ns()
    encoded = [tensor(result) for result in results]
    encoded_wall, encoded_cpu = time.perf_counter_ns(), time.process_time_ns()
    usage, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = children.ru_utime + children.ru_stime
    if child_cpu != 0:
        raise ValueError("unexpected child process resource usage")
    receipt = {"schema": SCHEMA, "status": "completed", "request_id": request["request_id"],
        "request_sha256": expected_request_sha256, "graph_sha256": request["graph_sha256"],
        "protocol_sha256": request["protocol_sha256"], "environment_sha256": request["environment_sha256"],
        "head_indices": indices, "head_ids": [HEAD_IDS[i] for i in indices],
        "input_feature_sha256": request["features"]["sha256"],
        "input_head_tensor_sha256": [head["tensor_sha256"] for head in request["heads"]],
        "own_cgroup_limits": cgroup, "own_cgroup_receipt_sha256": sha(canonical(cgroup)),
        "local_resource_ceiling_match": True,
        "probabilities": encoded, "worker_pid": os.getpid(), "request_bytes": len(payload),
        "phase_ns": {"python_entry_import_wall": _IMPORT_WALL, "python_entry_import_cpu": _IMPORT_CPU,
            "request_parse_environment_feature_and_parameter_load_wall": loaded_wall - began,
            "request_parse_environment_feature_and_parameter_load_cpu": loaded_cpu - cpu,
            "inference_wall": compute_wall - loaded_wall,
            "inference_cpu": compute_cpu - loaded_cpu,
            "tensor_encode_wall": encoded_wall - compute_wall, "tensor_encode_cpu": encoded_cpu - compute_cpu},
        "worker_wall_ns_before_receipt_json": time.perf_counter_ns() - _ENTRY_WALL,
        "worker_cpu_ns_before_receipt_json": time.process_time_ns() - _ENTRY_CPU,
        "process_peak_rss_bytes": int(usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024),
        "child_process_cpu_ns": 0, "process_tree_scope": "this single fresh worker plus its numerical threads; no children",
        "not_in_worker_cost": ["interpreter startup before Python entry", "broker dispatch/transfer/polling",
            "receipt JSON serialization/stdout transport after this measurement", "service daemon resource usage"],
        "authority": "DENY_ALL", "model_checkpoint_or_task_labels_opened": False}
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--expected-request-sha256")
    args = parser.parse_args()
    if args.inventory:
        if args.expected_request_sha256 is not None:
            raise ValueError("inventory has no inference request")
        output = canonical(inventory()) + b"\n"
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
    else:
        if args.expected_request_sha256 is None:
            raise ValueError("explicit request identity required")
        read_wall, read_cpu = time.perf_counter_ns(), time.process_time_ns()
        payload = sys.stdin.buffer.read(MAX_INPUT + 1)
        read_wall, read_cpu = time.perf_counter_ns() - read_wall, time.process_time_ns() - read_cpu
        receipt = execute(payload, args.expected_request_sha256)
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        output = canonical(receipt) + b"\n"
        json_wall, json_cpu = time.perf_counter_ns() - began, time.process_time_ns() - cpu
        if len(output) + 4096 > MAX_OUTPUT:
            raise ValueError("bounded output exceeded")
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        write_wall, write_cpu = time.perf_counter_ns() - began, time.process_time_ns() - cpu
        final = {"schema": "hepta.fixed-cell-graph.worker-final.v1", "status": "completed",
            "request_sha256": args.expected_request_sha256, "result_line_sha256": sha(output),
            "result_line_bytes": len(output), "stdin_read_wall_ns": read_wall, "stdin_read_cpu_ns": read_cpu,
            "result_json_encode_wall_ns": json_wall, "result_json_encode_cpu_ns": json_cpu,
            "result_stdout_write_wall_ns": write_wall, "result_stdout_write_cpu_ns": write_cpu,
            "worker_wall_ns_before_final_trailer": time.perf_counter_ns() - _ENTRY_WALL,
            "worker_cpu_ns_before_final_trailer": time.process_time_ns() - _ENTRY_CPU,
            "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                (1 if sys.platform == "darwin" else 1024)),
            "excluded": "interpreter pre-entry, this small trailer write, external transport/service resources"}
        sys.stdout.buffer.write(canonical(final) + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
