"""Linux operator campaign: 21 prespecified communication arms, then sealed test.

resource/ru_maxrss and the external systemd resource scope are Linux-specific.
The original fit and test implementation is reused via explicit worker-local
factory/data/evaluator substitutions, recorded in the independent protocol.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import resource
import subprocess
import sys
import traceback

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from qualification.hcsn_smallnet_20261124.train import runtime_identity
from . import provenance as primary, runner as engine
from .communication import make_communication_model
from .communication_observe import CommunicationObserver
from .data import generate_sources
from .provenance import create, digest, identity, read


HERE = Path(__file__).resolve().parent
ARMS = {
    "signed_only": ("flow", "raw", "raw", True),
    "unsigned_signed_raw": ("flow", "raw", "raw", False),
    "unsigned_signed_centered": ("flow", "raw", "centered", False),
    "unsigned_signed_centered_bounded": ("flow", "raw", "centered_bounded", False),
    "boundary_raw": ("boundary", "raw", "raw", False),
    "boundary_accumulate": ("boundary", "accumulate", "raw", False),
    "boundary_hold": ("boundary", "hold", "raw", False),
}
SOURCES = {"train": tuple(range(13000, 13012)), "dev": tuple(range(14000, 14004)),
           "test": tuple(range(15000, 15016)), "smoke_train": (12500, 12501),
           "smoke_dev": (12600, 12601)}
OWN_FILES = ("communication.py", "communication_observe.py", "communication_run.py", "communication_tests.py")


def sources():
    return {**primary.sources(), **{__package__+"."+name: digest(HERE/name) for name in OWN_FILES}}


def make_model(slot):
    channel, control, unsigned, signed_only = ARMS[slot["arm"]]
    model = make_communication_model(ModelConfig(neurons=32, boundary_mode="qvi",
        feature_bank="value_risk", precision="mixed", backend="uniformized", message_mode=channel),
        control_mode=control, unsigned_mode=unsigned, unsigned_scale=1.)
    if signed_only:
        model.synaptic_mask[:, 32:64] = 0
    return model


def accounting(model):
    n = model.config.neurons
    mode = (1., 0., 0.) if model.config.message_mode == "boundary" else (0., 1., 1.)
    mask = model.synaptic_mask*model.synaptic_mask.new_tensor(mode).repeat_interleave(n)[None]
    active = int(torch.count_nonzero(mask))
    trainable = sum(v.numel() for v in model.parameters() if v.requires_grad)
    return {"total_parameters": sum(v.numel() for v in model.parameters()),
            "requires_grad_parameters": trainable, "structurally_active_recurrent_parameters": active,
            "trainable_minus_masked_recurrent": trainable-model.recurrent.weight.numel()+active,
            "scope": "Exact structural masks; adding unsigned also adds an active trainable branch. No equal effective-capacity claim."}


def make_data(split, *, per_source=48, length=12):
    return generate_sources(SOURCES[split], per_source=per_source, length=length,
                            namespace="communication-v1-"+split)


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    base = read(HERE/"protocol.json")
    p = {"experiment_id": "HCSN-COMMUNICATION-PROSPECTIVE-20261125-v1",
         "base_commit": base["base_commit"], "base_protocol_sha256": digest(HERE/"protocol.json"),
         "slots": [{"id": "n32-"+arm+"-s"+str(seed), "arm": arm, "neurons": 32,
                    "boundary": "qvi", "features": "value_risk", "precision": "mixed", "seed": seed,
                    "family": "communication"} for arm in ARMS for seed in (18011, 28011, 38011)],
         "arms": {name: dict(zip(("message_mode", "control_mode", "unsigned_mode", "signed_only"), fields))
                  for name, fields in ARMS.items()}, "unsigned_scale": 1.,
         "data": {**{key+"_sources": list(value) for key, value in SOURCES.items()},
                  "train_per_source": 48, "dev_per_source": 48, "test_per_source": 64, "length": 12},
         "training": base["training"],
         "validation": {key: base["validation"][key] for key in
                        ("min_final_accuracy", "min_gain_over_initial", "min_gain_over_prelate", "min_seed_fraction", "max_mixed_mass_error")},
         "holdout_policy": "All 21 terminal attempts and complete checkpoint states are globally sealed before any test construction. All failures remain in the three-seed denominator. New source identities in the existing synthetic generator family; no new real-world domain claim. No test tuning, retries or best-arm selection.",
         "comparison": "First four arms have boundary communication disabled; unsigned addition/centering/bounding are prespecified contrasts. Last three are boundary-only and compare causal raw/accumulate/hold input-drive paths. input_mark always reads raw observed input. Extra control state is explicit and retained across continuation.",
         "factory_patch": "Fresh worker context replaces runner.make_model, make_data, parameter_accounting, forward_batch, evaluate and check_seal; original runner.fit/test bodies remain byte-identical. No train/test labels enter preprocessing or detached observers.",
         "measurement": "Detached per-channel moments, preactivation saturation and preclip recurrent gradient norms. Observer CPU is included in every update and complete worker cost. Reference centering is the nominal single-neuron stationary event rate, with no data-fitted mean.",
         "cost_policy": base["cost_policy"], "capacity_policy": "Report exact active mask counts. Unsigned adds parameters; held/accumulated inputs add explicit memory. No equality of functional capacity or deployment time is assumed.",
         "source_hashes": sources(), "runtime": runtime_identity()}
    create(root/"PROTOCOL.json", p)
    return p


def load(root):
    p = read(root/"PROTOCOL.json")
    if p["source_hashes"] != sources() or p["runtime"] != runtime_identity():
        raise ValueError("communication executable source or runtime changed")
    expected = {(arm, seed) for arm in ARMS for seed in (18011, 28011, 38011)}
    if ({(s["arm"], s["seed"]) for s in p["slots"]} != expected or len(p["slots"]) != 21
            or any(s["neurons"] != 32 or s["boundary"] != "qvi" or s["features"] != "value_risk"
                   or s["precision"] != "mixed" for s in p["slots"])):
        raise ValueError("communication roster changed")
    return p


def validate(directory, p, slot):
    original = primary.make_model
    try:
        primary.make_model = make_model
        primary.validate_record(directory, p, slot)
    finally:
        primary.make_model = original
    record = read(directory/"result.json")
    if record["status"] in ("completed", "censored_cpu"):
        saved = torch.load(directory/"checkpoint.pt", map_location="cpu", weights_only=True)
        expected = make_model(slot).unsigned_reference
        for key in ("initial_model", "selected_model", "last_model", "cpu_prefix_model"):
            if not torch.equal(saved[key]["unsigned_reference"], expected):
                raise ValueError("nominal unsigned reference changed")
    mechanism = read(directory/"MECHANISM_FIT.json")
    if mechanism["slot"] != slot or mechanism["protocol_sha256"] != identity(p):
        raise ValueError("mechanism receipt identity changed")


def seal(root, p):
    rows = {}
    for slot in p["slots"]:
        directory = root/slot["id"]
        validate(directory, p, slot)
        names = ("result.json", "worker_cost.json", "history.json", "checkpoint.pt", "parent_cost.json", "MECHANISM_FIT.json")
        rows[slot["id"]] = {name: digest(directory/name) for name in names if (directory/name).exists()}
    create(root/"SEAL.json", {"schema": "hcsn-communication-seal-v1", "protocol_sha256": identity(p), "attempts": rows})


def check_seal(root, p):
    value = read(root/"SEAL.json")
    if value["protocol_sha256"] != identity(p) or set(value["attempts"]) != {s["id"] for s in p["slots"]}:
        raise ValueError("incomplete or foreign communication seal")
    for slot in p["slots"]:
        for name, expected in value["attempts"][slot["id"]].items():
            if digest(root/slot["id"]/name) != expected:
                raise ValueError("sealed communication artifact changed")
        validate(root/slot["id"], p, slot)
    return value


@contextmanager
def worker_context(action, observers):
    names = ("make_model", "make_data", "parameter_accounting", "forward_batch", "evaluate", "check_seal")
    original = {key: getattr(engine, key) for key in names}
    evaluation_index = 0

    def factory(slot):
        model = make_model(slot)
        observer = CommunicationObserver(model.config.neurons)
        observer.attach(model)
        observers.append(observer)
        return model

    def forward(model, batch):
        model.observer.phase = "training"
        return original["forward_batch"](model, batch)

    def evaluate(model, batch, **kwargs):
        nonlocal evaluation_index
        phase = ("test_selected", "test_initial", "test_cpu_prefix")[evaluation_index] if action == "test" else "development"
        evaluation_index += 1
        model.observer.phase = phase
        metrics, logits, features = original["evaluate"](model, batch, **kwargs)
        group = model.observer.group()
        metrics["maximum_complete_chunk_state_tensor_bytes"] = group["maximum_complete_state_tensor_bytes"]
        metrics["additional_control_state_tensor_bytes"] = group["maximum_control_state_tensor_bytes"]
        metrics["complete_state_bytes_scope"] = "five physical fields plus pending and held input tensors; AD tape and model excluded"
        return metrics, logits, features

    try:
        for key, value in zip(names, (factory, make_data, accounting, forward, evaluate, check_seal)):
            setattr(engine, key, value)
        yield
    finally:
        for key, value in original.items():
            setattr(engine, key, value)


def worker(root, p, slot, action):
    observers, status, error = [], "failed", None
    try:
        with worker_context(action, observers):
            result = engine.test(root, p, slot) if action == "test" else engine.fit(root, p, slot, action == "smoke")
        status = result["status"]
        print({key: result.get(key) for key in ("slot", "status", "updates", "selected_step", "learning_gate", "error")}, flush=True)
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        directory = root/slot["id"]
        directory.mkdir(exist_ok=True)
        create(directory/("MECHANISM_TEST.json" if action == "test" else "MECHANISM_FIT.json"),
               {"slot": slot, "protocol_sha256": identity(p), "models": [o.export() for o in observers]})
        create(directory/("test_worker_cost.json" if action == "test" else "worker_cost.json"),
               {"status": status, "error": error, "wall_from_first_module_statement": time.perf_counter()-ENTRY_WALL,
                "process_cpu_through_receipt": time.process_time(),
                "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                "energy_joules_process": None, "scope": "Linux fresh worker, imports and observers included, shutdown excluded"})
    return 0 if status in ("completed", "censored_cpu", "evaluated", "unavailable") else 1


def stage(root, p, action, workers, slots=None):
    wall, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)

    def one(slot):
        start = time.perf_counter()
        row = {"slot": slot["id"], "returncode": None, "error": None}
        try:
            command = [sys.executable, "-m", __package__+".communication_run", "worker", "--stage", action,
                       "--root", str(root), "--slot", slot["id"]]
            env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
            with (root/(slot["id"]+"."+action+".log")).open("x") as log:
                child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=3000, check=False)
            row["returncode"] = child.returncode
        except Exception:
            row["error"] = traceback.format_exc()
        finally:
            row["launch_through_exit_wall_seconds"] = time.perf_counter()-start
            directory = root/slot["id"]
            directory.mkdir(exist_ok=True)
            create(directory/("test_parent_cost.json" if action == "test" else "parent_cost.json"), row)
        print({"stage": action, **row}, flush=True)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, p["slots"] if slots is None else slots))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"stage": action, "workers": workers, "attempts": rows, "wall_seconds": time.perf_counter()-wall,
               "driver_cpu_seconds": time.process_time()-cpu,
               "children_cpu_seconds_including_shutdown": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
               "energy_joules_process": None}
    create(root/(action.upper()+"_EXECUTION.json"), receipt)
    return receipt


def run(root, p, workers):
    create(root/"RUN_CLAIM.json", {"protocol_sha256": identity(p), "workers": workers})
    wall, cpu, status, error = time.perf_counter(), time.process_time(), "failed", None
    try:
        stage(root, p, "fit", workers)
        seal(root, p)
        create(root/"TEST_CLAIM.json", {"seal_sha256": digest(root/"SEAL.json"), "protocol_sha256": identity(p)})
        tests = stage(root, p, "test", workers)
        if any(row["returncode"] != 0 or row["error"] is not None for row in tests["attempts"]):
            raise RuntimeError("test process failed; preserved receipts prevent a complete claim")
        results = [read(root/slot["id"]/"test_result.json") for slot in p["slots"]]
        if any(row["slot"] != slot or row["status"] not in ("evaluated", "unavailable") for row, slot in zip(results, p["slots"])):
            raise ValueError("missing or foreign terminal test result")
        create(root/"FINAL_RESULTS.json", {"protocol_sha256": identity(p), "seal_sha256": digest(root/"SEAL.json"), "results": results})
        status = "completed"
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        create(root/"CAMPAIGN_RECEIPT.json", {"status": status, "error": error,
            "wall_seconds": time.perf_counter()-wall, "driver_cpu_seconds": time.process_time()-cpu,
            "energy_joules_process": None, "scope": "driver only; stages separately report full child CPU, do not add nested body cost"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "smoke", "worker"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stage", choices=("fit", "test", "smoke"))
    parser.add_argument("--slot")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.workers <= 5:
        raise ValueError("communication worker count must lie in 1..5")
    torch.set_num_threads(1)
    p = prepare(args.root) if args.action == "prepare" else load(args.root)
    if args.action == "prepare":
        print({"protocol_sha256": identity(p), "slots": len(p["slots"]), "source_files": len(p["source_hashes"]), "test_constructed": False}, flush=True)
    elif args.action == "run":
        run(args.root, p, args.workers)
    elif args.action == "smoke":
        receipt = stage(args.root, p, "smoke", args.workers, [s for s in p["slots"] if s["seed"] == 18011])
        return 0 if all(r["returncode"] == 0 and r["error"] is None for r in receipt["attempts"]) else 1
    else:
        return worker(args.root, p, next(s for s in p["slots"] if s["id"] == args.slot), args.stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
