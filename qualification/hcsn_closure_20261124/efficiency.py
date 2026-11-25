"""Complete forward/backward and long-BPTT qualification of optional kernels.

Synthetic numerical probes never read train/dev/test examples. Each case is a
fresh process; comparisons include every named parameter VJP and input VJP,
all returned state fields, logits and features. They are not full Jacobians.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import os
import resource
import subprocess
import sys
import traceback

import numpy as np
import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .fast_kernel import FastSignedHCSN
from .models import SignedHCSN
from .provenance import create, digest, read


REPO_ROOT = Path(__file__).resolve().parents[2]


def source_identity():
    base_path = REPO_ROOT/"INSTALLATION.json"
    if digest(base_path) != "e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced":
        raise ValueError("unexpected frozen base source installation")
    base = read(base_path)
    for name, expected in base.items():
        if digest(REPO_ROOT/name) != expected:
            raise ValueError("base executable dependency changed: "+name)
    names = ("efficiency.py", "fast_kernel.py", "fast_tests.py")
    return {**base, **{str(Path(__file__).relative_to(REPO_ROOT).with_name(name)):
                      digest(Path(__file__).with_name(name)) for name in names}}

def execute(model, x, target):
    model.zero_grad(set_to_none=True)
    x = x.detach().clone().requires_grad_()
    cpu, wall = time.process_time(), time.perf_counter()
    logits, features, state = model(x, return_features=True)
    loss = (.8*torch.nn.functional.cross_entropy(logits[-1], target)
            +.2*torch.nn.functional.cross_entropy(logits.flatten(0, 1), target.expand(len(logits), -1).flatten()))
    loss.backward()
    cpu, wall = time.process_time()-cpu, time.perf_counter()-wall
    params, missing, grad = [], [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        params.append(name)
        if p.grad is None:
            missing.append(name)
            grad.append(torch.zeros_like(p).flatten())
        else:
            grad.append(p.grad.flatten())
    data = {"logits": logits.detach().double().cpu().numpy(),
            "features": features.detach().double().cpu().numpy(),
            "parameter_vjp": torch.cat(grad).detach().double().cpu().numpy(),
            "input_vjp": x.grad.detach().double().cpu().numpy()}
    for name in ("density", "boundary", "drift", "cost", "message"):
        data["state_"+name] = getattr(state, name).detach().double().cpu().numpy()
    if not all(np.isfinite(v).all() for v in data.values()):
        raise FloatingPointError("nonfinite complete numerical probe")
    return data, {"cpu_seconds": cpu, "wall_seconds": wall,
                  "parameters": params, "none_gradients": missing,
                  "diagnostics": model.last_diagnostics, "loss": float(loss.detach())}


def compare(reference, candidate):
    rows = {}
    for name, expected in reference.items():
        delta = candidate[name]-expected
        rows[name] = {"max_abs": float(np.max(np.abs(delta))),
                      "relative_l2": float(np.linalg.norm(delta.ravel())/max(1e-12, np.linalg.norm(expected.ravel())))}
    return rows


def case(root, n, length, batch, precision):
    protocol = read(root/"PROTOCOL.json")
    if protocol["source_hashes"] != source_identity() or [n, length, batch, precision] not in protocol["cases"]:
        raise ValueError("unregistered case or changed executable source")
    name = f"n{n}-t{length}-b{batch}-{precision}"
    out = root/name
    out.mkdir(exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(74123+n+length)
    config = ModelConfig(neurons=n, message_mode="flow", backend="uniformized", precision=precision)
    reference = SignedHCSN(config)
    initial = {k: v.detach().clone() for k, v in reference.state_dict().items()}
    dtype = reference.input_drive.weight.dtype
    x = torch.randn(length, batch, 6, dtype=dtype)*.3
    target = torch.arange(batch, dtype=torch.long) % 2
    rows, failures, raw, models = {}, {}, {}, {}
    for implementation in ("original", "newton_cache", "scripted_cache"):
        start = time.perf_counter()
        try:
            model = reference if implementation == "original" else FastSignedHCSN(config, scripted=implementation == "scripted_cache")
            model.load_state_dict(initial)
            data, cold = execute(model, x, target)
            cold["construct_load_forward_backward_wall"] = time.perf_counter()-start
            rows[implementation] = {"cold": cold, "repeats": []}
            models[implementation] = model
            raw[implementation] = data
            np.savez_compressed(out/(implementation+".npz"), **data)
        except Exception:
            failures[implementation] = traceback.format_exc()
    warm_order = []
    if length == 12:
        names = ("original", "newton_cache", "scripted_cache")
        for repeat in range(3):
            for implementation in names[repeat:]+names[:repeat]:
                if implementation not in models:
                    continue
                try:
                    data, timed = execute(models[implementation], x, target)
                    timed["cold_vs_warm"] = compare(raw[implementation], data)
                    rows[implementation]["repeats"].append(timed)
                    warm_order.append(implementation)
                except Exception:
                    failures[implementation+"_warm_"+str(repeat)] = traceback.format_exc()
    comparisons = {}
    if "original" in raw:
        for implementation in ("newton_cache", "scripted_cache"):
            if implementation in raw:
                comparisons[implementation] = compare(raw["original"], raw[implementation])
    # A true FP64 reference uses the exact same representational weights and
    # buffers promoted from this case; initialization RNG differences excluded.
    if precision != "float64":
        try:
            model64 = SignedHCSN(replace(config, precision="float64"))
            model64.load_state_dict(initial)
            data64, details64 = execute(model64, x.double(), target)
            np.savez_compressed(out/"fp64_reference.npz", **data64)
            rows["fp64_reference"] = details64
            for implementation, data in raw.items():
                comparisons[implementation+"_vs_fp64"] = compare(data64, data)
        except Exception:
            failures["fp64_reference"] = traceback.format_exc()
    report = {"case": name, "neurons": n, "length": length, "batch": batch, "precision": precision,
              "implementations": rows, "failures": failures, "comparisons": comparisons,
              "warm_order": warm_order,
              "raw_files": {p.name: digest(p) for p in out.glob("*.npz")},
              "process_cpu_through_receipt": time.process_time(),
              "process_wall_from_module_entry": time.perf_counter()-ENTRY_WALL,
              "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
              "energy_joules_process": None,
              "scope": "single scalar classification-loss VJP; long cases are one full untruncated BPTT, no optimizer or dataset quality claim"}
    create(out/"RESULT.json", report)
    print(json.dumps({"case": name, "failures": list(failures), "process_cpu": report["process_cpu_through_receipt"]}), flush=True)


def launch(root):
    root.mkdir(exist_ok=False)
    cases = [(n, 12, 8, precision) for n in (8, 32, 64) for precision in ("float64", "mixed", "native32")]
    cases += [(n, length, 1, precision) for n in (8, 32, 64) for length in (128, 512) for precision in ("mixed", "native32")]
    protocol = {"schema": "hcsn-kernel-qualification-v1", "cases": cases,
        "source_hashes": source_identity(),
        "numerical_gates": {"fp64_max_abs": 1e-9, "mixed_max_abs": 2e-5,
            "native32_max_abs": 5e-4, "fp64_vjp_relative_l2": 1e-7,
            "mixed_vjp_relative_l2": 5e-5, "native32_vjp_relative_l2": .002,
            "mixed_mass": 2e-9, "native32_mass": 3e-5},
        "execution": "fresh process per case, single CPU thread, 3 balanced-order warm repeats only T12; cold calls in declared original/newton/scripted order, common imports separately measured; no labels from research datasets",
        "selection": "report all variants and failures; no replacement of the frozen training campaign"}
    create(root/"PROTOCOL.json", protocol)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    def one(spec):
        n, length, batch, precision = spec
        name = f"n{n}-t{length}-b{batch}-{precision}"
        tick = time.perf_counter()
        row = {"case": name, "returncode": None, "error": None}
        try:
            args = [sys.executable, "-m", __package__+".efficiency", "case", "--root", str(root),
                    "--neurons", str(n), "--length", str(length), "--batch", str(batch), "--precision", precision]
            with (root/(name+".log")).open("x") as log:
                child = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT,
                    env=dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"), timeout=1200)
            row["returncode"] = child.returncode
        except Exception:
            row["error"] = traceback.format_exc()
        row["wall_seconds_including_shutdown"] = time.perf_counter()-tick
        print(json.dumps(row), flush=True)
        return row
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(one, cases))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    create(root/"EXECUTION.json", {"cases": rows, "wall_seconds": time.perf_counter()-start,
        "children_cpu_seconds_including_shutdown": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "driver_cpu_seconds_through_receipt": time.process_time(), "energy_joules_process": None})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("case", "launch"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--neurons", type=int, default=8)
    parser.add_argument("--length", type=int, default=12)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--precision", default="mixed")
    args = parser.parse_args()
    if args.action == "launch":
        launch(args.root)
    else:
        case(args.root, args.neurons, args.length, args.batch, args.precision)


if __name__ == "__main__":
    main()
