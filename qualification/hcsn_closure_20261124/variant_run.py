"""Independent prospective dual-force and accelerated-training campaigns.

Each fresh worker explicitly binds a registered factory/data/evaluator to the
unchanged, already audited training loop. The old source files remain immutable.
All extra code and substitutions are part of this protocol's source commitment.
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
from .data import generate_sources, make_data as smoke_data
from .models import SignedHCSN


ROOT = Path(__file__).resolve().parents[2]


def sources(suite):
    manifest = ROOT/"INSTALLATION.json"
    if pv.digest(manifest) != "e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced":
        raise ValueError("unexpected frozen base installation")
    result = pv.read(manifest)
    for path, expected in result.items():
        if pv.digest(ROOT/path) != expected:
            raise ValueError("frozen base file changed: "+path)
    names = ["variant_run.py"] + (["dual_force.py", "dual_tests.py"] if suite == "dual" else ["fast_kernel.py", "fast_tests.py"])
    for name in names:
        path = Path(__file__).with_name(name)
        result[str(path.relative_to(ROOT))] = pv.digest(path)
    return result


def expected_protocol(suite):
    if suite not in ("dual", "fast"):
        raise ValueError("explicit registered suite required")
    p = pv.read(Path(__file__).with_name("protocol.json"))
    p["suite"], p["slots"] = suite, []
    p["experiment_id"] = "HCSN-"+suite.upper()+"-PROSPECTIVE-20261124-v1"
    if suite == "dual":
        for call, panic, label in ((0., 0., "zero"), (.5, 0., "call"), (0., .5, "panic"), (.5, .5, "both")):
            for seed in (19011, 29011, 39011):
                p["slots"].append({"id": f"n8-{label}-s{seed}", "variant": label,
                    "neurons": 8, "precision": "mixed", "boundary": "qvi", "features": "value_risk",
                    "seed": seed, "call_gain": call, "panic_gain": panic})
        start = 16000
        p["claim_scope"] = "Bounded lagged reference-QVI-gradient restoring force and previous-first-hit panic force actually enter drift. Not global QVI optimality, HX financial prices or a superiority claim."
    else:
        for n in (8, 32, 64):
            for variant in ("original", "fast"):
                for seed in (20011, 30011, 40011):
                    p["slots"].append({"id": f"n{n}-{variant}-s{seed}", "variant": variant,
                        "neurons": n, "precision": "mixed", "boundary": "qvi", "features": "value_risk", "seed": seed})
        start = 24000
        p["claim_scope"] = "Same-law original and accelerated mixed kernels train on common information, paired initialization/minibatches, 512 updates and dev selection. Compare complete quality/calibration/cost and retain every failure."
    p["data"].update(train_sources=list(range(start, start+12)), dev_sources=list(range(start+1000, start+1004)),
                     test_sources=list(range(start+2000, start+2016)))
    p["source_hashes"], p["runtime"] = sources(suite), runtime_identity()
    p["factory_binding"] = "Fresh worker replaces runner.make_model, runner.make_data, runner.evaluate and provenance.make_model with this exact source-bound suite. No shared process or base source changes."
    p["holdout_policy"] = "Freeze full roster, sources, code and selection before fit. Validate and seal every terminal attempt before any holdout construction; one create-only test claim per slot."
    p["comparison_gates"] = {"accuracy_margin": .02, "brier_margin": .02,
        "reference": "zero" if suite == "dual" else "original",
        "rule": "Per paired seed, accuracy>=reference-.02 and Brier<=reference+.02; at least2/3 per width, no failed pair omitted. Engineering tolerance, not statistical equivalence."}
    return p


def prepare(root, suite):
    p = expected_protocol(suite)
    root.mkdir(parents=True, exist_ok=False)
    pv.create(root/"PROTOCOL.json", p)
    return p


def load(root):
    p = pv.read(root/"PROTOCOL.json")
    if p != expected_protocol(p.get("suite")):
        raise ValueError("variant roster/data/selection/source/runtime changed after freeze")
    return p


def factory(slot):
    config = ModelConfig(neurons=slot["neurons"], message_mode="flow", boundary_mode="qvi",
                         feature_bank="value_risk", precision="mixed", backend="uniformized")
    if "call_gain" in slot:
        from .dual_force import DualForceHCSN
        return DualForceHCSN(config, call_gain=slot["call_gain"], panic_gain=slot["panic_gain"])
    if slot["variant"] == "fast":
        from .fast_kernel import FastSignedHCSN
        return FastSignedHCSN(config, scripted=True, interval_cache=True)
    return SignedHCSN(config)


def bind(p):
    def data(split, *, per_source, length=12, dtype=torch.float32):
        if split.startswith("smoke"):
            return smoke_data(split, per_source=per_source, length=length, dtype=dtype)
        return generate_sources(p["data"][split+"_sources"], per_source=per_source,
                                length=length, dtype=dtype, namespace=p["experiment_id"]+"-"+split)
    original_evaluate = worker.evaluate
    def evaluate(model, batch, **kwargs):
        metrics, logits, features = original_evaluate(model, batch, **kwargs)
        if p["suite"] == "dual":
            chunk = min(kwargs.get("chunk", 16), len(batch.y))
            metrics["maximum_chunk_state_tensor_bytes"] += chunk*model.config.neurons*model.reset_absolute.element_size()
            metrics["state_bytes_scope"] = "all six dynamic tensor fields, including previous first-hit risk; model, outputs and AD tape excluded"
        return metrics, logits, features
    worker.make_model, worker.make_data, worker.evaluate = factory, data, evaluate
    pv.make_model = factory


def check_extra_buffers(root, p):
    if p["suite"] != "dual":
        return
    for slot in p["slots"]:
        record = pv.read(root/slot["id"]/"result.json")
        if record["status"] == "failed":
            continue
        saved = torch.load(root/slot["id"]/"checkpoint.pt", map_location="cpu", weights_only=True)
        expected = factory(slot).state_dict()
        for key in ("initial_model", "selected_model", "last_model", "cpu_prefix_model"):
            for name in ("call_gain", "panic_gain", "target_margin"):
                if not torch.equal(saved[key][name], expected[name]):
                    raise ValueError("declared dual-force constants changed")


def run_worker(root, p, slot, action):
    status, error = "failed", None
    try:
        report = worker.test(root, p, slot) if action == "test" else worker.fit(root, p, slot)
        status = report["status"]
        print(json.dumps({"slot": slot["id"], "status": status, "updates": report.get("updates"),
                          "learning_gate": report.get("learning_gate")}), flush=True)
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        directory = root/slot["id"]
        directory.mkdir(exist_ok=True)
        pv.create(directory/("test_worker_cost.json" if action == "test" else "worker_cost.json"), {
            "status": status, "error": error, "wall_from_first_module_statement": time.perf_counter()-ENTRY_WALL,
            "process_cpu_through_receipt": time.process_time(),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            "energy_joules_process": None, "scope": "fresh Linux child through receipt, imports included, shutdown excluded"})
    return 0 if status in ("completed", "censored_cpu", "evaluated", "unavailable") else 1


def stage(root, p, action, workers):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    def one(slot):
        begin = time.perf_counter()
        row = {"slot": slot["id"], "returncode": None, "error": None}
        try:
            args = [sys.executable, "-m", __package__+".variant_run", action,
                    "--root", str(root), "--slot", slot["id"]]
            with (root/(slot["id"]+"."+action+".log")).open("x") as log:
                child = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=2400,
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


def run(root, p, workers):
    pv.create(root/"RUN_CLAIM.json", {"protocol_sha256": pv.identity(p), "workers": workers})
    begin, status, error = time.perf_counter(), "failed", None
    try:
        stage(root, p, "fit", workers)
        check_extra_buffers(root, p)
        pv.seal(root, p)
        pv.create(root/"TEST_CLAIM.json", {"seal_sha256": pv.digest(root/"SEAL.json"), "protocol_sha256": pv.identity(p)})
        rows = stage(root, p, "test", workers)
        if any(row["returncode"] != 0 or row["error"] is not None for row in rows):
            raise RuntimeError("test child failure; receipts retained")
        for slot in p["slots"]:
            report = pv.read(root/slot["id"]/"test_result.json")
            if report["slot"] != slot or report["status"] not in ("evaluated", "unavailable"):
                raise ValueError("incomplete terminal evaluation roster")
        status = "completed"
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        pv.create(root/"CAMPAIGN_RECEIPT.json", {"status": status, "error": error,
            "wall_seconds": time.perf_counter()-begin, "driver_cpu_through_receipt": time.process_time(),
            "energy_joules_process": None})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "fit", "test"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--suite", choices=("dual", "fast"))
    parser.add_argument("--slot")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.action == "prepare":
        p = prepare(args.root, args.suite)
        print(json.dumps({"protocol_sha256": pv.identity(p), "slots": len(p["slots"]), "holdout_constructed": False}), flush=True)
        return 0
    p = load(args.root)
    bind(p)
    if args.action == "run":
        if not 1 <= args.workers <= 9:
            raise ValueError("bounded worker count required")
        run(args.root, p, args.workers)
        return 0
    slot = next(s for s in p["slots"] if s["id"] == args.slot)
    return run_worker(args.root, p, slot, args.action)


if __name__ == "__main__":
    raise SystemExit(main())
