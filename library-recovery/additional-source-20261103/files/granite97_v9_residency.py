#!/usr/bin/env python3
"""Real immutable Granite97 BF16 weight residency, never model inference.

Research-only, source-scoped, no trained Head and no hardware attestation.
Usage: python granite97_v9_residency.py --model-root PATH --lock PATH --source PATH --output FILE
Requires PyTorch CPU, safetensors and psutil only for the physical worker phase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")
MODEL = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
SOURCE_SHA = "8d6dd20b7f64904c33b81a90a204d6f123e87b45b40cf7ac519862ef96812610"
HEAD_SIZE = 6914
MODEL_TENSORS = 74
MODEL_ELEMENTS = 97_441_152
MODEL_WEIGHT_BYTES = MODEL_ELEMENTS * 2
PROFILES = (("shared", 4, 1), ("replicated", 4, 4), ("shared", 64, 1),
            ("shared", 256, 1), ("shared", 1024, 1), ("shared", 4096, 1))
SCHEMA = "hepta.granite97.real-weight-residency.v2"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def strict_json(path: Path, maximum: int = 16_384) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("missing, symlinked or oversized source manifest")
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("duplicate JSON key")
            obj[k] = v
        return obj
    data = json.loads(path.read_bytes(), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError("non-object JSON input")
    return data


def verify_material(root: Path, lock_path: Path, source_path: Path) -> tuple[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("untrusted model directory")
    material = strict_json(root / "material.json")
    lock = strict_json(lock_path)
    if (material.get("model_id"), material.get("revision")) != (MODEL, REVISION):
        raise ValueError("unregistered upstream revision")
    if set(material.get("files", {})) != set(FILES) or set(material.get("sha256", {})) != set(FILES):
        raise ValueError("incomplete exact-file manifest")
    if (lock.get("model_id"), lock.get("revision"), lock.get("source_sha256")) != (MODEL, REVISION, SOURCE_SHA):
        raise ValueError("external immutable lock incompatible")
    if (lock.get("authority") != "DENY_ALL" or lock.get("production_authorized") is not False
            or lock.get("model_selected") is not False or lock.get("labels_exposed") is not False
            or lock.get("independent_model_owner_authenticated") is not False
            or lock.get("independent_source_owner_authenticated") is not False):
        raise ValueError("research-only authority or provenance claim changed")
    if type(lock.get("expires_at_ms")) is not int or lock["expires_at_ms"] <= time.time_ns() // 1_000_000:
        raise ValueError("original research source lock expired")
    if source_path.is_symlink() or not source_path.is_file() or sha_file(source_path) != SOURCE_SHA:
        raise ValueError("changed original complete source")
    parts = [b"hepta.stem.granite97.material.v5\0"]
    total = 0
    for name in sorted(FILES):
        file = root / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("missing or redirected model file")
        size = file.stat().st_size
        if type(material["files"][name]) is not int or size != material["files"][name] or size <= 0:
            raise ValueError("modified model file size")
        total += size
        if total > 512_000_000:
            raise ValueError("model memory budget exceeded")
        digest = sha_file(file)
        if digest != material["sha256"][name]:
            raise ValueError("model digest differs from frozen manifest")
        raw = name.encode()
        parts.extend((len(raw).to_bytes(4, "big"), raw, size.to_bytes(8, "big"), bytes.fromhex(digest)))
    digest = hashlib.sha256(b"".join(parts)).hexdigest()
    if digest != lock.get("material_sha256"):
        raise ValueError("model manifest does not match immutable source lock")
    return digest, material["sha256"]["model.safetensors"]


def physical_worker(model: Path, expected_sha: str, mode: str, cells: int, copies: int) -> dict:
    import psutil
    import torch
    from safetensors import safe_open
    if sha_file(model) != expected_sha:
        raise ValueError("physical model material changed")
    if (mode, cells, copies) not in PROFILES:
        raise ValueError("unregistered resource arm")
    torch.set_num_threads(1)
    process = psutil.Process()
    before = process.memory_info().rss
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    with safe_open(str(model), framework="pt", device="cpu") as reader:
        original = {key: reader.get_tensor(key) for key in reader.keys()}
    if len(original) != MODEL_TENSORS or sum(t.numel() for t in original.values()) != MODEL_ELEMENTS:
        raise ValueError("original model tensor inventory changed")
    if any(t.dtype != torch.bfloat16 for t in original.values()):
        raise ValueError("model is not frozen BF16")
    bank = [{key: tensor.clone().contiguous() for key, tensor in original.items()} for _ in range(copies)]
    heads = torch.zeros((cells, HEAD_SIZE), dtype=torch.bfloat16)
    objects = [(bank[0], heads[i]) for i in range(cells)]
    pointers = {(key, tensor.untyped_storage().data_ptr()) for resident in bank for key, tensor in resident.items()}
    if len(pointers) != MODEL_TENSORS * copies or len(objects) != cells:
        raise ValueError("resident tensors were unexpectedly coalesced")
    assert all(obj[0] is bank[0] for obj in objects)
    assert not sum(float(x[1][0]) for x in objects[:min(32, cells)])
    after = process.memory_info().rss
    result = dict(mode=mode, logical_cells=cells, resident_model_copies=copies,
                  unique_model_tensor_storages=len(pointers),
                  actual_model_weight_bytes=MODEL_WEIGHT_BYTES * copies,
                  per_cell_head_scalars=HEAD_SIZE, actual_head_bytes=heads.numel() * heads.element_size(),
                  rss_before_bytes=before, rss_after_bytes=after, rss_increment_bytes=after - before,
                  measured_wall_ns=time.perf_counter_ns() - start_wall,
                  measured_cpu_ns=time.process_time_ns() - start_cpu,
                  forward_calls=0, training_steps=0, production_authorized=False, authority="DENY_ALL")
    if result["rss_increment_bytes"] <= 0:
        raise ValueError("physical allocation not observed")
    return result


def verify_receipts(receipts: list[dict]) -> None:
    if not isinstance(receipts, list) or len(receipts) != len(PROFILES):
        raise ValueError("missing matched physical residency arms")
    exact = {"mode", "logical_cells", "resident_model_copies", "unique_model_tensor_storages",
             "actual_model_weight_bytes", "per_cell_head_scalars", "actual_head_bytes",
             "rss_before_bytes", "rss_after_bytes", "rss_increment_bytes", "measured_wall_ns",
             "measured_cpu_ns", "forward_calls", "training_steps", "production_authorized", "authority"}
    for observed, (mode, cells, copies) in zip(receipts, PROFILES, strict=True):
        if (not isinstance(observed, dict) or set(observed) != exact
            or (observed.get("mode"), observed.get("logical_cells"), observed.get("resident_model_copies")) != (mode, cells, copies)
            or observed.get("unique_model_tensor_storages") != copies * MODEL_TENSORS
            or observed.get("actual_model_weight_bytes") != copies * MODEL_WEIGHT_BYTES
            or observed.get("per_cell_head_scalars") != HEAD_SIZE
            or observed.get("actual_head_bytes") != cells * HEAD_SIZE * 2
            or observed.get("forward_calls") != 0 or observed.get("training_steps") != 0
            or observed.get("authority") != "DENY_ALL" or observed.get("production_authorized") is not False):
            raise ValueError("unmatched, unphysical or falsely qualified resource arm")
        for key in ("rss_before_bytes", "rss_after_bytes", "rss_increment_bytes", "measured_wall_ns", "measured_cpu_ns"):
            if type(observed[key]) is not int or observed[key] <= 0:
                raise ValueError("missing actual physical resource measurement")
        if observed["rss_after_bytes"] - observed["rss_before_bytes"] != observed["rss_increment_bytes"]:
            raise ValueError("process RSS delta cannot be replayed")
    if receipts[1]["rss_increment_bytes"] <= receipts[0]["rss_increment_bytes"]:
        # If this invariant is not true on a busy host, report unavailable instead
        # of inventing a positive shared-weight memory effect.
        raise ValueError("resident-copy memory contrast not supported by measured RSS")


def run(model_root: Path, lock: Path, source: Path, output: Path) -> dict:
    material_digest, model_sha = verify_material(model_root, lock, source)
    receipts = []
    for mode, count, copies in PROFILES:
        invocation = [sys.executable, str(Path(__file__).resolve()), "--worker", "--model-root", str(model_root),
                      "--material-sha256", model_sha, "--mode", mode, "--cells", str(count), "--copies", str(copies)]
        proc = subprocess.run(invocation, capture_output=True, text=True, timeout=80, check=False)
        if proc.returncode != 0:
            raise RuntimeError("local physical weight allocation failed: " + proc.stderr[-700:])
        receipts.append(json.loads(proc.stdout))
    verify_receipts(receipts)
    # Confirm a second source/material hash after all the physical model loads.
    material_after, model_after = verify_material(model_root, lock, source)
    if material_after != material_digest or model_after != model_sha:
        raise ValueError("model material changed during subprocess measurements")
    report = {"schema": SCHEMA, "model_id": MODEL, "revision": REVISION,
              "source_sha256": SOURCE_SHA, "material_digest": material_digest,
              "pretrained_weights_sha256": model_sha,
              "model_weight_parameters": MODEL_ELEMENTS,
              "experimental_scope": "actual BF16 cloned CPU storage, individually addressed untrained Q24-independent BF16 Head slots",
              "process_rss_not_gpu_or_end_to_end_latency": True,
              "true_transformer_forward_executed": False,
              "independently_qualified_human_task_efficacy": False,
              "hardware_attestation": False, "model_selected": False,
              "production_authorized": False, "authority": "DENY_ALL",
              "trials": receipts}
    if output.exists() or output.is_symlink():
        raise ValueError("create-only output required")
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with output.open("xb") as writer:
        writer.write(payload)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--material-sha256")
    parser.add_argument("--mode", choices=("shared", "replicated"))
    parser.add_argument("--cells", type=int)
    parser.add_argument("--copies", type=int)
    args = parser.parse_args()
    if args.worker:
        if not args.material_sha256 or not args.mode or args.cells is None or args.copies is None:
            raise SystemExit("incomplete internal physical worker arguments")
        print(json.dumps(physical_worker(args.model_root / "model.safetensors", args.material_sha256,
                                         args.mode, args.cells, args.copies), sort_keys=True))
    else:
        if args.lock is None or args.source is None or args.output is None:
            raise SystemExit("original source/material lock and create-only output required")
        print(json.dumps(run(args.model_root, args.lock, args.source, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
