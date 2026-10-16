"""Research-only physical CPU Head dispatch using *original saved mmBERT features*.

Measures one immutable 384D observation shared by many physically allocated
logical Head slots, comparing identical CPU floating-point work run in a Python
per-slot loop versus a packed NumPy kernel. Also measures fixed 32-active-slot
subsets under identical model weights. This is NOT a production Worker, GPU,
true independently differentiated 4096-Head model, Encoder forward, a new task,
or proof of future efficacy. All outcomes are DENY_ALL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

import numpy as np
from safetensors.numpy import load as load_numpy

import v20_original_material_challenge as frozen

SCHEMA = "hepta.stem.v23.original-feature-packed-head-cost.research"
SIZES = (64, 256, 1024, 4096)
SOURCE_FEATURE_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
SOURCE_INPUT_SHA = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
MODEL_SHA = frozen.SAVED_MODEL_SHA["41-joint"]
WIDTH = 384
OUTPUT_CLASSES = 4
ACTIVE = 32
PROBE_CASES = 4
REQUIRED_TIMED_ROUNDS = 128
MAX_DIFFERENCE = 1e-5


def need(ok, why):
    if not ok:
        raise ValueError(why)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def create_only(path, value):
    path = Path(path)
    need(path.parent.is_dir() and not path.parent.is_symlink() and not path.exists(),
         "create-only real output directory/file required")
    with path.open("xb") as f:
        f.write(canonical(value)); f.flush(); os.fsync(f.fileno())
    return sha(canonical(value))


def load_observations(inputs, v15, v16):
    """Only the original four TRAIN observations; no user text or held labels."""
    inputs = Path(inputs)
    need(inputs.is_dir() and not inputs.is_symlink(), "real original input directory required")
    raw = frozen.bounded_bytes(inputs / "features.safetensors", 300_000)
    need(sha(raw) == SOURCE_FEATURE_SHA, "original feature material changed")
    meta = frozen.read(inputs / "input.json")
    need(sha(frozen.bounded_bytes(inputs / "input.json")) == SOURCE_INPUT_SHA,
         "original source roster changed")
    need(meta.get("production_authorized") is False and
         meta.get("archive_sha256") == "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7",
         "wrong original authority/source identity")
    rows = meta.get("partitions")
    need(type(rows) is dict and set(rows) == {"train", "calibration", "holdout"} and
         len(rows["train"]) == 64 and len(rows["calibration"]) == 32 and
         len(rows["holdout"]) == 32, "original partition split changed")
    data = load_numpy(raw)
    need(set(data) == {"features"} and data["features"].shape == (128, WIDTH) and
         data["features"].dtype == np.float32 and np.isfinite(data["features"]).all(),
         "wrong actual frozen Encoder feature tensor")
    mean, _, split, _, mean_sha = frozen.physically_reload(v15, v16)
    indices = rows["train"][:PROBE_CASES]
    need(len(set(indices)) == PROBE_CASES and all(type(i) is int and 0 <= i < 128 for i in indices),
         "must use four separate old TRAIN cases")
    x = data["features"][indices].copy()
    x = x - mean
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    x = np.ascontiguousarray(x, dtype=np.float32)
    need(np.isfinite(x).all() and x.flags.owndata,
         "finite owned original feature readout required")
    return x, split, mean_sha


def materialize_heads(n, split):
    """Physical unique slots; VALUES intentionally repeat two actually trained Heads.

    This measures infrastructure, not 4096 independently learned expertise.
    """
    need(type(n) is int and n in SIZES, "only preregistered fleet sizes allowed")
    shapes = {"centers": (2, WIDTH)}
    for k in (0, 1):
        shapes[f"heads.{k}.weight"] = (OUTPUT_CLASSES, WIDTH)
        shapes[f"heads.{k}.bias"] = (OUTPUT_CLASSES,)
    need(set(split) == set(shapes) and all(split[k].shape == v and
         split[k].dtype == np.float32 and bool(np.isfinite(split[k]).all())
         for k, v in shapes.items()), "saved original V16 Head tensors changed")
    weights = np.empty((n, OUTPUT_CLASSES, WIDTH), dtype=np.float32)
    biases = np.empty((n, OUTPUT_CLASSES), dtype=np.float32)
    for k in (0, 1):
        weights[k::2] = split[f"heads.{k}.weight"]
        biases[k::2] = split[f"heads.{k}.bias"]
    need(weights.flags.owndata and biases.flags.owndata and
         not np.shares_memory(weights, biases), "real independent physical Head slot storage required")
    return weights, biases


def selected_ids(n):
    need(type(n) is int and n in SIZES, "bounded physical Head fleet required")
    selected = np.array([i * n // ACTIVE for i in range(ACTIVE)], dtype=np.intp)
    need(len(set(selected.tolist())) == ACTIVE, "unique selected Head IDs required")
    return selected


def per_head(weights, biases, feature):
    out = np.empty((len(weights), OUTPUT_CLASSES), dtype=np.float32)
    for i in range(len(weights)):
        out[i] = weights[i] @ feature + biases[i]
    return out


def packed(weights, biases, feature):
    # No repeated feature allocation; original one-dimensional source is broadcast by NumPy.
    return np.einsum("nkd,d->nk", weights, feature, optimize=False) + biases


def quantized_digest(scores):
    need(scores.ndim == 2 and scores.shape[1] == OUTPUT_CLASSES and
         np.isfinite(scores).all() and float(np.max(np.abs(scores))) < 1e4,
         "bounded real physical logits required")
    return sha(np.ascontiguousarray(np.rint(scores * 1e4).astype("<i8")).tobytes())


def percentile(vals, q):
    need(type(vals) is list and len(vals) >= 100 and all(type(x) is int and x > 0 for x in vals),
         "p95/p99 require 100+ positive measured request samples")
    a = sorted(vals)
    position = (len(a)-1)*q
    low = int(position)
    weight = position-low
    return float(a[low]*(1-weight) + a[min(low+1,len(a)-1)]*weight)


def baseline_proof(weights, biases, features, ids):
    need(tuple(features.shape) == (PROBE_CASES, WIDTH) and
         features.dtype == np.float32 and np.isfinite(features).all(),
         "four valid original scoped observations required")
    output = []
    for feature in features:
        d = per_head(weights, biases, feature)
        p = packed(weights, biases, feature)
        sd = per_head(weights[ids], biases[ids], feature)
        sp = packed(weights[ids], biases[ids], feature)
        err = max(float(np.max(np.abs(d-p))),float(np.max(np.abs(sd-sp))))
        need(err <= MAX_DIFFERENCE and
             np.array_equal(np.argmax(d,axis=1),np.argmax(p,axis=1)) and
             np.array_equal(np.argmax(sd,axis=1),np.argmax(sp,axis=1)),
             "same frozen Head logits/top-choice changed under packing")
        output.append({"full_logit_quantized_sha256":quantized_digest(d),
                       "active_logit_quantized_sha256":quantized_digest(sd),
                       "max_f32_kernel_difference":err})
    return output


def benchmark(inputs, v15, v16, n, *, rounds=REQUIRED_TIMED_ROUNDS, warmups=8):
    need(type(rounds) is int and 100 <= rounds <= 256 and
         type(warmups) is int and 0 <= warmups <= 32,
         "bounded 100+ repeated CPU measurements required")
    # A one-thread CPU environment must be established BEFORE importing NumPy.
    need(all(os.environ.get(k) == "1" for k in
             ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")),
         "must enforce one-thread CPU controls before numeric import")
    features, split, mean_sha = load_observations(inputs, v15, v16)
    rss_before = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    weights, biases = materialize_heads(n, split)
    ids = selected_ids(n)
    # Materialize the 32 active Head weights ONCE, outside the timed loop.
    # This is a charged secondary weight cache, not extra pretrained skills.
    active_weights = np.ascontiguousarray(weights[ids])
    active_biases = np.ascontiguousarray(biases[ids])
    need(active_weights.flags.owndata and active_biases.flags.owndata and
         not np.shares_memory(active_weights, weights),
         "32 selected Head weights must be pre-cached before inference")
    proof = baseline_proof(weights, biases, features, ids)
    rss_after = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    functions = {"all_loop":lambda x:per_head(weights,biases,x),
                 "all_packed":lambda x:packed(weights,biases,x),
                 "active32_loop":lambda x:per_head(active_weights,active_biases,x),
                 "active32_packed":lambda x:packed(active_weights,active_biases,x)}
    for i in range(warmups):
        x=features[i % PROBE_CASES]
        for f in functions.values():
            f(x)
    samples={name:[] for name in functions}
    proc_ns={name:0 for name in functions}
    for i in range(rounds):
        x=features[i % PROBE_CASES]
        # Rotate measurement order to reduce recurring thermal/order bias.
        names=list(functions)
        names=names[i%len(names):]+names[:i%len(names)]
        for name in names:
            a=time.perf_counter_ns();c=time.process_time_ns()
            scores=functions[name](x)
            elapsed=time.perf_counter_ns()-a
            cpu=time.process_time_ns()-c
            need(scores.shape == (n if name.startswith("all") else ACTIVE,OUTPUT_CLASSES) and
                 np.isfinite(scores).all(),"measured physical logits invalid")
            samples[name].append(max(1,elapsed));proc_ns[name]+=max(1,cpu)
    return {
        "schema":SCHEMA,"source_kind":"original_pretrained_mmbert_cached_features_only",
        "producer_source_sha256":sha(Path(__file__).read_bytes()),
        "feature_sha256":SOURCE_FEATURE_SHA,"input_source_sha256":SOURCE_INPUT_SHA,
        "v15_normalizer_sha256":mean_sha,"original_v16_split_file_sha256":MODEL_SHA,
        "model_origin_signed_by_publisher":False,"encoder_forward_count_this_run":0,
        "physical_cell_slots":n,"physically_allocated_individual_head_slots":n,
        "unique_independently_trained_head_values":2,
        "weight_bank_bytes":weights.nbytes+biases.nbytes,
        "selected_cached_head_weight_bytes":active_weights.nbytes+active_biases.nbytes,
        "total_actual_head_storage_bytes":weights.nbytes+biases.nbytes+active_weights.nbytes+active_biases.nbytes,
        "logical_active_ids":ids.tolist(),"shared_original_feature_count":PROBE_CASES,
        "per_cell_feature_copies_made":0,"probe_numeric_consistency":proof,
        "benchmark_measurement":"local_one_thread_CPU_kernel_wall_and_process_time_not_full_worker",
        "timed_rounds":rounds,"warmups":warmups,
        "whole_process_rusage_maxrss_kib_before_weights":rss_before,
        "whole_process_rusage_maxrss_kib_after_benchmark":int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "whole_process_rusage_maxrss_kib_after_weights":rss_after,
        "profiles":{name:{"latency_ns_samples":times,
                 "p95_ns":percentile(times,.95),"p99_ns":percentile(times,.99),
                 "process_cpu_ns":proc_ns[name]}
                 for name,times in samples.items()},
        "research_result":"CPU_KERNEL_MECHANISM_ONLY_NOT_NEW_CELL_SKILL",
        "actual_target_device_host_verified":False,
        "feature_cache_authority_verified":False,
        "new_independent_future_sources":0,
        "prospective_utility_verified":False,"old_task_retention_verified":False,
        "signed_meter_or_hardware_attested":False,
        "scientific_promotion_authorized":False,"production_authorized":False,
        "authority_posture":"DENY_ALL"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs",required=True)
    p.add_argument("--v15",required=True)
    p.add_argument("--v16",required=True)
    p.add_argument("--cells",required=True,type=int,choices=SIZES)
    p.add_argument("--out",required=True)
    p.add_argument("--rounds",type=int,default=REQUIRED_TIMED_ROUNDS)
    a=p.parse_args()
    result=benchmark(a.inputs,a.v15,a.v16,a.cells,rounds=a.rounds)
    create_only(a.out,result)


if __name__=="__main__":
    main()
