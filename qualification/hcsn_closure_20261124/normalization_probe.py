"""Prospective numerical probes; never construct research task datasets."""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import traceback

import numpy as np
import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .efficiency import compare, execute
from .fast_kernel import FastSignedHCSN
from .models import SignedHCSN
from .normalized_uniformization import NormalizedUniformizedHCSN
from .provenance import create, digest, read


REPO_ROOT = Path(__file__).resolve().parents[2]


def source_identity():
    base_path = REPO_ROOT/"INSTALLATION.json"
    if digest(base_path) != "e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced":
        raise ValueError("unexpected immutable base")
    base = read(base_path)
    for name, expected in base.items():
        if digest(REPO_ROOT/name) != expected:
            raise ValueError("base source changed: "+name)
    files = ("efficiency.py", "fast_kernel.py", "normalized_uniformization.py",
             "normalization_tests.py", "normalization_probe.py")
    return {**base, **{str(Path(__file__).relative_to(REPO_ROOT).with_name(name)):
                      digest(Path(__file__).with_name(name)) for name in files}}


def run_case(root, spec):
    protocol = read(root/"PROTOCOL.json")
    if protocol["source_hashes"] != source_identity() or spec not in protocol["cases"]:
        raise ValueError("unregistered case or changed source")
    n, length, batch, precision = spec
    name = f"n{n}-t{length}-b{batch}-{precision}"
    out = root/name
    out.mkdir(exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(74123+n+length)
    config = ModelConfig(neurons=n, message_mode="flow", backend="uniformized",
                         precision=precision)
    reference = SignedHCSN(config)
    initial = {k: v.detach().clone() for k, v in reference.state_dict().items()}
    x = torch.randn(length, batch, 6, dtype=reference.input_drive.weight.dtype)*.3
    target = torch.arange(batch, dtype=torch.long) % 2
    raw, rows, errors, models, orders = {}, {}, {}, {}, []
    for implementation, factory in (("qualified_fast", FastSignedHCSN),
                                    ("normalized", NormalizedUniformizedHCSN)):
        try:
            model = factory(config, scripted=True)
            model.load_state_dict(initial)
            data, details = execute(model, x, target)
            rows[implementation] = {"cold": details, "repeats": []}
            raw[implementation], models[implementation] = data, model
            np.savez_compressed(out/(implementation+".npz"), **data)
        except Exception:
            errors[implementation] = traceback.format_exc()
    if length == 12:
        for repeat in range(3):
            names = ("qualified_fast", "normalized")
            for implementation in names[repeat % 2:]+names[:repeat % 2]:
                if implementation not in models:
                    continue
                try:
                    data, details = execute(models[implementation], x, target)
                    details["cold_vs_warm"] = compare(raw[implementation], data)
                    rows[implementation]["repeats"].append(details)
                    orders.append(implementation)
                except Exception:
                    errors[implementation+"_warm_"+str(repeat)] = traceback.format_exc()
    try:
        reference64 = SignedHCSN(replace(config, precision="float64"))
        reference64.load_state_dict(initial)
        data64, details64 = execute(reference64, x.double(), target)
        raw["fp64_reference"] = data64
        rows["fp64_reference"] = details64
        np.savez_compressed(out/"fp64_reference.npz", **data64)
    except Exception:
        errors["fp64_reference"] = traceback.format_exc()
    comparisons = {name+"_vs_fp64": compare(raw["fp64_reference"], data)
        for name, data in raw.items() if name != "fp64_reference" and "fp64_reference" in raw}
    if "normalized" in raw and "qualified_fast" in raw:
        comparisons["normalized_vs_qualified_fast"] = compare(raw["qualified_fast"], raw["normalized"])
    report = {"case": name, "neurons": n, "length": length, "batch": batch,
        "precision": precision, "implementations": rows, "failures": errors,
        "comparisons": comparisons, "warm_order": orders,
        "raw_files": {p.name: digest(p) for p in out.glob("*.npz")},
        "process_cpu_through_receipt": time.process_time(),
        "process_wall_from_module_entry": time.perf_counter()-ENTRY_WALL,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        "energy_joules_process": None,
        "scope": "all parameter and input VJP of one declared scalar loss, full BPTT; no task quality evidence"}
    # Use the immutable case directory name; comprehensions must not name it.
    report["case"] = out.name
    create(out/"RESULT.json", report)
    print(json.dumps({"case": out.name, "failures": list(errors)}), flush=True)


def launch(root):
    root.mkdir(exist_ok=False)
    cases = [[n, 12, 8, precision] for n in (8, 32, 64)
             for precision in ("float64", "mixed", "native32")]
    cases += [[n, length, 1, precision] for n in (8, 32, 64)
              for length in (128, 512) for precision in ("mixed", "native32")]
    cases += [[n, 2048, 1, "native32"] for n in (8, 32, 64)]
    protocol = {"schema": "hcsn-conditional-poisson-numerical-v1", "cases": cases,
        "source_hashes": source_identity(),
        "gates": {"fp64_max_abs": 1e-9, "mixed_max_abs": 2e-5,
            "native32_max_abs": 5e-4, "fp64_vjp_relative_l2": 1e-7,
            "mixed_vjp_relative_l2": 5e-5, "native32_vjp_relative_l2": .002,
            "mixed_mass": 2e-9, "native32_mass": 3e-5},
        "operator": "conditional truncated Poisson mixture, not state renormalization",
        "probability_exact_arithmetic_bound": "2*substeps*Poisson_tail for stochastic action; roundoff/VJP excluded",
        "reward_single_step_exact_arithmetic_bound": "max_reward/rate * (order*tail + mean*Pr[N>=order]); propagate separately across substeps",
        "execution": "two single-thread child workers; fresh process per case; all failures retained; full untruncated BPTT",
        "selection": "report every case; frozen main, communication, force and fast training remain unchanged"}
    create(root/"PROTOCOL.json", protocol)
    before, start = resource.getrusage(resource.RUSAGE_CHILDREN), time.perf_counter()
    def one(spec):
        name = f"n{spec[0]}-t{spec[1]}-b{spec[2]}-{spec[3]}"
        tick = time.perf_counter()
        row = {"case": name, "returncode": None, "error": None}
        try:
            args = [sys.executable, "-m", __package__+".normalization_probe", "case",
                    "--root", str(root), "--spec", json.dumps(spec)]
            with (root/(name+".log")).open("x") as log:
                child = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT,
                    env=dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                             OPENBLAS_NUM_THREADS="1"), timeout=1200)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("case", "launch"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spec", type=json.loads)
    args = parser.parse_args()
    if args.action == "launch":
        launch(args.root)
    else:
        run_case(args.root, args.spec)
