"""Registered singleton admission for the unchanged COMPLETE report assembler.

The parent imports only stdlib/operational modules, owns the controller lock,
reserves a worker, and registers its PID before the child imports report code.
This performs no training, endpoint scoring, threshold selection, or refitting.
"""

import argparse
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import subprocess
import sys
import time

from .resource_v2 import (RAW_OPEN, StorageBudget, file_hash, load_registration,
                         memory_admission, memory_profile, pending_growth, whole_phase_lock)
from .resource_io_v2 import guarded_writes
from .run_v2 import ORIGINAL_A, ensure_loaded_closure, verify_files

ROOT = Path(__file__).resolve().parents[2]
PHASES = ("A", "B", "C", "W", "R")
SEEDS = (17, 29, 43)
JOB_IDS = {f"{p}-{s}" for p in ("A", "B", "R") for s in SEEDS} | {
    "C", "W", "A_endpoint", "B_endpoint", "C_endpoint"}
MODULE = "experiments.parameter_field_fullstudy_20261029.analysis_launch_v2"
LOG_CAP = 4 * 1024 ** 2


def require(test, message):
    if not test:
        raise ValueError(message)


def descriptor(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": file_hash(path)}


def json_read(path):
    with RAW_OPEN(path) as stream:
        return json.load(stream)


def descriptors(value):
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"} <= set(value):
            yield value
        for item in value.values():
            yield from descriptors(item)
    elif isinstance(value, list):
        for item in value:
            yield from descriptors(item)


def validate(args):
    registration = load_registration(args.amendment, args.amendment_sha256)
    root = Path(args.root).resolve()
    freeze = json_read(args.freeze)
    require(root.is_dir() and root == Path(registration["raw_root"]).resolve(), "Analysis raw root differs")
    require(file_hash(args.freeze) == args.freeze_sha256, "Analysis source-freeze bytes differ")
    require(freeze.get("execution_kind") == "aggregate_analysis" and freeze.get("allowed_phases") == ["ANALYSIS"]
            and freeze.get("attempt_id") == registration["attempt_id"] == "attempt02"
            and freeze.get("operational_amendment_sha256") == registration["_sha256"]
            and re.fullmatch(r"[0-9a-f]{40}", freeze.get("registered_commit", "")), "Unregistered aggregate analysis")
    verify_files(freeze, ROOT)
    prefix = Path(__file__).parent.relative_to(ROOT)
    require(all(str(prefix / (name + ".py")) in freeze["source_files"] for name in (
        "analysis_launch_v2", "report_results", "resource_v2", "resource_io_v2", "run_v2")), "Analysis source closure incomplete")
    require(freeze.get("report_module") == __package__ + ".report_results", "Report module differs")
    inputs = descriptor(args.inputs)
    require(inputs == freeze.get("report_inputs") and inputs["sha256"] == args.expected_sha256,
            "Report input manifest differs from registration")
    output = (root / freeze["output_relative"]).resolve()
    require(output.is_relative_to(root) and output != root and Path(args.output).resolve() == output,
            "Report output differs or escapes raw root")
    require(not output.exists(), "Refusing to replace previous report evidence")
    require(re.fullmatch(r"[A-Za-z0-9]+", freeze.get("analysis_id", "")), "Unsafe analysis identity")
    spec = json_read(inputs["path"])
    require(spec.get("schema") == "hepta.fullstudy.report-inputs.1"
            and spec.get("attempt_id") == "attempt02" and Path(spec["raw_root"]).resolve() == root
            and set(spec["stages"]) == set(PHASES)
            and all(spec["stages"][p]["status"] == "COMPLETE" for p in PHASES), "All scientific stages must be sealed first")
    require(spec["amendment"] == descriptor(args.amendment)
            and spec["protocol"]["sha256"] == registration["original_protocol"]["sha256"] == ORIGINAL_A[2]
            and freeze.get("protocol_sha256") == ORIGINAL_A[2], "Report scientific or operation ancestry differs")
    artifacts = freeze.get("artifacts", {})
    require(artifacts.get(inputs["path"]) == inputs["sha256"], "Report manifest absent from frozen artifacts")
    for item in descriptors(spec):
        require(descriptor(item["path"]) == item and artifacts.get(item["path"]) == item["sha256"],
                "Report descriptor is unbound or its bytes differ")
    seals, job_completions = {}, {}
    for phase in PHASES:
        runs = spec["stages"][phase]["runs"]
        expected = set(SEEDS) if phase in ("A", "B", "R") else {None}
        require(len(runs) == len(expected) and {run["seed"] for run in runs} == expected, "Incomplete scientific operation population")
        for run in runs:
            token = f"{phase}-seed-{run['seed']}" if run["seed"] is not None else f"{phase}-all"
            complete = f"stage_{phase}/seed-{run['seed']}/COMPLETE.json" if run["seed"] is not None else f"stage_{phase}/COMPLETE.json"
            for key, relative in (("operation", f"operations/{token}.COMPLETE.json"), ("complete", complete)):
                require(Path(run[key]["path"]).resolve() == root / relative, "Scientific completion path differs")
                seals[str(root / relative)] = run[key]["sha256"]
            job_id = f"{phase}-{run['seed']}" if run["seed"] is not None else phase
            op = run["operation"]
            job_completions[job_id] = {**op, "path": str(Path(op["path"]).relative_to(root))}
        if phase in ("A", "B", "C"):
            relative = f"stage_{phase}/" + ("endpoint_evaluation" if phase == "C" else "endpoints") + "/ENDPOINTS.json"
            endpoint = spec["stages"][phase]["endpoint"]
            require(Path(endpoint["path"]).resolve() == root / relative, "Endpoint completion path differs")
            seals[str(root / relative)] = endpoint["sha256"]
            job_completions[phase + "_endpoint"] = {**endpoint, "path": relative}
    controller = root / "controller/EXECUTION.json"
    completed = json_read(controller)
    require(completed.get("complete") is True and set(completed["jobs"]) == JOB_IDS
            and all(row.get("complete") is True for row in completed["jobs"].values())
            and all(completed["jobs"][name].get("completion") == expected for name, expected in job_completions.items()),
            "Full fourteen-job controller completion identities differ")
    seals[str(controller)] = file_hash(controller)
    require(freeze.get("required_scientific_seals") == seals
            and all(artifacts.get(path) == sha for path, sha in seals.items()), "Required scientific seals differ")
    return registration, freeze


def active_workers(root):
    path = Path(root) / "ACTIVE_WORKERS.json"
    return json_read(path).get("workers", []) if path.exists() else []


def binding(args, freeze):
    return {"attempt_id": "attempt02", "phase": "ANALYSIS", "analysis_id": freeze["analysis_id"],
            "source_freeze_sha256": args.freeze_sha256, "registered_commit": freeze["registered_commit"],
            "operational_amendment_sha256": args.amendment_sha256, "report_inputs_sha256": args.expected_sha256,
            "scheduled_gradient_microsteps": 0, "endpoint_scoring_performed": False, "refitting_performed": False}


def child(args):
    deadline = time.monotonic() + 5.
    while True:
        rows = active_workers(args.root)
        matching = [row for row in rows if row.get("id") == "ANALYSIS" and row.get("pid") == os.getpid()
                    and row.get("source_freeze_sha256") == args.freeze_sha256
                    and row.get("report_inputs_sha256") == args.expected_sha256]
        if len(rows) == len(matching) == 1 and os.getppid() == args.parent_pid:
            break
        require(time.monotonic() < deadline, "Analysis child was not registered by its parent")
        time.sleep(.05)
    registration, freeze = validate(args)
    storage = StorageBudget(args.root, registration)
    storage.check()
    with guarded_writes(storage):
        module = importlib.import_module(freeze["report_module"])
        old_argv = sys.argv
        try:
            sys.argv = [module.__name__, "--inputs", args.inputs, "--expected-sha256", args.expected_sha256, "--output", args.output]
            module.main()  # Unchanged assembler enforces its own training_slot and original verified loaders.
        finally:
            sys.argv = old_argv
        ensure_loaded_closure(freeze)
        storage.check()
        storage.write_json(Path(args.root) / "analysis_operations" / freeze["analysis_id"] / "WORKER_COMPLETE.json", {
            **binding(args, freeze), "complete": True, "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
            "process_cpu_seconds_total": time.process_time(), "post_execution_storage_check": True})
    return 0


def child_argv(args):
    result = [sys.executable, "-B", "-m", MODULE, "--child", "--parent-pid", str(os.getpid())]
    for key in ("root", "inputs", "expected_sha256", "output", "freeze", "freeze_sha256", "amendment", "amendment_sha256"):
        result += ["--" + key.replace("_", "-"), str(getattr(args, key))]
    return result


def monitor(process, storage, log, baseline):
    selector = selectors.DefaultSelector()
    os.set_blocking(process.stdout.fileno(), False)
    selector.register(process.stdout, selectors.EVENT_READ)
    started, closed = time.monotonic(), False
    try:
        while process.poll() is None or not closed:
            for key, unused in selector.select(timeout=.2):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    closed = True
                else:
                    require(log.stat().st_size + len(chunk) <= LOG_CAP, "Bounded analysis log exceeded 4 MiB")
                    storage.append_bytes(log, chunk)
            profile = memory_profile()
            require(all(profile[k] <= baseline[k] for k in ("oom", "oom_kill")), "OOM counter increased during analysis")
            require(time.monotonic() - started <= 3600, "One-hour aggregate analysis window exhausted")
        return process.returncode
    finally:
        selector.close()



def prepare_control(storage, control, args, freeze):
    if control.exists():
        require(getattr(args, "resume_admission", False), "Analysis control exists; only explicit pure-admission retry is supported")
        receipt = json_read(control / "ADMISSION_FAILED.json")
        require({p.name for p in control.iterdir()} == {"ADMISSION_FAILED.json"}
                and receipt.get("status") == "ADMISSION_BLOCKED" and receipt.get("workers_started") == 0
                and all(receipt.get(key) == value for key, value in binding(args, freeze).items()),
                "Only unchanged zero-worker admission evidence may be retried")
        index = 1
        while control.with_name(control.name + f"_admission_{index:03d}").exists():
            index += 1
        with storage.writer_lock():
            storage.check(check_memory=False)
            control.rename(control.with_name(control.name + f"_admission_{index:03d}"))
    control.mkdir(parents=True, exist_ok=False)


def parent(args):
    registration, freeze = validate(args)
    root = Path(args.root).resolve()
    storage = StorageBudget(root, registration)
    control = root / "analysis_operations" / freeze["analysis_id"]
    process, registry_cleared, started = None, False, time.monotonic()
    with RAW_OPEN(root / ".ops-controller.lock", "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not active_workers(root), "Analysis requires an empty worker registry")
        with whole_phase_lock(root):
            require(not active_workers(root), "Scientific writer is still active")
        prepare_control(storage, control, args, freeze)
        baseline = memory_profile()
        admission = memory_admission(registration["concurrency"]["worker_reservation_bytes"],
                                     registration["concurrency"]["memory_margin_bytes"], pending_growth(root))
        if not admission["allowed"]:
            storage.write_json(control / "ADMISSION_FAILED.json", {**binding(args, freeze), "complete": False,
                "status": "ADMISSION_BLOCKED", "workers_started": 0, "admission": admission}, failure_record=True)
            return 75
        try:
            storage.check()
            storage.write_json(control / "START.json", {**binding(args, freeze), "parent_pid": os.getpid(),
                "started_unix": time.time(), "admission": admission})
            log = control / "worker.log"
            storage.write_bytes(log, b"")
            process = subprocess.Popen(child_argv(args), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            storage.write_json(root / "ACTIVE_WORKERS.json", {"workers": [{"id": "ANALYSIS", "pid": process.pid,
                "reservation_bytes": registration["concurrency"]["worker_reservation_bytes"],
                "source_freeze_sha256": args.freeze_sha256, "report_inputs_sha256": args.expected_sha256}],
                "oom_baseline": {k: baseline[k] for k in ("oom", "oom_kill")}}, allow_replace=True)
            code = monitor(process, storage, log, baseline)
            require(code == 0, "Aggregate worker failed with exit code " + str(code))
            storage.write_json(root / "ACTIVE_WORKERS.json", {"workers": [],
                "oom_baseline": {k: baseline[k] for k in ("oom", "oom_kill")}}, allow_replace=True)
            registry_cleared = True
            worker = json_read(control / "WORKER_COMPLETE.json")
            require(worker.get("complete") is True and worker.get("post_execution_storage_check") is True
                    and all(worker.get(key) == value for key, value in binding(args, freeze).items()), "Aggregate worker seal differs")
            result = json_read(Path(args.output) / "RESULTS.json")
            require(result.get("status") == "COMPLETE" and result.get("input_sha256") == args.expected_sha256
                    and result.get("efficacy_artifacts_opened") is True, "Complete aggregate result is missing or unbound")
            outputs = [descriptor(Path(args.output) / name) for name in ("RESULTS.json", "REPORT.md")]
            storage.check()
            storage.write_json(control / "COMPLETE.json", {**binding(args, freeze), "complete": True,
                "outputs": outputs, "worker_receipt": descriptor(control / "WORKER_COMPLETE.json"),
                "wall_seconds": time.monotonic() - started, "post_execution_storage_check": True,
                "process_peak_rss_bytes": worker["process_peak_rss_bytes"],
                "worker_cpu_seconds_total": worker["process_cpu_seconds_total"],
                "parent_cpu_seconds_total": time.process_time()})
            return 0
        except BaseException as error:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            failure = {**binding(args, freeze), "complete": False, "error_type": type(error).__name__,
                       "message": str(error)[:8192], "partial_evidence_preserved": True,
                       "wall_seconds": time.monotonic() - started}
            try:
                storage.write_json(control / "FAILED.json", failure, failure_record=True)
            except (OSError, RuntimeError, MemoryError):
                print(json.dumps(failure), flush=True)
            raise
        finally:
            if process is not None and process.poll() is not None and not registry_cleared:
                storage.write_json(root / "ACTIVE_WORKERS.json", {"workers": [],
                    "oom_baseline": {k: baseline[k] for k in ("oom", "oom_kill")}}, allow_replace=True)
            if process is not None and process.stdout is not None and not process.stdout.closed:
                process.stdout.close()


def main():
    parser = argparse.ArgumentParser()
    for key in ("root", "inputs", "expected-sha256", "output", "freeze", "freeze-sha256", "amendment", "amendment-sha256"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--resume-admission", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    require(args.child == (args.parent_pid is not None), "Child launch must identify its parent")
    raise SystemExit(child(args) if args.child else parent(args))


if __name__ == "__main__":
    main()
