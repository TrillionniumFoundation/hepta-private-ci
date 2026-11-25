"""Prospective boundary/signed/joint communication with one frozen fast core.

Only the recurrent channel mask changes. The unsigned channel is disabled in
every arm. A fresh worker binds the existing audited train/test loop; no frozen
parent, runner or former communication experiment is modified.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
from .fast_kernel import FastSignedHCSN


ROOT = Path(__file__).resolve().parents[2]
CHANNELS = ("boundary_only", "signed_only", "boundary_signed")
FAST_SHA256 = "a92d7cc45af0ccf1e1c2629ee9fe8ef1d4b0bc6dba335bbdc53cd909c42d80b3"


class JointHCSN(FastSignedHCSN):
    def __init__(self, config, channel):
        if channel not in CHANNELS or config.message_mode != "full":
            raise ValueError("explicit full-mode boundary/signed channel required")
        # SignedHCSN's constructor requires flow mode. This temporary config
        # changes neither initialization nor physical dynamics; restore the
        # SmallHCSN two-role base mask before applying the declared channels.
        super().__init__(replace(config, message_mode="flow"), scripted=True, interval_cache=True)
        self.config = config
        n, h = config.neurons, config.neurons//2
        base = torch.ones(n, n, dtype=self.synaptic_mask.dtype, device=self.synaptic_mask.device)
        base[:h, h:] = 0
        self.synaptic_mask.copy_(base.repeat(1, 3))
        self.synaptic_mask[:, n:2*n] = 0
        if channel == "signed_only":
            self.synaptic_mask[:, :n] = 0
        if channel == "boundary_only":
            self.synaptic_mask[:, 2*n:] = 0


def factory(slot):
    return JointHCSN(ModelConfig(neurons=slot["neurons"], boundary_mode="qvi",
        feature_bank="value_risk", feature_normalization="none", precision="mixed",
        backend="uniformized", message_mode="full"), slot["variant"])


def parameter_accounting(model):
    total = sum(v.numel() for v in model.parameters())
    trainable = sum(v.numel() for v in model.parameters() if v.requires_grad)
    active = int(torch.count_nonzero(model.synaptic_mask))
    masked = model.recurrent.weight.numel()-active
    return {"total_parameters": total, "requires_grad_parameters": trainable,
        "structurally_active_recurrent_parameters": active,
        "trainable_minus_masked_recurrent": trainable-masked,
        "scope": "Exact full-mode channel mask count; joint has more active recurrent parameters, not an equal effective-capacity claim."}


def sources():
    manifest = ROOT/"INSTALLATION.json"
    if pv.digest(manifest) != "e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced":
        raise ValueError("unexpected immutable base installation")
    result = pv.read(manifest)
    for path, expected in result.items():
        if pv.digest(ROOT/path) != expected:
            raise ValueError("frozen base source changed: "+path)
    for name in ("fast_kernel.py", "joint_run.py", "joint_tests.py"):
        path = Path(__file__).with_name(name)
        result[str(path.relative_to(ROOT))] = pv.digest(path)
    if pv.digest(Path(__file__).with_name("fast_kernel.py")) != FAST_SHA256:
        raise ValueError("unqualified fast kernel")
    return result


def expected_protocol():
    p = pv.read(Path(__file__).with_name("protocol.json"))
    p["experiment_id"] = "HCSN-BOUNDARY-SIGNED-JOINT-PROSPECTIVE-20261125-v1"
    p["suite"] = "boundary_signed_joint"
    p["slots"] = [{"id": f"n32-{channel}-s{seed}", "variant": channel,
        "neurons": 32, "boundary": "qvi", "features": "value_risk", "precision": "mixed",
        "seed": seed} for channel in CHANNELS for seed in (22011, 32011, 42011)]
    p["data"].update(train_sources=list(range(33000, 33012)), dev_sources=list(range(34000, 34004)),
                     test_sources=list(range(35000, 35016)))
    p["source_hashes"], p["runtime"] = sources(), runtime_identity()
    p["claim_scope"] = "Three within-family communication masks on N32 mixed QVI/value-risk raw features; unsigned always disabled; no overwrite or pooling of earlier failed boundary tests."
    p["factory_binding"] = "Fresh process binds runner.make_model, make_data, parameter_accounting and provenance.make_model; unchanged training/evaluation source."
    p["holdout_policy"] = "All nine terminal attempts, four states per checkpoint and exact masks validated and sealed before any test construction; once-only test claims; all failures retained."
    p["comparison_gates"] = {"reference": "signed_only", "accuracy_margin": .02, "brier_margin": .02,
        "rule": "Paired seed accuracy>=signed-.02 and Brier<=signed+.02; at least2/3. Descriptive engineering tolerance, not superiority or statistical equivalence."}
    p["capacity_policy"] = "Same allocated tensors/initialization and scalar task, but joint has twice the active recurrent entries of either single channel. Report exact mask counts and actual gradients; no effective-capacity equality."
    p["resource_policy"] = {"workers": 6, "threads_per_worker": 1, "aggregate_cpu_percent_cap": 600,
        "aggregate_memory_limit_bytes": 6*1024**3, "stage_child_wall_timeout_seconds": 2400}
    return p


def prepare(root):
    p = expected_protocol()
    root.mkdir(parents=True, exist_ok=False)
    pv.create(root/"PROTOCOL.json", p)
    return p


def load(root):
    p = pv.read(root/"PROTOCOL.json")
    if p != expected_protocol():
        raise ValueError("frozen joint protocol/source/runtime changed")
    return p


def bind(p):
    def data(split, *, per_source, length=12, dtype=torch.float32):
        if split.startswith("smoke"):
            return smoke_data(split, per_source=per_source, length=length, dtype=dtype)
        return generate_sources(p["data"][split+"_sources"], per_source=per_source,
            length=length, dtype=dtype, namespace=p["experiment_id"]+"-"+split)
    worker.make_model, worker.make_data, worker.parameter_accounting = factory, data, parameter_accounting
    pv.make_model = factory


def check_checkpoint_masks(saved, slot):
    expected = factory(slot).state_dict()
    for state_name in ("initial_model", "selected_model", "last_model", "cpu_prefix_model"):
        for name in ("synaptic_mask", "reset_absolute", "fixed_boundary"):
            if not torch.equal(saved[state_name][name], expected[name]):
                raise ValueError("checkpoint channel/physical buffer changed: "+state_name+"/"+name)


def check_all_masks(root, p):
    for slot in p["slots"]:
        directory = root/slot["id"]
        if pv.read(directory/"result.json")["status"] == "failed":
            continue
        saved = torch.load(directory/"checkpoint.pt", map_location="cpu", weights_only=True)
        check_checkpoint_masks(saved, slot)


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
            "energy_joules_process": None, "scope": "fresh Linux child through receipt; imports included, shutdown excluded"})
    return 0 if status in ("completed", "censored_cpu", "evaluated", "unavailable") else 1


def stage(root, p, action, workers):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    def one(slot):
        begin = time.perf_counter()
        row = {"slot": slot["id"], "returncode": None, "error": None}
        try:
            args = [sys.executable, "-m", __package__+".joint_run", action,
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
        check_all_masks(root, p)
        pv.seal(root, p)
        pv.create(root/"TEST_CLAIM.json", {"seal_sha256": pv.digest(root/"SEAL.json"), "protocol_sha256": pv.identity(p)})
        rows = stage(root, p, "test", workers)
        if any(row["returncode"] != 0 or row["error"] is not None for row in rows):
            raise RuntimeError("joint test child failure; all receipts retained")
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
    parser.add_argument("--slot")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.action == "prepare":
        p = prepare(args.root)
        print(json.dumps({"protocol_sha256": pv.identity(p), "slots": len(p["slots"]), "holdout_constructed": False}), flush=True)
        return 0
    p = load(args.root)
    bind(p)
    if args.action == "run":
        if args.workers != 6:
            raise ValueError("frozen six-worker campaign required")
        run(args.root, p, args.workers)
        return 0
    slot = next(s for s in p["slots"] if s["id"] == args.slot)
    return run_worker(args.root, p, slot, args.action)


if __name__ == "__main__":
    raise SystemExit(main())
