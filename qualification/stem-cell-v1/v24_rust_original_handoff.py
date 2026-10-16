"""Build private Rust V24 input frames from SHA-verified original V16 features.

No model download, synthetic fallback, label reading or production effect.
The Rust executor receives exact original f32 values over a bounded binary wire.
Both writer and independent reviewer validate source identity; the Rust probe
checks bounds, mirrored generation/fence/epoch and numeric reference parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from safetensors.numpy import load as load_numpy

import v20_original_material_challenge as previous

MAGIC = b"HPV24\x00\x00\x01"
SIZES = (64, 256, 1024, 4096)
ROWS, WIDTH, CLASSES = 4, 384, 4
SRC_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
INPUT_SHA = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
MODEL_SHA = previous.SAVED_MODEL_SHA["41-joint"]
REF_SCOPE = (11, 17, 23, 29, 31, 37)
SOURCE_SCHEMA = "hepta.stem.v24.original-frozen-rust-wire.research"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def regular(path: Path, maximum: int) -> bytes:
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
            "bounded regular frozen file required")
    return path.read_bytes()


def original_material(inputs: Path, v15: Path, v16: Path):
    inputs, v15, v16 = map(Path, (inputs, v15, v16))
    meta_raw = regular(inputs / "input.json", 40_000)
    feature_raw = regular(inputs / "features.safetensors", 300_000)
    require(sha(meta_raw) == INPUT_SHA and sha(feature_raw) == SRC_SHA,
            "original mmBERT input/feature SHA changed")
    meta = json.loads(meta_raw)
    require(meta.get("production_authorized") is False
            and meta.get("archive_sha256") == "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
            and set(meta.get("partitions", {})) == {"train", "calibration", "holdout"},
            "original source roster or authority changed")
    train = meta["partitions"]["train"]
    require(len(train) == 64 and len(set(train[:ROWS])) == ROWS,
            "must use four distinct original TRAIN records")
    tensors = load_numpy(feature_raw)
    require(set(tensors) == {"features"} and tensors["features"].shape == (128, WIDTH)
            and tensors["features"].dtype == np.float32 and np.isfinite(tensors["features"]).all(),
            "wrong original frozen feature tensor")
    mean, _, split, _, mean_sha = previous.physically_reload(v15, v16)
    shapes = {"centers": (2, WIDTH)}
    for index in (0, 1):
        shapes[f"heads.{index}.weight"] = (CLASSES, WIDTH)
        shapes[f"heads.{index}.bias"] = (CLASSES,)
    require(set(split) == set(shapes) and all(split[k].shape == shape
        and split[k].dtype == np.float32 and np.isfinite(split[k]).all()
        for k, shape in shapes.items()), "original trained Head tensor identity invalid")
    x = np.array(tensors["features"][train[:ROWS]] - mean, dtype=np.float32, copy=True)
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    require(x.shape == (ROWS, WIDTH) and np.isfinite(x).all(), "invalid original normalized rows")
    return np.ascontiguousarray(x, dtype="<f4"), split, mean_sha


def create_only(path: Path, raw: bytes) -> None:
    path = Path(path)
    require(path.parent.is_dir() and not path.parent.is_symlink() and not path.exists(),
            "existing canonical output parent and new file required")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()


def build_frame(features, split, mean_sha: str, slots: int, *, scope=REF_SCOPE, request=REF_SCOPE) -> bytes:
    require(type(slots) is int and slots in SIZES, "bounded registered fleet only")
    require(type(scope) in (tuple, list) and type(request) in (tuple, list)
            and len(scope) == len(request) == 6
            and all(type(x) is int and 0 < x < 2**64 for x in (*scope, *request)),
            "research generation/fence/epoch/scope/principal/purpose binding required")
    require(scope == request, "stale or mixed research generation/fence request")
    require(type(mean_sha) is str and len(mean_sha) == 64 and mean_sha != "0" * 64,
            "missing original mean digest")
    require(features.shape == (ROWS, WIDTH) and features.dtype == np.float32
            and np.isfinite(features).all(), "nonfinite or mismatched physical source vector")
    wire = bytearray(MAGIC)
    wire += struct.pack("<II", slots, ROWS)
    wire += struct.pack("<12Q", *(list(scope) + list(request)))
    wire += bytes.fromhex(SRC_SHA) + bytes.fromhex(MODEL_SHA) + bytes.fromhex(mean_sha)
    wire += np.ascontiguousarray(features, dtype="<f4").tobytes()
    for slot in (0, 1):
        for key in (f"heads.{slot}.weight", f"heads.{slot}.bias"):
            arr = np.ascontiguousarray(split[key], dtype="<f4")
            require(np.isfinite(arr).all(), "original frozen Head changed")
            wire += arr.tobytes()
    require(0 < len(wire) <= 32*1024, "Rust wire size overflow")
    return bytes(wire)


def prepare(inputs: Path, v15: Path, v16: Path, output: Path):
    original, split, mean_sha = original_material(inputs, v15, v16)
    output = Path(output)
    require(not output.exists(), "create-only private work directory")
    output.mkdir(mode=0o700)
    manifest = {"schema": SOURCE_SCHEMA, "source_feature_sha256": SRC_SHA,
        "source_input_sha256": INPUT_SHA, "original_saved_model_sha256": MODEL_SHA,
        "v15_normalizer_sha256": mean_sha, "slots": list(SIZES),
        "real_pretrained_encoder_forward_this_round": 0,
        "new_independently_trained_heads": 0,
        "two_original_trained_head_values_replicated": True,
        "original_train_rows": ROWS, "production_authorized": False,
        "authority_posture": "DENY_ALL", "generation_fence_scope_are_research_only": True,
        "rust_worker_driver_integrated": False, "q24_parity_qualified": False}
    for n in SIZES:
        data = build_frame(original, split, mean_sha, n)
        create_only(output / f"frame-{n}.bin", data)
        manifest[f"frame_sha256_{n}"] = sha(data)
    create_only(output / "source-manifest.json", canonical(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--v15", type=Path, required=True)
    parser.add_argument("--v16", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.inputs, args.v15, args.v16, args.output)


if __name__ == "__main__":
    main()
