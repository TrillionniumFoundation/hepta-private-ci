"""Run the frozen 60-candidate Hepta study; never invoke select or score.

This scheduler is outside the frozen scientific package. It records its own
source, all registration files, child output, resource use, dispatch order,
and independently checks each completion receipt and budget checkpoint.
Incomplete candidate directories are retained and never silently restarted.
"""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import threading
import time


REPOSITORY = Path(__file__).resolve().parents[3]
SCIENTIFIC_PACKAGE = REPOSITORY / "experiments" / "call_put_stable_flow"
QUEUE_SEED = 20261029
THREAD_ENVIRONMENT = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONUNBUFFERED": "1",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def validate_frozen_sources(output):
    protocol_file = output / "protocol.json"
    protocol = json.loads(protocol_file.read_text())
    seal = json.loads((output / "freeze_seal.json").read_text())
    if digest(protocol_file) != seal["protocol_sha256"]:
        raise RuntimeError("Protocol digest no longer matches its freeze seal")
    current = {
        str(path.relative_to(SCIENTIFIC_PACKAGE)): digest(path)
        for path in sorted(SCIENTIFIC_PACKAGE.rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    if current != protocol["source_sha256"]:
        raise RuntimeError("Scientific sources changed after freezing")
    for name, expected in current.items():
        if digest(output / "source_snapshot" / name) != expected:
            raise RuntimeError(f"Frozen source snapshot changed: {name}")
    if protocol["candidate_count"] != 60 or len(protocol["candidates"]) != 60:
        raise RuntimeError("This orchestration contract requires exactly 60 candidates")
    if protocol["torch_threads"] != 1:
        raise RuntimeError("The registered study must use one torch thread per worker")
    return protocol


def validate_completion(output, specification):
    folder = output / "candidates" / specification["id"]
    path = folder / "complete.json"
    receipt = json.loads(path.read_text())
    if receipt["status"] != "complete" or receipt["specification"] != specification:
        raise RuntimeError("Candidate receipt does not match the frozen specification")
    if receipt["updates"] < 384 or receipt["training_cpu_seconds"] < 30:
        raise RuntimeError("Candidate did not reach both registered endpoints")
    trace = [json.loads(line) for line in (folder / "training_trace.jsonl").read_text().splitlines()]
    if [row["update"] for row in trace] != list(range(1, receipt["updates"] + 1)):
        raise RuntimeError("Candidate trace is incomplete or reordered")
    clocks = [row["training_cpu_seconds"] for row in trace]
    if any(later <= earlier for earlier, later in zip([0.0] + clocks[:-1], clocks)):
        raise RuntimeError("Candidate training CPU trace is not strictly increasing")
    if abs(clocks[-1] - receipt["training_cpu_seconds"]) > 1e-9:
        raise RuntimeError("Final training CPU receipt disagrees with trace")
    required = {"step0", "cpu15", "cpu30", "update192", "update384"}
    if set(receipt["checkpoints"]) != required:
        raise RuntimeError("A registered endpoint checkpoint is missing")
    for name, checkpoint in receipt["checkpoints"].items():
        if digest(folder / checkpoint["file"]) != checkpoint["sha256"]:
            raise RuntimeError(f"Checkpoint digest mismatch: {name}")
    for limit in (15, 30):
        eligible = [row for row in trace if row["training_cpu_seconds"] <= limit]
        expected = eligible[-1] if eligible else {"update": 0, "training_cpu_seconds": 0.0}
        checkpoint = receipt["checkpoints"][f"cpu{limit}"]
        if checkpoint["updates"] != expected["update"]:
            raise RuntimeError("CPU checkpoint is not the last completed in-budget update")
        if abs(checkpoint["training_cpu_seconds"] - expected["training_cpu_seconds"]) > 1e-9:
            raise RuntimeError("CPU checkpoint clock disagrees with the retained trace")
    for update in (192, 384):
        checkpoint = receipt["checkpoints"][f"update{update}"]
        if checkpoint["updates"] != update:
            raise RuntimeError("Update checkpoint is not at its exact registered update")
        if abs(checkpoint["training_cpu_seconds"] - clocks[update - 1]) > 1e-9:
            raise RuntimeError("Update checkpoint clock disagrees with the retained trace")
    if digest(folder / "final_train_diagnostics.npz") != receipt["diagnostic_sha256"]:
        raise RuntimeError("Raw final training diagnostics changed")
    return {"complete_sha256": digest(path), "updates": receipt["updates"],
            "training_cpu_seconds": receipt["training_cpu_seconds"],
            "checkpoint_count": len(receipt["checkpoints"])}


def run(output, python, workers, registrations):
    protocol = validate_frozen_sources(output)
    if (output / "selection.json").exists() or (output / "results.json").exists():
        raise RuntimeError("Training orchestration cannot run after selection or test scoring")
    if not (output / "data_manifest.json").exists():
        raise RuntimeError("Prepare and seal the data before starting training")
    for path in registrations:
        if not path.is_file():
            raise RuntimeError(f"A pre-training registration is missing: {path}")
        json.loads(path.read_text())
    session_name = datetime.now(timezone.utc).strftime("session_%Y%m%dT%H%M%SZ") + f"_{os.getpid()}"
    session = output / "orchestration" / session_name
    session.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, session / "scheduler_source.py")
    registration_rows = []
    for index, path in enumerate(registrations):
        target = session / f"registration_{index:02d}_{path.name}"
        shutil.copy2(path, target)
        registration_rows.append({"original_path": str(path), "sha256": digest(path),
                                  "retained_snapshot": target.name})
    order = list(protocol["candidates"])
    random.Random(QUEUE_SEED).shuffle(order)
    completed, pending = {}, []
    for specification in order:
        folder = output / "candidates" / specification["id"]
        if (folder / "complete.json").exists():
            completed[specification["id"]] = validate_completion(output, specification)
        elif folder.exists():
            raise RuntimeError(f"Retained incomplete candidate requires explicit review: {folder}")
        else:
            pending.append(specification)
    start_wall = time.monotonic()
    write_json(session / "dispatch_contract.json", {
        "new_execution": True, "workers": workers, "torch_threads_each": 1,
        "thread_environment": THREAD_ENVIRONMENT, "python": str(python),
        "protocol_sha256": digest(output / "protocol.json"),
        "freeze_seal_sha256": digest(output / "freeze_seal.json"),
        "data_manifest_sha256": digest(output / "data_manifest.json"),
        "scheduler_source_sha256": digest(__file__), "registrations": registration_rows,
        "queue_seed": QUEUE_SEED, "queue": [row["id"] for row in order],
        "already_complete_verified": list(completed),
        "automatic_retries": False, "validation_or_test_scoring": False,
        "external_resource_clock": "Per-child wait4 user+system CPU includes interpreter, imports, evaluations, checkpoint I/O and all work; budget clock remains the frozen per-training-update process_time sum",
        "available_disk_bytes_at_start": shutil.disk_usage(output).free,
    })
    lock = threading.Lock()
    active, outcomes, failures = {}, {}, {}
    events = (session / "events.jsonl").open("x", encoding="utf-8")

    def event(kind, **fields):
        record = {"event": kind, "unix_time": time.time(),
                  "orchestration_wall_seconds": time.monotonic() - start_wall, **fields}
        with lock:
            events.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            events.flush()
        return record

    def worker(specification):
        identifier = specification["id"]
        command = [str(python), "-m", "experiments.call_put_stable_flow.study", "train",
                   "--output", str(output), "--candidate", identifier]
        environment = os.environ.copy()
        environment.update(THREAD_ENVIRONMENT)
        began = time.monotonic()
        with (session / f"{identifier}.stdout.log").open("x") as stdout, \
                (session / f"{identifier}.stderr.log").open("x") as stderr:
            process = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            with lock:
                active[identifier] = {"pid": process.pid, "began_monotonic": began}
            event("candidate_started", candidate=identifier, pid=process.pid, command=command)
            if hasattr(os, "wait4"):
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                resource_row = {
                    "child_user_cpu_seconds": usage.ru_utime,
                    "child_system_cpu_seconds": usage.ru_stime,
                    "child_total_cpu_seconds": usage.ru_utime + usage.ru_stime,
                    "peak_rss_bytes": usage.ru_maxrss * (1 if platform.system() == "Darwin" else 1024),
                }
            else:
                process.wait()
                resource_row = {"child_resource_usage": "wait4 unavailable on this platform"}
        with lock:
            active.pop(identifier, None)
        outcome = {"candidate": identifier, "returncode": process.returncode,
                   "external_wall_seconds": time.monotonic() - began, **resource_row}
        if process.returncode != 0:
            event("candidate_failed", **outcome)
            return outcome
        try:
            outcome["verification"] = validate_completion(output, specification)
        except Exception as error:
            outcome["verification_error"] = f"{type(error).__name__}: {error}"
            event("candidate_receipt_failed", **outcome)
            return outcome
        event("candidate_complete", **outcome)
        print(json.dumps({"candidate": identifier, "status": "complete", **outcome["verification"]}), flush=True)
        return outcome

    iterator = iter(pending)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for _ in range(min(workers, len(pending))):
            specification = next(iterator)
            futures[executor.submit(worker, specification)] = specification
        while futures:
            done, _ = wait(futures, timeout=30, return_when=FIRST_COMPLETED)
            if not done:
                with lock:
                    running = dict(active)
                progress = {}
                for identifier, process in running.items():
                    trace = output / "candidates" / identifier / "training_trace.jsonl"
                    row = {"pid": process["pid"]}
                    if trace.exists():
                        lines = trace.read_text().splitlines()
                        if lines:
                            try:
                                last = json.loads(lines[-1])
                                row.update({key: last[key] for key in ("update", "training_cpu_seconds")})
                            except json.JSONDecodeError:
                                row["trace_write_in_progress"] = True
                    progress[identifier] = row
                event("heartbeat", completed=len(completed), active=progress)
                print(json.dumps({"status": "running", "completed": len(completed), "active": progress}), flush=True)
            for future in done:
                specification = futures.pop(future)
                identifier = specification["id"]
                try:
                    outcome = future.result()
                except Exception as error:
                    outcome = {"candidate": identifier, "orchestration_error": f"{type(error).__name__}: {error}"}
                    event("worker_exception", **outcome)
                outcomes[identifier] = outcome
                if "verification" in outcome:
                    completed[identifier] = outcome["verification"]
                else:
                    failures[identifier] = outcome
                if not failures:
                    following = next(iterator, None)
                    if following is not None:
                        futures[executor.submit(worker, following)] = following
    validate_frozen_sources(output)
    complete = len(completed) == 60 and not failures
    summary = {"status": "all_60_training_complete" if complete else "incomplete_requires_review",
               "validation_read_by_scheduler": False, "test_read_by_scheduler": False,
               "completed_count": len(completed), "completed": completed, "outcomes": outcomes,
               "failures": failures, "wall_seconds": time.monotonic() - start_wall,
               "new_children_cpu_seconds": sum(row.get("child_total_cpu_seconds", 0.0) for row in outcomes.values()),
               "next_phase": "Report to root before invoking select; numerical appendix remains independent"}
    write_json(session / "training_orchestration_summary.json", summary)
    event("orchestration_finished", status=summary["status"], completed=len(completed))
    events.close()
    print(json.dumps({"status": summary["status"], "completed": len(completed), "session": str(session)}), flush=True)
    return 0 if complete else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--workers", type=int, default=4, choices=(4,))
    parser.add_argument("--registration-file", type=Path, action="append", required=True)
    args = parser.parse_args()
    # Preserve the virtual-environment interpreter path. Resolving its symlink
    # selects the base interpreter and can silently change installed packages.
    return run(args.output.resolve(), args.python.absolute(), args.workers,
               [path.resolve() for path in args.registration_file])


if __name__ == "__main__":
    raise SystemExit(main())
