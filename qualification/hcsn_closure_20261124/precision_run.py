"""Prospective N64 quality follow-up of the explicit joint-mass projection.

This does not replace the failed native32 factorial or input-VJP results. It
asks whether the already specified projection is useful on a new task sample.
The frozen base fit/test/seal implementation is reused without source changes.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import traceback

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from qualification.hcsn_smallnet_20261124.train import runtime_identity
from . import provenance as pv
from . import runner as worker
from . import variant_run as lifecycle
from .data import generate_sources, make_data as smoke_data
from .fast_kernel import FastSignedHCSN
from .mass_projection import ProjectedUniformizedHCSN


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ("fast_mixed", "projected_native32")
SEEDS = (24011, 34011, 44011)


def sources():
    manifest = ROOT/"INSTALLATION.json"
    if pv.digest(manifest) != "e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced":
        raise ValueError("unexpected frozen base installation")
    result = pv.read(manifest)
    for path, expected in result.items():
        if pv.digest(ROOT/path) != expected:
            raise ValueError("frozen base source changed: "+path)
    for name in ("variant_run.py", "fast_kernel.py", "fast_tests.py",
                 "normalized_uniformization.py", "normalization_tests.py",
                 "mass_projection.py", "projection_tests.py", "precision_run.py", "precision_tests.py"):
        path = Path(__file__).with_name(name)
        result[str(path.relative_to(ROOT))] = pv.digest(path)
    return result


def expected_protocol():
    p = pv.read(Path(__file__).with_name("protocol.json"))
    p["suite"] = "precision_followup"
    p["experiment_id"] = "HCSN-N64-PROJECTION-QUALITY-20261125-v1"
    p["slots"] = [{"id": f"n64-{variant}-s{seed}", "variant": variant,
        "neurons": 64, "precision": "mixed" if variant == "fast_mixed" else "native32",
        "boundary": "qvi", "features": "value_risk", "seed": seed}
        for variant in VARIANTS for seed in SEEDS]
    p["data"].update(train_sources=list(range(36000, 36012)),
        dev_sources=list(range(37000, 37004)), test_sources=list(range(38000, 38016)))
    p["source_hashes"], p["runtime"] = sources(), runtime_identity()
    p["holdout_policy"] = "All six attempts sealed before any new-source test generation. No tuning, retries or selection using holdout; every failure remains. Old native32 quality/VJP failures remain unchanged."
    p["claim_scope"] = "N64 paired fresh-data quality comparison only. Explicit normalized Poisson mixture and bounded joint-mass projection change the numerical operator. No general native32 derivative, long-horizon quality or same-path-law claim."
    p["comparison_gates"] = {"reference": "fast_mixed", "accuracy_margin": .02,
        "brier_margin": .02, "required_pairs": 2, "total_pairs": 3,
        "rule": "Candidate accuracy >= reference-.02 and Brier <= reference+.02 plus learning/numerical gates; engineering tolerance, not a statistical equivalence test."}
    p["factory_binding"] = "Fresh worker binds runner/pv model factory and data generator to this source; lifecycle.stage uses this module, costs include entry imports."
    return p


def prepare(root):
    p = expected_protocol()
    root.mkdir(parents=True, exist_ok=False)
    pv.create(root/"PROTOCOL.json", p)
    return p


def load(root):
    p = pv.read(root/"PROTOCOL.json")
    if p != expected_protocol():
        raise ValueError("precision roster, source, runtime or selection changed")
    return p


def factory(slot):
    variant = slot["variant"]
    if variant not in VARIANTS or slot["neurons"] != 64:
        raise ValueError("unregistered precision variant")
    precision = "mixed" if variant == "fast_mixed" else "native32"
    if slot["precision"] != precision:
        raise ValueError("precision does not match declared numerical operator")
    config = ModelConfig(neurons=64, message_mode="flow", boundary_mode="qvi",
        feature_bank="value_risk", precision=precision, backend="uniformized")
    model = FastSignedHCSN if variant == "fast_mixed" else ProjectedUniformizedHCSN
    return model(config, scripted=True, interval_cache=True)


def bind(p):
    def data(split, *, per_source, length=12, dtype=torch.float32):
        if split.startswith("smoke"):
            return smoke_data(split, per_source=per_source, length=length, dtype=dtype)
        return generate_sources(p["data"][split+"_sources"], per_source=per_source,
            length=length, dtype=dtype, namespace=p["experiment_id"]+"-"+split)
    worker.make_model, worker.make_data, pv.make_model = factory, data, factory
    lifecycle.ENTRY_WALL = ENTRY_WALL
    lifecycle.stage = stage


def stage(root, p, action, workers):
    before, started = resource.getrusage(resource.RUSAGE_CHILDREN), time.perf_counter()
    def one(slot):
        begin = time.perf_counter()
        row = {"slot": slot["id"], "returncode": None, "error": None}
        try:
            with (root/(slot["id"]+"."+action+".log")).open("x") as log:
                child = subprocess.run([sys.executable, "-m", __package__+".precision_run",
                    action, "--root", str(root), "--slot", slot["id"]],
                    stdout=log, stderr=subprocess.STDOUT, timeout=2400,
                    env=dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"))
            row["returncode"] = child.returncode
        except Exception:
            row["error"] = traceback.format_exc()
        row["launch_through_exit_wall_seconds"] = time.perf_counter()-begin
        directory = root/slot["id"]
        directory.mkdir(exist_ok=True)
        pv.create(directory/("test_parent_cost.json" if action == "test" else "parent_cost.json"), row)
        print(json.dumps({"stage": action, **row}), flush=True)
        return row
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, p["slots"]))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    pv.create(root/(action.upper()+"_EXECUTION.json"), {"rows": rows, "workers": workers,
        "wall_seconds": time.perf_counter()-started,
        "children_cpu_seconds_including_shutdown": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "energy_joules_process": None})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "fit", "test", "smoke"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--slot")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.action == "prepare":
        p = prepare(args.root)
        print(json.dumps({"protocol_sha256": pv.identity(p), "slots": len(p["slots"]), "holdout_constructed": False}))
        return 0
    p = load(args.root)
    bind(p)
    if args.action == "run":
        if not 1 <= args.workers <= 6:
            raise ValueError("bounded worker count required")
        lifecycle.run(args.root, p, args.workers)
        return 0
    slot = next(s for s in p["slots"] if s["id"] == args.slot)
    if args.action == "smoke":
        print(json.dumps(worker.fit(args.root, p, slot, smoke=True)), flush=True)
        return 0
    return lifecycle.run_worker(args.root, p, slot, args.action)


if __name__ == "__main__":
    raise SystemExit(main())
