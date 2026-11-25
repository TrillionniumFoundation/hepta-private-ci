"""Frozen numerical follow-up for known FP32 mass and input-VJP failures."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import numpy as np
import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .efficiency import execute, compare
from .mass_projection import ProjectedUniformizedHCSN
from .models import SignedHCSN
from .normalization_probe import source_identity as prior_sources
from .normalized_uniformization import NormalizedUniformizedHCSN
from .provenance import create, digest, read


def sources():
    folder = Path(__file__).parent
    root = folder.parents[1]
    return {**prior_sources(), **{str((folder/name).relative_to(root)): digest(folder/name)
        for name in ("mass_projection.py", "projection_tests.py", "projection_probe.py")}}


def case(root, spec):
    protocol = read(root/"PROTOCOL.json")
    if sources() != protocol["source_hashes"] or spec not in protocol["cases"]:
        raise ValueError("unregistered projection numerical probe")
    n, length, batch = spec
    out = root/f"n{n}-t{length}-b{batch}-native32"
    out.mkdir(exist_ok=False)
    torch.set_num_threads(1); torch.manual_seed(74123+n+length)
    cfg = ModelConfig(neurons=n, message_mode="flow", backend="uniformized", precision="native32")
    original = SignedHCSN(cfg)
    initial = {k: v.detach().clone() for k, v in original.state_dict().items()}
    x, labels = torch.randn(length, batch, 6)*.3, torch.arange(batch) % 2
    raw, details, errors = {}, {}, {}
    for name, factory in (("normalized", NormalizedUniformizedHCSN),
                          ("projected", ProjectedUniformizedHCSN),
                          ("fp64_reference", SignedHCSN)):
        model = None
        try:
            model = (factory(replace(cfg, precision="float64")) if name == "fp64_reference"
                     else factory(cfg, scripted=True))
            model.load_state_dict(initial)
            data, info = execute(model, x.double() if name == "fp64_reference" else x, labels)
            raw[name], details[name] = data, info
            np.savez_compressed(out/(name+".npz"), **data)
        except Exception:
            errors[name] = {"traceback": traceback.format_exc(),
                            "diagnostics": getattr(model, "last_diagnostics", {})}
    comparisons = {name+"_vs_fp64": compare(raw["fp64_reference"], data)
        for name, data in raw.items() if name != "fp64_reference" and "fp64_reference" in raw}
    create(out/"RESULT.json", {"case": out.name, "neurons": n, "length": length,
        "batch": batch, "precision": "native32", "implementations": details,
        "failures": errors, "comparisons": comparisons,
        "raw_files": {p.name: digest(p) for p in out.glob("*.npz")},
        "process_cpu_through_receipt": time.process_time(),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        "scope": "parameter/input scalar-loss VJP, not ambient initial-population Jacobian; joint numerical projection is explicit"})
    print(json.dumps({"case": out.name, "failed_implementations": list(errors)}), flush=True)


def launch(root):
    root.mkdir(exist_ok=False)
    cases = [[n, 12, 8] for n in (8, 32, 64)]+[[n, 2048, 1] for n in (8, 32, 64)]+[[64, 512, 1]]
    create(root/"PROTOCOL.json", {"schema": "hcsn-bounded-joint-projection-v1",
        "source_hashes": sources(), "cases": cases, "gates": {"native32_max_abs": 5e-4,
        "native32_vjp_relative_l2": .002, "native32_mass": 3e-5,
        "raw_local_mass_projection_admission": 2e-6},
        "rationale": "Follow-up of known 2048-step mass failure and N32T12 input-VJP failure; old failures remain",
        "policy": "report all seven cases and all failures; no task data, no changed old gates; complete BPTT; not a universal FP32 guarantee"})
    start, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    def one(spec):
        name = f"n{spec[0]}-t{spec[1]}-b{spec[2]}"
        tick = time.perf_counter()
        row = {"case": name, "returncode": None, "error": None}
        try:
            with (root/(name+".log")).open("x") as log:
                child = subprocess.run([sys.executable, "-m", __package__+".projection_probe",
                    "case", "--root", str(root), "--spec", json.dumps(spec)],
                    stdout=log, stderr=subprocess.STDOUT, timeout=1200,
                    env=dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"))
            row["returncode"] = child.returncode
        except Exception:
            row["error"] = traceback.format_exc()
        row["complete_wall_seconds"] = time.perf_counter()-tick
        print(json.dumps(row), flush=True)
        return row
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(one, cases))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    create(root/"EXECUTION.json", {"cases": rows, "wall_seconds": time.perf_counter()-start,
        "children_cpu_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "energy_joules_process": None})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("case", "launch"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spec", type=json.loads)
    args = parser.parse_args()
    if args.action == "launch":
        launch(args.root)
    else:
        case(args.root, args.spec)
