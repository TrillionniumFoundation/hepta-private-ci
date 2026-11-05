#!/usr/bin/env python3
"""Inspect the live registered Laya adapter and execute isolated CPU head probes.

The actual encoder, price task, broker, trainer and production model are not run.
Only aggregate identities/statistics are exported; all input activations are
deterministic synthetic probes. The selected adapter is read, never modified.
"""

import argparse
import ast
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import stat
import struct
import subprocess
import time


EXPECTED = {
    "candidate_id": "8fe51f354c8a75001b0948c3588cab7d62dcb54c90f932f32e7bf9eb1505bf5a",
    "adapter_sha256": "94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0",
    "base_id": "24a87544b623b73d2a94e8e7110c7e640e1b1d88f15f234540ef252a4ed29af7",
    "base_model_sha256": "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204",
    "parent_adapter_sha256": "52adec4b889f2898d554877e3534f3121503f88850920868e9adc5b6547a7a73",
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def unique_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "DUPLICATE_JSON_KEY")
            out[key] = value
        return out

    def constant(_):
        raise ValueError("NONFINITE_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def stamp(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read(path, cap):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= cap, "SOURCE_BOUND")
        data = bytearray()
        while chunk := os.read(fd, min(1024 * 1024, cap + 1 - len(data))):
            data.extend(chunk)
            require(len(data) <= cap, "SOURCE_GREW")
        require(stamp(before) == stamp(os.fstat(fd)) == stamp(path.lstat()), "SOURCE_CHANGED")
        return bytes(data)
    finally:
        os.close(fd)


def bound_live():
    r = subprocess.run(["systemctl", "--user", "show", "heptatrader-laya-trainer.service",
                        "--property=MainPID", "--value"], check=True, capture_output=True,
                       text=True, timeout=6)
    pid = int(r.stdout)
    require(pid > 0, "TRAINER_MISSING")
    proc = Path("/proc") / str(pid)
    args = read(proc / "cmdline", 16384).split(b"\0")
    require(args.count(b"--config") == 1, "LIVE_CONFIG_AMBIGUOUS")
    guardian_path = Path(os.fsdecode(args[args.index(b"--config") + 1]))
    guardian_raw = read(guardian_path, 65536)
    guardian = unique_json(guardian_raw)
    config_raw = read(Path(guardian["original_config"]), 262144)
    require(digest(config_raw) == guardian["original_config_sha256"], "CONFIG_BINDING")
    config = unique_json(config_raw)
    state_raw = read(Path(config["control_directory"]) / "status.json", 262144)
    state = unique_json(state_raw)
    require(state["last_candidate_id"] == EXPECTED["candidate_id"], "CANDIDATE_CHANGED")
    registration = state["latest_candidate_registration"]
    require(registration["candidate_id"] == EXPECTED["candidate_id"], "REGISTRATION_BINDING")
    job_raw = read(Path(config["control_directory"]) / "jobs" /
                   (registration["job_id"] + ".json"), 524288)
    job = unique_json(job_raw)
    start = (proc / "stat").read_text().rpartition(")")[2].split()[19]
    return config, job, {
        "guardian_sha256": digest(guardian_raw), "config_sha256": digest(config_raw),
        "job_sha256": digest(job_raw), "candidate_id": EXPECTED["candidate_id"],
        "process_identity_sha256": digest(str(pid).encode() + b":" + start.encode() + b":" + b"\0".join(args)),
    }


def parse_safetensors(raw, np):
    require(len(raw) >= 8, "SAFETENSORS_HEADER_MISSING")
    size = struct.unpack("<Q", raw[:8])[0]
    require(size <= 4 * 1024 * 1024 and 8 + size <= len(raw), "SAFETENSORS_HEADER_BOUND")
    header = unique_json(raw[8:8 + size]); data = raw[8 + size:]
    arrays, intervals = {}, []
    for name, row in header.items():
        if name == "__metadata__":
            continue
        require(row["dtype"] == "F32", "ADAPTER_DTYPE")
        shape = row["shape"]
        require(all(type(x) is int and x >= 0 for x in shape), "ADAPTER_SHAPE")
        lo, hi = row["data_offsets"]
        require(type(lo) is int and type(hi) is int and 0 <= lo <= hi <= len(data), "ADAPTER_OFFSET")
        require(hi - lo == 4 * math.prod(shape), "ADAPTER_SIZE")
        array = np.frombuffer(data[lo:hi], dtype="<f4").reshape(shape).copy()
        require(np.isfinite(array).all(), "ADAPTER_NONFINITE")
        arrays[name] = array; intervals.append((lo, hi))
    cursor = 0
    for lo, hi in sorted(intervals):
        require(lo == cursor, "ADAPTER_LAYOUT"); cursor = hi
    require(cursor == len(data), "ADAPTER_TRAILING_BYTES")
    return arrays


def base_weights(path, manifest, np):
    """Stream the full checkpoint hash; then read the six small head tensors."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size == manifest["size"], "BASE_SIZE")
        h = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            h.update(chunk)
        require(h.hexdigest() == manifest["sha256"] == EXPECTED["base_model_sha256"], "BASE_FULL_HASH")
        os.lseek(fd, 0, os.SEEK_SET)
        size = struct.unpack("<Q", os.read(fd, 8))[0]
        require(size < 4 * 1024 * 1024, "BASE_HEADER_BOUND")
        header_raw = os.read(fd, size)
        require(len(header_raw) == size, "BASE_HEADER_SHORT")
        header = unique_json(header_raw)
        result = {}
        for name in ("scorer.1", "scorer.3", "act_head.2"):
            for kind in ("weight", "bias"):
                key = name + "." + kind; row = header[key]
                require(row["dtype"] == "F16", "BASE_DTYPE")
                lo, hi = row["data_offsets"]
                require(0 <= lo <= hi <= before.st_size - size - 8 and hi - lo <= 2 * 1024 * 1024,
                        "BASE_TENSOR_BOUND")
                require(hi - lo == 2 * math.prod(row["shape"]), "BASE_TENSOR_SIZE")
                os.lseek(fd, size + 8 + lo, os.SEEK_SET); raw = os.read(fd, hi - lo)
                require(len(raw) == hi - lo, "BASE_TENSOR_SHORT")
                result[key] = np.frombuffer(raw, dtype="<f2").reshape(row["shape"]).astype(np.float32)
                require(np.isfinite(result[key]).all(), "BASE_TENSOR_NONFINITE")
        require(stamp(before) == stamp(os.fstat(fd)) == stamp(path.lstat()), "BASE_CHANGED")
        return result, {"sha256": h.hexdigest(), "bytes": before.st_size,
                        "streamed_full_hash": True, "head_tensor_count_loaded": len(result)}
    finally:
        os.close(fd)


def run(output):
    start, cpu = time.perf_counter(), time.process_time()
    os.umask(0o077); output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "hepta.wsp.laya_cpu_head_probe.v1", "started_utc": utc(),
              "status": "STARTED", "production_mutated": False, "training_executed": False,
              "full_model_forward_executed": False, "trader_value_qualified": False,
              "private_weights_or_rows_exported": False, "gpu_initialized": False}
    try:
        config, job, binding = bound_live()
        candidate_dir, parent_dir = Path(job["output_directory"]), Path(job["parent_directory"])
        candidate_raw = read(candidate_dir / "candidate.json", 524288)
        candidate = unique_json(candidate_raw)
        require(candidate["candidate_id"] == EXPECTED["candidate_id"] ==
                digest(canonical({k: v for k, v in candidate.items() if k != "candidate_id"})), "CANDIDATE_MANIFEST")
        adapter_raw = read(candidate_dir / "adapter.safetensors", 1048576)
        parent_raw = read(parent_dir / "adapter.safetensors", 1048576)
        parent_manifest_raw = read(parent_dir / "candidate.json", 524288)
        parent_manifest = unique_json(parent_manifest_raw)
        require(digest(parent_manifest_raw) == job["parent_manifest_sha256"], "PARENT_MANIFEST")
        require(parent_manifest["candidate_id"] == digest(canonical({k: v for k, v in parent_manifest.items()
                                                                    if k != "candidate_id"})), "PARENT_CONTENT_ID")
        require(digest(adapter_raw) == candidate["adapter_sha256"] == EXPECTED["adapter_sha256"], "ADAPTER_HASH")
        require(digest(parent_raw) == parent_manifest["adapter_sha256"] == EXPECTED["parent_adapter_sha256"], "PARENT_HASH")
        base_dir = Path(config["base_directory"])
        manifest_raw = read(base_dir / "base-manifest.json", 65536); manifest = unique_json(manifest_raw)
        require(digest(canonical(manifest)) == candidate["base_id"] == EXPECTED["base_id"], "BASE_ID")
        sources = {}
        for filename, classname in (("model.py", "RowLoRALinear"), ("resident_model.py", "MaskedActionLinear")):
            path = Path(config["runtime_directory"]) / "learn/laya_cell" / filename
            raw = read(path, 131072); tree = ast.parse(raw)
            nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname]
            require(len(nodes) == 1, "CLASS_NOT_UNIQUE")
            sources[classname] = (nodes[0], path, raw)
        protocol = {"schema": "hepta.wsp.laya_cpu_head_probe.protocol.v1", "frozen_before_torch_import": utc(),
                    "expected": EXPECTED, "source_sha256": {k: digest(v[2]) for k, v in sources.items()},
                    "class_ast_sha256": {k: digest(ast.dump(v[0], include_attributes=False).encode()) for k, v in sources.items()},
                    "probes_per_layer": 16, "seed": 20261105, "atol": 0.00002, "rtol": 0.00002,
                    "matrix_atol": 0.0000001, "matrix_rtol": 0.000002,
                    "scope": "source-extracted actual adapter class on three real head tensors; deterministic synthetic activations; no encoder or task evaluation"}
        (output / "PROTOCOL_FROZEN.json").write_bytes(canonical(protocol) + b"\n")
        result["protocol_sha256"] = digest(canonical(protocol) + b"\n")
        import numpy as np
        import torch
        from torch import nn
        from torch.nn import functional as F
        torch.set_num_threads(1); torch.set_num_interop_threads(1)
        require(not torch.cuda.is_initialized(), "GPU_ALREADY_INITIALIZED")
        result["versions"] = {"torch": torch.__version__, "numpy": np.__version__, "dtype": "CPU_F32", "threads": 1}
        child, parent = parse_safetensors(adapter_raw, np), parse_safetensors(parent_raw, np)
        child_keys = {"model." + layer + "." + factor for layer in ("scorer.1", "scorer.3", "act_head.2")
                      for factor in ("A", "B")}
        parent_keys = {key for key in child_keys if ".scorer." in key}
        require(set(child) == set(candidate["tensor_mask"]) == child_keys, "TENSOR_MASK")
        require(set(parent) == parent_keys, "PARENT_TENSOR_MASK")
        require(candidate["profile"]["targets"] == {"scorer.1": {"rows": [0, 1, 2, 3], "rank": 2},
                                                     "scorer.3": {"rows": [0], "rank": 1}} and
                candidate["profile"]["action_targets"] == {"act_head.2": {"rows": [0, 1],
                                                                          "cols": list(range(64)), "rank": 1}},
                "DECLARED_PROFILE_CHANGED")
        weights, base_receipt = base_weights(base_dir / "model.safetensors", manifest["files"]["model.safetensors"], np)
        result["base_checkpoint"] = base_receipt
        classes = {"nn": nn, "torch": torch, "F": F, "ContractError": ValueError}
        for node, path, raw in sources.values():
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, "<bound_adapter_class>", "exec"), classes)
        rows = []; total_num = total_den = 0.0
        generator = np.random.Generator(np.random.PCG64(protocol["seed"]))
        for name in ("scorer.1", "scorer.3", "act_head.2"):
            w, b = weights[name + ".weight"], weights[name + ".bias"]
            base = nn.Linear(w.shape[1], w.shape[0])
            with torch.no_grad():
                base.weight.copy_(torch.from_numpy(w)); base.bias.copy_(torch.from_numpy(b))
            module = (classes["MaskedActionLinear"](base) if name == "act_head.2" else
                      classes["RowLoRALinear"](base, list(range(4 if name == "scorer.1" else 1)),
                                                 2 if name == "scorer.1" else 1, 20261105))
            x = generator.normal(size=(16, w.shape[1])).astype(np.float32)
            x[0] = 0; x[1] = 1; x[2] = -1; x[3] = np.arange(w.shape[1]) % 2 * 2 - 1
            x[4] *= np.float32(.001); x[5] *= np.float32(1000)
            if name == "act_head.2":
                x[6, :64] = 0
            initial = {"A": module.A.detach().clone(), "B": module.B.detach().clone()}
            outputs, effective, probes = {}, {}, {}
            for which, state in (("parent", parent), ("child", child)):
                prefix = "model." + name + "."
                with torch.no_grad():
                    for k in ("A", "B"):
                        if prefix + k in state:
                            value = torch.from_numpy(state[prefix + k]); require(value.shape == getattr(module, k).shape, "FACTOR_SHAPE")
                        else:
                            require(which == "parent" and name == "act_head.2", "MISSING_FACTOR")
                            value = initial[k]
                        getattr(module, k).copy_(value)
                    y = module(torch.from_numpy(x)).detach().numpy()
                    effective[which] = module.full_effective_weight().detach().numpy().copy()
                aa, bb = module.A.detach().numpy().astype(np.float64), module.B.detach().numpy().astype(np.float64)
                # Independently derive the stored F32 effective matrix. This
                # comparison allows declared floating-point kernel differences;
                # it is not an exact arithmetic norm certificate.
                aa32, bb32 = aa.astype(np.float32), bb.astype(np.float32)
                product = np.zeros((bb.shape[0], aa.shape[1]), dtype=np.float32)
                for rank_index in range(aa.shape[0]):
                    product = np.float32(product + np.float32(bb32[:, rank_index:rank_index + 1] *
                                                             aa32[rank_index:rank_index + 1, :]))
                matrix_reference = w.copy()
                if name == "act_head.2": matrix_reference[:, :64] += product
                else: matrix_reference[:bb.shape[0], :] += product
                matrix_error = np.abs(effective[which].astype(np.float64) - matrix_reference.astype(np.float64))
                require(np.all(matrix_error <= protocol["matrix_atol"] + protocol["matrix_rtol"] *
                               np.abs(matrix_reference.astype(np.float64))), "EFFECTIVE_MATRIX_REFERENCE_MISMATCH")
                xx = x.astype(np.float64); reference = xx @ w.astype(np.float64).T + b.astype(np.float64)
                delta = ((xx[:, :64] if name == "act_head.2" else xx) @ aa.T) @ bb.T
                if name == "act_head.2":
                    reference += delta
                else:
                    reference[:, :bb.shape[0]] += delta
                require(np.isfinite(y).all() and np.isfinite(reference).all(), "FORWARD_NONFINITE")
                error = np.abs(y.astype(np.float64) - reference)
                allowed = protocol["atol"] + protocol["rtol"] * np.abs(reference)
                require(np.all(error <= allowed), "HEAD_FORWARD_REFERENCE_MISMATCH")
                outputs[which] = y.copy()
                probes[which] = {"max_absolute_error": float(error.max()),
                                "max_error_over_allowed": float((error / allowed).max()),
                                "effective_matrix_max_absolute_error": float(matrix_error.max()),
                                "effective_matrix_reference_pass": True,
                                "allclose": True, "output_sha256": digest(y.tobytes())}
            # This is a real in-memory source-class parent restoration, not a production rollback.
            with torch.no_grad():
                for k in ("A", "B"):
                    prefix = "model." + name + "."
                    value = torch.from_numpy(parent[prefix + k]) if prefix + k in parent else initial[k]
                    getattr(module, k).copy_(value)
                restored = module(torch.from_numpy(x)).detach().numpy()
            require(np.array_equal(restored.view(np.uint32), outputs["parent"].view(np.uint32)), "RESTORE_FORWARD_MISMATCH")
            require(np.array_equal(base.weight.detach().numpy().view(np.uint32), w.view(np.uint32)) and
                    np.array_equal(base.bias.detach().numpy().view(np.uint32), b.view(np.uint32)), "BASE_MUTATED")
            d = effective["child"].astype(np.float64) - effective["parent"].astype(np.float64)
            num = float((d * d).sum()); den = float((effective["parent"].astype(np.float64) ** 2).sum())
            total_num += num; total_den += den
            allowed_mask = np.zeros_like(w, dtype=bool)
            if name == "act_head.2": allowed_mask[:, :64] = True
            else: allowed_mask[:4 if name == "scorer.1" else 1, :] = True
            require(np.count_nonzero(d[~allowed_mask]) == 0, "EFFECT_ESCAPED_MASK")
            rows.append({"name": name, "base_shape": list(w.shape), "factor_rank": int(module.A.shape[0]),
                         "effective_changed_f32_coordinates": int(np.count_nonzero(d)),
                         "effective_delta_l2_squared": num, "parent_l2_squared": den,
                         "relative_delta_l2_f64": math.sqrt(num / den), "all_changes_within_declared_mask": True,
                         "parent_child_max_probe_output_change": float(np.abs(outputs["child"] - outputs["parent"]).max()),
                         "probes": probes, "parent_restore_output_bytes_exact": True, "base_weight_bias_unchanged": True})
        _, _, final_binding = bound_live()
        require(binding == final_binding, "LIVE_BINDING_CHANGED")
        require(read(candidate_dir / "adapter.safetensors", 1048576) == adapter_raw, "ADAPTER_CHANGED_AT_END")
        require(read(candidate_dir / "candidate.json", 524288) == candidate_raw, "MANIFEST_CHANGED_AT_END")
        require(read(parent_dir / "adapter.safetensors", 1048576) == parent_raw, "PARENT_CHANGED_AT_END")
        for _, path, raw in sources.values(): require(read(path, 131072) == raw, "SOURCE_CHANGED_AT_END")
        require(not torch.cuda.is_initialized(), "GPU_INITIALIZED_DURING_PROBE")
        result.update(status="PASS_ISOLATED_SOURCE_HEADS", binding=binding, layers=rows,
                      global_relative_l2_f64=math.sqrt(total_num / total_den),
                      engineering_norm_scope="CPU F32 rounded effective matrices versus bound parent; not exact-real budget proof or original ROCm replay",
                      memory_only_restore_verified=True, live_binding_stable=True,
                      gpu_initialized=torch.cuda.is_initialized(), base_model_content_refreshed=True)
    except Exception as error:
        # No private exception message, paths, row IDs or parameter values are exported.
        result["status"] = "FAILED_PRESERVED"
        own_tree = ast.parse(Path(__file__).read_text())
        failure_codes = {n.args[1].value for n in ast.walk(own_tree) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == "require" and len(n.args) == 2
                         and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)}
        result["failure"] = {"type": type(error).__name__, "message_code": str(error) if
                             str(error) in failure_codes else "REDACTED_EXCEPTION"}
    result["finished_utc"] = utc()
    result["cost"] = {"worker_wall_seconds_through_result": time.perf_counter() - start,
                      "worker_cpu_seconds_through_result": time.process_time() - cpu,
                      "worker_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      "scope": "worker excludes interpreter startup and final result write; supervisor accounts complete process"}
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    require("/home/" not in encoded, "PRIVATE_PATH_EXPORT")
    (output / "RESULTS.json").write_text(encoded)
    print(json.dumps({"status": result["status"], "result_sha256": digest(encoded.encode())}))
    return 0 if result["status"] == "PASS_ISOLATED_SOURCE_HEADS" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().output))
