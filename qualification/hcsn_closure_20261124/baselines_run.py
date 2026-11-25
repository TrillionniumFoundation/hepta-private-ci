"""Separate source-bound workers for conventional baselines and rule programs.

Conventional training reuses the frozen training function with three explicit
process-local dependencies. No source file or main-campaign process is patched.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

try:
    import resource
except ImportError:
    resource = None

import torch
import numpy as np

from . import baselines, programs, runner
from . import provenance as original
from qualification.hcsn_smallnet_20261124.train import runtime_identity
from qualification.hcsn_smallnet_20261124.train import evaluate as evaluate_hcsn
from .data import generate_sources


HERE = Path(__file__).resolve().parent


def implementation():
    return {**original.sources(), **{__package__+"."+name: original.digest(HERE/(name+".py"))
            for name in ("baselines", "baselines_run", "programs")},
            **{__package__+".old_"+name: original.digest(HERE.parent/"hcsn_smallnet_20261124"/(name+".py"))
               for name in ("editing", "transfer_suite")}}


def freeze(root, parent_root, suite):
    torch.set_num_threads(1)
    parent = original.load(parent_root)
    root.mkdir(parents=True, exist_ok=False)
    if suite == "programs":
        p = programs.default_protocol()
    else:
        slots = []
        for kind, widths in (("GRU", (4, 16, 32)), ("surrogate_LIF", (9, 30, 58)),
                             ("causal_Transformer", (3, 11, 21))):
            for n, width, target in zip((8, 32, 64), widths, (154, 1186, 3906)):
                for seed in (17011, 27011, 37011):
                    slots.append({"id": f"{kind}-n{n}-s{seed}", "kind": kind, "width": width,
                                  "reference_neurons": n, "target_parameters": target, "seed": seed})
        p = {"schema": "hcsn-conventional-baselines-v1", "slots": slots,
             "data": parent["data"], "training": parent["training"], "validation": parent["validation"],
             "training_adapter": ["runner.make_model=baselines.make_model",
                                  "runner.parameter_accounting=baselines.parameter_accounting",
                                  "runner.evaluate=baselines.evaluate"],
             "holdout": "all 27 baseline candidates and all 63 HCSN candidates sealed before construction",
             "capacity_scope": "approximate parameter matching; zero initial state and architecture/dtype/operation differences retained"}
        p["long_delay_stress"] = {"panels": [
            {"sources": list(range(30000, 30008)), "length": 76, "delay": 64},
            {"sources": list(range(31000, 31008)), "length": 140, "delay": 128}],
            "per_source": 16, "parents": [f"n{n}-s{s}" for n in (8, 32, 64) for s in (17011, 27011, 37011)],
            "min_final_accuracy": .8, "min_gain_over_prelate": .1,
            "gate": "both training seals and all main/baseline short-test terminal records before construction",
            "scope": "fixed T12-trained selected models; new delay/clock distribution; no training or selection"}
    p.update(suite=suite, parents_root=str(parent_root.resolve()),
             parent_protocol_sha256=original.identity(parent), implementation=implementation(), runtime=runtime_identity())
    original.create(root/"PROTOCOL.json", p)
    return p


def load(root):
    p = original.read(root/"PROTOCOL.json")
    if p["implementation"] != implementation() or p["runtime"] != runtime_identity():
        raise ValueError("changed companion source or runtime")
    parent = original.load(Path(p["parents_root"]))
    if original.identity(parent) != p["parent_protocol_sha256"]:
        raise ValueError("parent protocol changed")
    return p


def parent_slot(parent, parent_id):
    candidates = [s for s in parent["slots"] if s["boundary"] == "qvi" and s["features"] == "value_risk"
                  and s["precision"] == "mixed" and f'n{s["neurons"]}-s{s["seed"]}' == parent_id]
    if len(candidates) != 1:
        raise ValueError("one declared QVI/value-risk/mixed parent required")
    return candidates[0]


def load_parent(p, parent_id):
    parent_root = Path(p["parents_root"]); parent = original.load(parent_root)
    slot = parent_slot(parent, parent_id); directory = parent_root/slot["id"]
    original.validate_record(directory, parent, slot)
    record = original.read(directory/"result.json")
    saved = torch.load(directory/"checkpoint.pt", map_location="cpu", weights_only=True)
    if saved["slot"] != slot or saved["protocol_sha256"] != original.identity(parent):
        raise ValueError("parent checkpoint identity mismatch")
    model = original.make_model(slot); model.load_state_dict(saved["selected_model"])
    info = {"parent_id": parent_id, "slot": slot, "selected_step": record["selected_step"],
            "updates": record["updates"], "status": record["status"],
            "input_sha256": {name: original.digest(directory/name) for name in
                ("checkpoint.pt", "result.json", "worker_cost.json", "parent_cost.json")},
            "inherited_training_cost": record["cost"],
            "inherited_worker_cost": original.read(directory/"worker_cost.json"),
            "inherited_launch_cost": original.read(directory/"parent_cost.json")}
    return model, info


def validate_baseline(directory, p, slot):
    record = original.read(directory/"result.json")
    worker = original.read(directory/"fit_worker_cost.json")
    launched = original.read(directory/"fit_launch_cost.json")
    if record["slot"] != slot or record["protocol_sha256"] != original.identity(p) or record["smoke"] is not False:
        raise ValueError("baseline result identity mismatch")
    if worker["status"] != record["status"] or worker["error"] is not None:
        raise ValueError("baseline worker did not publish a normal terminal result")
    if launched["returncode"] != (1 if record["status"] == "failed" else 0):
        raise ValueError("baseline terminal status differs from launcher")
    if record["checkpoint_sha256"] is not None:
        if original.digest(directory/"checkpoint.pt") != record["checkpoint_sha256"]:
            raise ValueError("baseline checkpoint bytes changed")
        saved = torch.load(directory/"checkpoint.pt", weights_only=True, map_location="cpu")
        if saved["slot"] != slot or saved["protocol_sha256"] != original.identity(p) or saved["selected_step"] != record["selected_step"]:
            raise ValueError("baseline checkpoint metadata mismatch")
        model = baselines.make_model(slot)
        for key in ("initial_model", "selected_model", "last_model", "cpu_prefix_model"):
            model.load_state_dict(saved[key])
            if record["status"] != "failed" and not all(bool(torch.isfinite(t).all()) for t in model.state_dict().values()):
                raise ValueError("nonfinite baseline checkpoint")
    return record


def seal_baselines(root, p):
    entries = {}
    for slot in p["slots"]:
        directory = root/slot["id"]; validate_baseline(directory, p, slot)
        entries[slot["id"]] = {file.name: original.digest(file) for file in directory.iterdir() if file.is_file()}
    original.create(root/"SEAL.json", {"protocol_sha256": original.identity(p), "attempts": entries})


def check_baselines(root, p):
    seal = original.read(root/"SEAL.json")
    if seal["protocol_sha256"] != original.identity(p) or set(seal["attempts"]) != {s["id"] for s in p["slots"]}:
        raise ValueError("baseline seal roster mismatch")
    for slot in p["slots"]:
        directory = root/slot["id"]
        if any(original.digest(directory/name) != sha for name, sha in seal["attempts"][slot["id"]].items()):
            raise ValueError("sealed baseline file changed")
        validate_baseline(directory, p, slot)
    return seal


def check_joint(root, p):
    check_baselines(root, p)
    parent_root = Path(p["parents_root"]); parent = original.load(parent_root)
    original.check_seal(parent_root, parent)
    expected = {"main_seal_sha256": original.digest(parent_root/"SEAL.json"),
                "baseline_seal_sha256": original.digest(root/"SEAL.json"), "protocol_sha256": original.identity(p)}
    if original.read(root/"JOINT_TEST_SEAL.json") != expected:
        raise ValueError("joint main/baseline test freeze changed")
    reference = original.read(parent_root/parent["slots"][0]["id"]/"result.json")
    for slot in p["slots"]:
        record = original.read(root/slot["id"]/"result.json")
        if record["status"] != "failed" and any(record[key] != reference[key] for key in ("train_data_sha256", "dev_data_sha256")):
            raise ValueError("baseline did not use byte-identical main training/development data")


def adapter():
    runner.make_model = baselines.make_model
    runner.parameter_accounting = baselines.parameter_accounting
    runner.evaluate = baselines.evaluate
    runner.check_seal = check_joint


def worker(root, p, action, slot_id):
    directory = root/"stress"/slot_id if action == "stress" else root/slot_id
    status, error = "failed", None
    try:
        if action == "stress":
            stress(root, p, slot_id)
            status = "completed"
        elif p["suite"] == "programs":
            model, info = load_parent(p, slot_id)
            if action == "prepare":
                programs.prepare(model, info, directory, p)
            else:
                programs.final_test(model, directory, p, root/"GLOBAL_SEAL.json")
            status = "completed"
        else:
            adapter(); slot = next(s for s in p["slots"] if s["id"] == slot_id)
            result = runner.fit(root, p, slot) if action == "fit" else runner.test(root, p, slot)
            status = result["status"]
        print(json.dumps({"suite": p["suite"], "slot": slot_id, "action": action, "status": status}), flush=True)
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        directory.mkdir(parents=True, exist_ok=True)
        peak = None if resource is None else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        original.create(directory/(action+"_worker_cost.json"), {"status": status, "error": error,
            "protocol_sha256": original.identity(p), "process_cpu_through_receipt": time.process_time(),
            "wall_from_first_module_statement": time.perf_counter()-ENTRY_WALL,
            "peak_rss_bytes": None if peak is None else peak*(1 if sys.platform == "darwin" else 1024),
            "energy_joules": None, "scope": "fresh worker includes imports, parent load, validation and body; shutdown excluded"})
    return 0 if status in ("completed", "censored_cpu", "evaluated", "unavailable") else 1


def launch(root, p, action, slot_id):
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (1200, 1210))
        resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
    before = None if resource is None else resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter(); logs = root/"logs"; logs.mkdir(exist_ok=True)
    timed_out = False
    with (logs/(slot_id+"-"+action+".stdout")).open("xb") as out, (logs/(slot_id+"-"+action+".stderr")).open("xb") as err:
        try:
            result = subprocess.run([sys.executable, "-m", __package__+".baselines_run", action,
                "--root", str(root), "--slot", slot_id], stdout=out, stderr=err,
                timeout=1800, preexec_fn=limits if resource is not None and os.name == "posix" else None)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            returncode, timed_out = 124, True
    after = None if resource is None else resource.getrusage(resource.RUSAGE_CHILDREN)
    record = {"returncode": returncode, "timed_out": timed_out, "launch_to_exit_wall_seconds": time.perf_counter()-start,
        "child_user_cpu_seconds": None if after is None else after.ru_utime-before.ru_utime,
        "child_system_cpu_seconds": None if after is None else after.ru_stime-before.ru_stime,
        "protocol_sha256": original.identity(p), "slot_id": slot_id, "action": action,
        "scope": "one child, sequential launch; includes interpreter startup and shutdown"}
    directory = root/"stress"/slot_id if action == "stress" else root/slot_id
    directory.mkdir(parents=True, exist_ok=True)
    original.create(directory/(action+"_launch_cost.json"), record)
    print(json.dumps(record), flush=True)
    return returncode


def short_tests_complete(root, p):
    parent_root = Path(p["parents_root"]); parent = original.load(parent_root)
    return (all((root/slot["id"]/"test_result.json").exists() for slot in p["slots"])
            and all((parent_root/slot["id"]/"test_result.json").exists() for slot in parent["slots"]))


def stress(root, p, slot_id):
    check_joint(root, p)
    if not short_tests_complete(root, p):
        raise ValueError("long-delay evaluation awaits every sealed short-test terminal record")
    specification = p["long_delay_stress"]
    directory = root/"stress"/slot_id; directory.mkdir(parents=True, exist_ok=False)
    original.create(directory/"CLAIM.json", {"protocol_sha256": original.identity(p),
        "joint_seal_sha256": original.digest(root/"JOINT_TEST_SEAL.json"), "slot_id": slot_id})
    wall, cpu = time.perf_counter(), time.process_time()
    if slot_id.startswith("parent--"):
        parent_id = slot_id.removeprefix("parent--")
        if parent_id not in specification["parents"]:
            raise ValueError("undeclared long-delay parent")
        model, model_identity = load_parent(p, parent_id); evaluator = evaluate_hcsn
        parent = original.load(Path(p["parents_root"]))
        short_path = Path(p["parents_root"])/parent_slot(parent, parent_id)["id"]/"test_result.json"
    else:
        slot = next(s for s in p["slots"] if s["id"] == slot_id)
        record = validate_baseline(root/slot_id, p, slot)
        if record["status"] == "failed":
            original.create(directory/"RESULT.json", {"status": "unavailable", "reason": record["error"]})
            return
        saved = torch.load(root/slot_id/"checkpoint.pt", weights_only=True, map_location="cpu")
        model = baselines.make_model(slot); model.load_state_dict(saved["selected_model"])
        evaluator = baselines.evaluate
        model_identity = {"slot": slot, "checkpoint_sha256": record["checkpoint_sha256"],
                          "selected_step": record["selected_step"]}
        short_path = root/slot_id/"test_result.json"
    model.eval(); original_digest = programs.tensor_digest(model.state_dict())
    short = original.read(short_path); rows, arrays = [], {}
    for panel in specification["panels"]:
        start, start_cpu = time.perf_counter(), time.process_time()
        data = generate_sources(panel["sources"], per_source=specification["per_source"],
            length=panel["length"], delay=panel["delay"], namespace="long_delay_stress")
        score, logits, _ = evaluator(model, data)
        name = "delay"+str(panel["delay"])
        arrays[name+"_logits"] = logits.numpy(); arrays[name+"_labels"] = data.y.numpy()
        arrays[name+"_source"] = data.source.numpy(); arrays[name+"_late_step"] = data.late_step.numpy()
        arrays[name+"_initial_margin"] = data.initial_margin.numpy()
        rows.append({"panel": panel, "data_sha256": data.digest(), "ids": data.ids, "metrics": score,
            "difference_from_short_accuracy": score["accuracy"]-short["metrics"]["selected"]["accuracy"],
            "capability_gate": score["accuracy"] >= specification["min_final_accuracy"] and
                score["accuracy"]-score["pre_late_accuracy"] >= specification["min_gain_over_prelate"],
            "cpu_seconds_including_data": time.process_time()-start_cpu,
            "wall_seconds_including_data": time.perf_counter()-start})
    if programs.tensor_digest(model.state_dict()) != original_digest:
        raise ValueError("stress changed frozen selected model")
    np.savez_compressed(directory/"PREDICTIONS.npz", **arrays)
    original.create(directory/"RESULT.json", {"status": "evaluated", "model_identity": model_identity,
        "protocol_sha256": original.identity(p), "panels": rows, "no_training_or_selection": True,
        "prediction_sha256": original.digest(directory/"PREDICTIONS.npz"),
        "body_cpu_seconds": time.process_time()-cpu, "body_wall_seconds": time.perf_counter()-wall})


def campaign(root, p):
    original.create(root/"CAMPAIGN_CLAIM.json", {"protocol_sha256": original.identity(p), "started_unix": time.time()})
    start, cpu = time.perf_counter(), time.process_time(); failed_workers = []
    if p["suite"] == "baselines":
        for slot in p["slots"]:
            if launch(root, p, "fit", slot["id"]) != 0:
                failed_workers.append({"stage": "fit", "slot": slot["id"]})
        seal_baselines(root, p)
        original.create(root/"TRAINING_TERMINAL.json", {"sealed_unix": time.time(), "seal_sha256": original.digest(root/"SEAL.json")})
        parent_root = Path(p["parents_root"])
        while not (parent_root/"SEAL.json").exists():
            time.sleep(10)
        original.create(root/"JOINT_TEST_SEAL.json", {"main_seal_sha256": original.digest(parent_root/"SEAL.json"),
            "baseline_seal_sha256": original.digest(root/"SEAL.json"), "protocol_sha256": original.identity(p)})
        check_joint(root, p)
        original.create(root/"TEST_CLAIM.json", {"seal_sha256": original.digest(root/"SEAL.json"), "protocol_sha256": original.identity(p)})
        for slot in p["slots"]:
            if launch(root, p, "test", slot["id"]) != 0:
                raise RuntimeError("baseline test failed without automatic retry: "+slot["id"])
        while not short_tests_complete(root, p):
            time.sleep(10)
        for slot_id in [s["id"] for s in p["slots"]]+["parent--"+name for name in p["long_delay_stress"]["parents"]]:
            if launch(root, p, "stress", slot_id) != 0:
                failed_workers.append({"stage": "stress", "slot": slot_id})
    else:
        pending = list(p["parent_ids"]); parent_root = Path(p["parents_root"])
        parent = original.load(parent_root)
        while pending:
            progress = False
            for parent_id in tuple(pending):
                directory = parent_root/parent_slot(parent, parent_id)["id"]
                if all((directory/name).exists() for name in ("result.json", "worker_cost.json", "parent_cost.json", "checkpoint.pt")):
                    if launch(root, p, "prepare", parent_id) != 0:
                        raise RuntimeError("program preparation failed; retained without automatic retry: "+parent_id)
                    pending.remove(parent_id); progress = True
            if not progress:
                time.sleep(10)
        programs.seal_all([root/name for name in p["parent_ids"]], root/"GLOBAL_SEAL.json", p)
        for parent_id in p["parent_ids"]:
            if launch(root, p, "test", parent_id) != 0:
                raise RuntimeError("program test failed; retained without automatic retry: "+parent_id)
    original.create(root/"CAMPAIGN_TERMINAL.json", {"wall_seconds": time.perf_counter()-start,
        "coordinator_cpu_seconds": time.process_time()-cpu,
        "scope": "wall includes parent-readiness waits and all sequential children; coordinator CPU excludes children",
        "finished_unix": time.time(), "status": "completed_with_failures" if failed_workers else "completed",
        "failed_workers": failed_workers})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "campaign", "fit", "prepare", "test", "stress"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--parent-root", type=Path)
    parser.add_argument("--suite", choices=("programs", "baselines"))
    parser.add_argument("--slot")
    args = parser.parse_args(); torch.set_num_threads(1)
    if args.action == "freeze":
        if args.parent_root is None or args.suite is None:
            parser.error("freeze requires --parent-root and --suite")
        p = freeze(args.root, args.parent_root, args.suite)
        print(json.dumps({"suite": p["suite"], "protocol_sha256": original.identity(p), "data_constructed": False}), flush=True)
        return 0
    p = load(args.root)
    if args.action == "campaign":
        campaign(args.root, p); return 0
    if args.slot is None:
        parser.error("worker requires --slot")
    return worker(args.root, p, args.action, args.slot)


if __name__ == "__main__":
    raise SystemExit(main())
