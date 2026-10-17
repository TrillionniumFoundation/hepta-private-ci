"""Independent original-material Rust V24 CPU operator and source audit.

Does not import the V24 frame producer or execute the Rust probe. Reloads the
original source/model through the pre-existing V20 immutable tensor contract;
recomputes every native Rust float output and p95/p99 from raw samples. The
bare research generation/fence is never accepted as production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from safetensors.numpy import load

import v20_original_material_challenge as model

ROWS, WIDTH, CLASSES = 4, 384, 4
SIZES = (64, 256, 1024, 4096)
MAGIC = b"HPV24\x00\x00\x01"
SRC_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
INPUT_SHA = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
MODEL_SHA = model.SAVED_MODEL_SHA["41-joint"]
SCHEMA = "hepta.stem.v24.rust-packed-worker-shadow.research"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def duplicates(items):
    result = {}
    for k, v in items:
        require(k not in result, "duplicate JSON fields")
        result[k] = v
    return result


def bounded(path, maximum):
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= maximum,
            "bounded regular original material required")
    return p.read_bytes()


def read_json(path):
    data = json.loads(bounded(path, 2_000_000), object_pairs_hook=duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    canonical(data)
    return data


def quantile(a, q):
    require(type(a) is list and len(a) == 128 and all(type(v) is int and 0 < v < 10**12 for v in a),
            "exact 128 measured wall samples required")
    x = sorted(a)
    pos = (len(x) - 1) * q
    i = int(pos)
    frac = pos - i
    return (x[i] * (1 - frac) + x[min(i+1, len(x)-1)] * frac) / 1e6


def read_original(inputs, v15, v16):
    raw_input = bounded(Path(inputs)/"input.json", 40_000)
    raw_features = bounded(Path(inputs)/"features.safetensors", 300_000)
    require(sha(raw_input) == INPUT_SHA and sha(raw_features) == SRC_SHA,
            "original pretrained frozen feature/input bytes drift")
    source = json.loads(raw_input)
    require(source["production_authorized"] is False
            and source["archive_sha256"] == "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7",
            "source lineage changed")
    arr = load(raw_features)["features"]
    require(arr.shape == (128, WIDTH) and arr.dtype == np.float32 and np.isfinite(arr).all(),
            "bad original source feature")
    train = source["partitions"]["train"][:4]
    require(len(set(train)) == 4, "duplicate original TRAIN identities")
    mean, _, split, _, mean_sha = model.physically_reload(v15, v16)
    original = np.array(arr[train] - mean, dtype=np.float32, copy=True)
    original /= np.maximum(np.linalg.norm(original, axis=1, keepdims=True), 1e-12)
    return original, split, mean_sha


def validate_wire(wire, original, split, mean_sha, slots):
    require(wire[:8] == MAGIC and len(wire) <= 32*1024,
            "wrong or oversized Rust original material wire")
    n, observations = struct.unpack_from("<II", wire, 8)
    require(n == slots and observations == ROWS, "wrong physical slot count")
    tags = struct.unpack_from("<12Q", wire, 16)
    require(tags[:6] == tags[6:] and all(tags[:6]) and tags == (11,17,23,29,31,37)*2,
            "research generation/fence/epoch/scope/principal/purpose drift")
    offset = 16 + 96
    require(wire[offset:offset+96] == bytes.fromhex(SRC_SHA)+bytes.fromhex(MODEL_SHA)+bytes.fromhex(mean_sha),
            "source feature/model/normalizer digest drift")
    offset += 96
    fixture = original.astype("<f4", copy=False).tobytes()
    require(wire[offset:offset+len(fixture)] == fixture, "different actual original feature values")
    offset += len(fixture)
    for idx in (0,1):
        for key in (f"heads.{idx}.weight",f"heads.{idx}.bias"):
            b = np.ascontiguousarray(split[key], dtype="<f4").tobytes()
            require(wire[offset:offset+len(b)] == b, "original trained model value changed")
            offset += len(b)
    require(offset == len(wire), "additional unregistered original material")


def independent_logits(original, split, slots):
    # Independent double accumulator, preserving original f32 tensor values.
    output = np.empty((ROWS, slots, CLASSES), dtype=np.float32)
    for case in range(ROWS):
        for idx in (0,1):
            w = split[f"heads.{idx}.weight"].astype(np.float64)
            b = split[f"heads.{idx}.bias"].astype(np.float64)
            p = (w @ original[case].astype(np.float64) + b).astype(np.float32)
            output[case, idx::2] = p
    return output


def review(inputs, v15, v16, root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "real bounded original proof directory required")
    original, split, mean_sha = read_original(inputs, v15, v16)
    manifest = read_json(root / "source-manifest.json")
    require(manifest["schema"] == "hepta.stem.v24.original-frozen-rust-wire.research"
            and manifest["source_feature_sha256"] == SRC_SHA and manifest["source_input_sha256"] == INPUT_SHA
            and manifest["original_saved_model_sha256"] == MODEL_SHA
            and manifest["v15_normalizer_sha256"] == mean_sha
            and manifest["production_authorized"] is False
            and manifest["rust_worker_driver_integrated"] is False
            and manifest["q24_parity_qualified"] is False
            and manifest["two_original_trained_head_values_replicated"] is True
            and manifest["slots"] == list(SIZES), "original source manifest or negative authority drift")
    result = {}
    for n in SIZES:
        wire = bounded(root/f"frame-{n}.bin",32*1024)
        require(sha(wire) == manifest[f"frame_sha256_{n}"], "source frame SHA mismatch")
        validate_wire(wire, original, split, mean_sha, n)
        obj = read_json(root/f"rust-report-{n}.json")
        require(obj["schema"] == SCHEMA and obj["authority"] == "DENY_ALL"
                and obj["production_authorized"] is False
                and obj["rust_source_input_is_signature_authenticated"] is False
                and obj["worker_model_driver_integrated"] is False
                and obj["q24_policy_parity_verified"] is False
                and obj["original_encoder_forward_count"] == 0
                and obj["future_source_count"] == 0
                and obj["original_pretrained_cell_skills"] == 2
                and obj["physically_allocated_head_slots"] == n
                and obj["logical_active_heads"] == 32
                and obj["feature_width"] == WIDTH and obj["original_train_probes"] == ROWS
                and obj["source_feature_sha256"] == SRC_SHA
                and obj["v16_model_sha256"] == MODEL_SHA and obj["v15_mean_sha256"] == mean_sha
                and obj["allocated_head_weight_bytes"] == n*1540*4
                and obj["selected_cache_head_weight_bytes"] == 32*1540*4
                and obj["shared_feature_bytes"] == ROWS*WIDTH*4
                and obj["timed_rounds"] == 128 and obj["warmups"] == 8
                and obj["comparison_only_accumulation"] == "f64-of-original-f32"
                and obj["research_generation"] == 11 and obj["research_fence"] == 17
                and obj["research_epoch"] == 23 and obj["research_scope"] == 29
                and obj["research_principal"] == 31 and obj["research_purpose"] == 37,
                "Rust physical source/counter/authority mismatch")
        require(all(obj[k] is None or (type(obj[k]) is int and 0 < obj[k] < 1<<37)
                    for k in ("whole_process_rss_after_bank_bytes", "whole_process_peak_rss_bytes")),
                "invalid per-process resident meter")
        require(type(obj["rolling_consumed_output"]) in (float,int)
                and np.isfinite(obj["rolling_consumed_output"]), "nonfinite bench consumption")
        samples = {}
        for name in ("scalar_full","packed_full","packed_active32"):
            a = obj[f"{name}_wall_samples_ns"]
            require(abs(obj[f"{name.split('_')[0] if name != 'packed_active32' else 'active32'}_p99_ms"] - quantile(a,.99)) < 1e-6,
                    "p99 not derived from 128 actual rust wall samples")
            samples[name] = a
        native = np.frombuffer(bounded(root/f"rust-logits-{n}.bin", ROWS*n*CLASSES*4+4),dtype="<f4")
        require(native.size == ROWS*n*CLASSES and np.isfinite(native).all(),
                "unbounded/nonfinite original Rust Head output")
        actual = native.reshape(ROWS,n,CLASSES)
        expected = independent_logits(original, split, n)
        delta = float(np.max(np.abs(expected - actual)))
        require(delta <= 2e-6 and np.array_equal(expected.argmax(2),actual.argmax(2)),
                "original saved model logits changed under native execution")
        result[str(n)] = {"physical_head_slots":n,"native_output_file_sha256":sha(native.tobytes()),
                         "original_head_weight_bytes":n*1540*4,
                         "rust_scalar_p99_ms":obj["scalar_p99_ms"],
                         "rust_packed_p99_ms":obj["packed_p99_ms"],
                         "rust_packed_active32_p99_ms":obj["active32_p99_ms"],
                         "whole_process_peak_rss_bytes":obj["whole_process_peak_rss_bytes"],
                         "max_original_numpy_f32_logit_difference":delta,
                         "timed_samples_per_arm":len(samples["scalar_full"])}
    return {"schema":"hepta.stem.v24.original-rust-worker-shadow.independent-audit",
            "source_sha256":SRC_SHA,"model_sha256":MODEL_SHA,"model_origin_signed":False,
            "no_new_primitive_cell_skills":True,"rust_worker_trait_integrated":False,
            "native_rust_binary_execution_verified_by_numeric_replay":True,
            "four_original_train_probes":True,"numerical_accumulation_f64_from_original_f32":True,
            "v23_python_packed_head_performance_replaced":False,
            "production_authorized":False,"new_future_sources":0,
            "trusted_target_host_evidence":False,"full_worker_wal_cas_finaluse":False,
            "authority_posture":"DENY_ALL","sizes":result}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs",type=Path,required=True)
    p.add_argument("--v15",type=Path,required=True)
    p.add_argument("--v16",type=Path,required=True)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=review(args.inputs,args.v15,args.v16,args.root)
    with args.output.open("xb") as f:f.write(canonical(result));f.flush()

if __name__=="__main__":main()
