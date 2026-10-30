"""Resource-only queue for the unchanged, sealed fixed-128-update workers.

This external scheduler does not import or patch any training code. It invokes
the exact registered worker CLI, preserves job order and records the same
wait4 receipts and terminal schema as the frozen runner. It never signals,
terminates or changes another process. Low memory delays new dispatches only.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PROTOCOL_SHA256 = "86bd8bc59c08b96cf76de482cfde007b251ae7fcb2295ff44a4ad0616f1d9a56"
EXPECTED_UPSTREAM_SEAL = "be2b8af6147157d468c3ae22a134cc37e6ed2cd8"
GIB = 1024 ** 3
MINIMUM_HEADROOM = math.ceil(1.2 * GIB)
PENDING_WORKER_RESERVATION = MINIMUM_HEADROOM


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush(); os.fsync(stream.fileno())


def verify_protocol(path):
    if digest(path) != EXPECTED_PROTOCOL_SHA256:
        raise RuntimeError("The sealed risk128_4w protocol identity differs")
    protocol = read(path)
    if len(protocol["source_files_sha256"]) != 59 or len(protocol["jobs"]) != 112:
        raise RuntimeError("Unexpected frozen source or job count")
    if protocol["execution"]["workers"] != 4 or protocol["optimization"]["updates"] != 128:
        raise RuntimeError("Unexpected frozen worker ceiling or update count")
    for relative, expected in protocol["source_files_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError("Frozen source changed: " + relative)
    for record in protocol["data"].values():
        if digest(ROOT / record["path"]) != record["sha256"]:
            raise RuntimeError("Frozen data changed")
    return protocol


def key_values(path):
    return {parts[0]: int(parts[1]) for line in Path(path).read_text().splitlines()
            if len(parts := line.split()) == 2}


def memory_measurement():
    directory = Path("/sys/fs/cgroup")
    limit_text = (directory / "memory.max").read_text().strip()
    if limit_text == "max":
        raise RuntimeError("A finite cgroup memory limit is required by this resource plan")
    maximum = int(limit_text)
    current = int((directory / "memory.current").read_text().strip())
    stat = key_values(directory / "memory.stat")
    events = key_values(directory / "memory.events")
    # kernel is an aggregate: subtract reclaimable slab instead of adding
    # kernel_stack/pagetables/slab again. A component sum guards older kernels.
    components = sum(stat.get(name, 0) for name in (
        "kernel_stack", "pagetables", "sec_pagetables", "percpu", "vmalloc", "slab_unreclaimable"))
    kernel_nonreclaimable = max(0, stat.get("kernel", 0) - stat.get("slab_reclaimable", 0), components)
    components_estimate = stat.get("anon", 0) + kernel_nonreclaimable + sum(
        stat.get(name, 0) for name in ("sock", "shmem", "unevictable", "file_dirty", "file_writeback"))
    current_minus_cache = max(0, current - stat.get("file", 0) - stat.get("slab_reclaimable", 0))
    nonreclaimable = max(components_estimate, current_minus_cache)
    return dict(utc=utc(), monotonic=time.monotonic(), memory_max=maximum,
                memory_current=current, memory_stat=stat, memory_events=events,
                kernel_nonreclaimable_estimate=kernel_nonreclaimable,
                nonreclaimable_estimate=nonreclaimable,
                raw_headroom_bytes=maximum - nonreclaimable,
                sampling_note="memory.current and memory.stat are sequential observations, not an atomic kernel snapshot")


def anonymous_rss(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("RssAnon:"):
                return int(line.split()[1]) * 1024
    except FileNotFoundError:
        return 0
    return 0


def dispatch_decision(measurement, active_pids, desired_workers, registered_limit):
    reservations = {str(pid): max(0, PENDING_WORKER_RESERVATION - anonymous_rss(pid))
                    for pid in active_pids}
    effective_limit = min(registered_limit, measurement["memory_max"])
    available = effective_limit - measurement["nonreclaimable_estimate"] - sum(reservations.values())
    return dict(allowed=len(active_pids) < desired_workers and available >= MINIMUM_HEADROOM,
                effective_memory_limit=effective_limit, pending_worker_reservations=reservations,
                effective_headroom_bytes=available, minimum_headroom_bytes=MINIMUM_HEADROOM,
                active_workers=len(active_pids), desired_workers=desired_workers)


def create_plan(protocol_path, output, runtime):
    protocol_path, output = Path(protocol_path).resolve(), Path(output).resolve()
    protocol = verify_protocol(protocol_path)
    if read(output / "REGISTRATION.json")["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise RuntimeError("Existing registration mismatch")
    if (output / "runs").exists():
        raise RuntimeError("Do not replace or restart an existing execution")
    folder = output / "EXECUTION_PLAN"
    folder.mkdir(exist_ok=False)
    snapshot = folder / "scheduler_snapshot.py"
    snapshot.write_bytes(Path(__file__).read_bytes())
    measurement = memory_measurement()
    plan = dict(schema="hcsn-fixed128-resource-only-execution-plan.v1", created_utc=utc(),
        protocol_path=str(protocol_path.relative_to(ROOT)), protocol_sha256=EXPECTED_PROTOCOL_SHA256,
        upstream_public_seal=EXPECTED_UPSTREAM_SEAL,
        scheduler_source=str(Path(__file__).relative_to(ROOT)), scheduler_sha256=digest(Path(__file__)),
        scheduler_snapshot=str(snapshot.relative_to(ROOT)), scheduler_snapshot_sha256=digest(snapshot),
        unchanged=dict(frozen_sources=59, jobs=112, job_order=True, worker_cli=True, updates=128,
                       learning_rate=.001, training_cpu_cap=900, heldout_and_selection_logic=True,
                       no_failed_candidate_retry=True),
        resources=dict(initial_workers=1, protocol_worker_ceiling=4, registered_memory_limit=measurement["memory_max"],
            minimum_dispatch_headroom_bytes=MINIMUM_HEADROOM,
            pending_worker_reservation_bytes=PENDING_WORKER_RESERVATION,
            formula="limit - max(anon + nonreclaimable_kernel + sock + shmem + unevictable + dirty + writeback, memory.current - file - reclaimable_slab) - pending_worker_reservations",
            kernel_formula="max(kernel - slab_reclaimable, kernel_stack + pagetables + sec_pagetables + percpu + vmalloc + slab_unreclaimable, 0)",
            reservation_formula="sum over own active workers max(0,1.2GiB-RssAnon(pid)); reserves not-yet-allocated training memory",
            no_dispatch_below_threshold=True, minimum_seconds_between_dispatches=10,
            polling_seconds=.25, heartbeat_seconds=15,
            insufficient_resources="Wait; do not kill or modify active workers or any other process"),
        control=dict(path=str((folder / "CONTROL.json").relative_to(ROOT)), initial_desired_workers=1,
            permitted_range=[0, 4], increase_only_on_root_instruction=True,
            meaning="0 pauses future dispatch without cancelling jobs; STOP_REQUESTED drains and terminates the queue"),
        environment=dict(PYTHONPATH=str(Path(runtime).resolve()), OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                         OPENBLAS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1"),
        receipts="Original equal_updates wait4 receipt keys and COMPLETE/ABORTED schema; additive resource journal outside receipts",
        failure="Any own worker failure stops new dispatches and drains active; no retries or filled cells",
        terminal_status="Read COMPLETE.json/ABORTED.json, not only process exit code",
        initial_resource_measurement=measurement)
    write(folder / "PLAN.json", plan)
    write(folder / "CONTROL.json", dict(desired_workers=1, revision=0, reason="Initial one-worker execution requested by root", utc=utc()))
    fixture = dict(memory_max=8 * GIB, nonreclaimable_estimate=8 * GIB - MINIMUM_HEADROOM + 1)
    assert not dispatch_decision(fixture, [], 1, 8 * GIB)["allowed"]
    fixture["nonreclaimable_estimate"] -= 1
    assert dispatch_decision(fixture, [], 1, 8 * GIB)["allowed"]
    assert not dispatch_decision(fixture, [], 0, 8 * GIB)["allowed"]
    write(folder / "RESOURCE_PREFLIGHT.json", dict(passed=True,
        low_headroom_rejected=True, threshold_equality_accepted=True, zero_worker_control_pauses=True,
        frozen_protocol_verified=True, scheduler_sha256=plan["scheduler_sha256"]))
    print(json.dumps(dict(plan=str(folder / "PLAN.json"), plan_sha256=digest(folder / "PLAN.json"),
                          scheduler_sha256=plan["scheduler_sha256"], initial_workers=1)), flush=True)


def set_control(output, workers, reason):
    path = Path(output).resolve() / "EXECUTION_PLAN" / "CONTROL.json"
    if workers < 0 or workers > 4:
        raise ValueError("Desired workers must be in [0,4]")
    previous = read(path)
    new = dict(desired_workers=workers, revision=previous["revision"] + 1, reason=reason, utc=utc())
    append(path.parent / "CONTROL_CHANGES.jsonl", dict(previous=previous, next=new))
    write(path, new)
    print(json.dumps(new), flush=True)


def run(protocol_path, output):
    protocol_path, output = Path(protocol_path).resolve(), Path(output).resolve()
    protocol = verify_protocol(protocol_path)
    folder = output / "EXECUTION_PLAN"
    plan = read(folder / "PLAN.json")
    if plan["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256 or digest(Path(__file__)) != plan["scheduler_sha256"]:
        raise RuntimeError("Execution-plan identity mismatch")
    if digest(ROOT / plan["scheduler_snapshot"]) != plan["scheduler_snapshot_sha256"]:
        raise RuntimeError("Scheduler snapshot changed")
    if (output / "COMPLETE.json").exists() or (output / "ABORTED.json").exists():
        raise RuntimeError("A terminal study cannot be rerun")
    (output / "runs").mkdir(); (output / "process_logs").mkdir()
    environment = dict(os.environ, **plan["environment"])
    pending, active, records, stopped = list(protocol["jobs"]), {}, [], False
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    last_dispatch, last_heartbeat = -float("inf"), -float("inf")
    last_control_hash, last_events = None, None
    write(folder / "LAUNCH.json", dict(utc=utc(), pid=os.getpid(), protocol_sha256=EXPECTED_PROTOCOL_SHA256,
        plan_sha256=digest(folder / "PLAN.json"), source_sha256=plan["scheduler_sha256"],
        command=sys.argv, initial_workers=1))
    while pending or active:
        try:
            if (output / "STOP_REQUESTED.json").exists():
                stopped = True
            for pid, item in list(active.items()):
                got, status, usage = os.wait4(pid, os.WNOHANG)
                if not got:
                    continue
                process, stream, job, run_folder, log, command, launched = item
                code = os.waitstatus_to_exitcode(status); process.returncode = code; stream.close()
                receipt = dict(job=job, command=command, returncode=code, protocol_sha256=EXPECTED_PROTOCOL_SHA256,
                    stdout_sha256=digest(log), child_user_cpu_seconds=usage.ru_utime,
                    child_system_cpu_seconds=usage.ru_stime, child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
                    child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter() - launched)
                records.append(receipt); del active[pid]
                stopped = stopped or code != 0
                write(output / "PROGRESS.json", dict(records=records, expected=len(protocol["jobs"])))
                run_folder.mkdir(exist_ok=True)
                write(run_folder / "EXECUTION.json", receipt)
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="reaped", utc=utc(), pid=pid, job=job,
                    returncode=code, completed=len(records), active_workers=len(active), resources=memory_measurement()))
                print(json.dumps(dict(event="completed", completed=len(records), expected=len(protocol["jobs"]),
                                      job=job, returncode=code, active_workers=len(active))), flush=True)
            if stopped and not active:
                break
            if stopped:
                # Preserve the original stop-and-drain policy even if an external
                # control file or resource probe caused a scheduler error.
                time.sleep(plan["resources"]["polling_seconds"])
                continue
            control = read(folder / "CONTROL.json")
            desired = control["desired_workers"]
            if not isinstance(desired, int) or desired < 0 or desired > protocol["execution"]["workers"]:
                raise ValueError("Control exceeds the registered worker ceiling")
            control_hash = digest(folder / "CONTROL.json")
            if control_hash != last_control_hash:
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="control_observed", utc=utc(),
                    control=control, control_sha256=control_hash))
                last_control_hash = control_hash
            now = time.monotonic()
            should_measure = now - last_heartbeat >= plan["resources"]["heartbeat_seconds"]
            can_consider_dispatch = pending and not stopped and len(active) < desired and \
                now - last_dispatch >= plan["resources"]["minimum_seconds_between_dispatches"]
            if should_measure or can_consider_dispatch:
                measured = memory_measurement()
                decision = dispatch_decision(measured, list(active), desired, plan["resources"]["registered_memory_limit"])
                if measured["memory_events"] != last_events:
                    append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="memory_events_observed", utc=utc(),
                        previous=last_events, current=measured["memory_events"]))
                    last_events = measured["memory_events"]
                if should_measure:
                    heartbeat = dict(event="heartbeat", utc=utc(), completed=len(records), pending=len(pending),
                                     active_pids=list(active), stopped=stopped, resources=measured, decision=decision)
                    write(folder / "HEARTBEAT.json", heartbeat)
                    append(folder / "RESOURCE_JOURNAL.jsonl", heartbeat)
                    last_heartbeat = now
                if can_consider_dispatch and decision["allowed"]:
                    if digest(protocol_path) != EXPECTED_PROTOCOL_SHA256:
                        raise RuntimeError("Protocol changed before dispatch")
                    job = pending[0]
                    identifier = f"{job['task']}__{job['model']}__{job['seed']}"
                    run_folder = output / "runs" / identifier
                    log = output / "process_logs" / (identifier + ".log")
                    stream = log.open("x")
                    command = [sys.executable, "-m", "experiments.hcsn_risk_ablation_v1.equal_updates", "worker",
                        "--protocol", str(protocol_path), "--output", str(run_folder),
                        "--task", job["task"], "--model", job["model"], "--seed", str(job["seed"])]
                    dispatched = dict(event="dispatch", utc=utc(), dispatch_index=len(protocol["jobs"]) - len(pending) + 1,
                        job=job, command=command, control=control, control_sha256=control_hash,
                        resources=measured, decision=decision, scheduler_sha256=plan["scheduler_sha256"])
                    append(folder / "RESOURCE_JOURNAL.jsonl", dispatched)
                    process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
                    active[process.pid] = (process, stream, job, run_folder, log, command, time.perf_counter())
                    pending.pop(0)
                    last_dispatch = now
                    append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="launched", utc=utc(),
                        pid=process.pid, job=job, active_workers=len(active)))
                    print(json.dumps(dict(event="launched", completed=len(records), job=job, pid=process.pid,
                        active_workers=len(active), effective_headroom_gib=decision["effective_headroom_bytes"] / GIB)), flush=True)
            if pending or active:
                time.sleep(plan["resources"]["polling_seconds"])
        except Exception:
            stopped = True
            append(folder / "SCHEDULER_FAILURES.jsonl", dict(utc=utc(), phase="scheduler_loop",
                active_pids=list(active), pending_jobs=len(pending), traceback=traceback.format_exc()))
            time.sleep(plan["resources"]["polling_seconds"])
    try:
        verify_protocol(protocol_path)
    except Exception:
        stopped = True
        append(folder / "SCHEDULER_FAILURES.jsonl", dict(utc=utc(), phase="final_identity_check", traceback=traceback.format_exc()))
    complete = not stopped and len(records) == len(protocol["jobs"])
    final = dict(status="completed" if complete else "aborted", protocol_sha256=EXPECTED_PROTOCOL_SHA256,
        records=records, expected=len(protocol["jobs"]), completed=len(records), unstarted=pending,
        failures=sum(row["returncode"] != 0 for row in records),
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall)
    write(output / ("COMPLETE.json" if complete else "ABORTED.json"), final)
    write(folder / "TERMINAL_RESOURCE_SNAPSHOT.json", dict(utc=utc(), resources=memory_measurement(),
        completed=complete, source_sha256=digest(Path(__file__)), plan_sha256=digest(folder / "PLAN.json")))
    print(json.dumps(dict(event="terminal", status=final["status"], completed=len(records),
                          worker_cpu_seconds=final["complete_child_cpu_seconds"])), flush=True)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run", "control"))
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--reason")
    arguments = parser.parse_args()
    if arguments.action == "plan":
        create_plan(arguments.protocol, arguments.output, arguments.runtime)
    elif arguments.action == "control":
        set_control(arguments.output, arguments.workers, arguments.reason)
    else:
        run(arguments.protocol, arguments.output)
