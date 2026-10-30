"""Publicly sealed, resource-guarded fresh fixed128 queue; never retries jobs."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

from .train_equivalence import ROOT, PACKAGE, GIB, sha, verify, utc
from .resource_accounting import measurement, own_host_pid, anonymous_credit, decision


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read(path):
    return json.loads(Path(path).read_bytes())


def verified_protocol(path):
    protocol = read(path)
    verify(protocol)
    if (protocol["schema"] != "hcsn-risk-memory-profile-fixed128.v1" or
            protocol["study_id"] != "memory_profile002" or len(protocol["jobs"]) != 112):
        raise RuntimeError("Unexpected fresh fixed128 protocol")
    if (protocol["execution"]["workers"] != 4 or
            protocol["execution"]["initial_desired_workers"] != 2 or
            protocol["execution"]["per_worker_peak_budget_bytes"] < 1.1 * GIB or
            protocol["execution"]["required_shared_reserve_bytes"] < 2 * GIB):
        raise RuntimeError("Unexpected resource limits")
    return protocol


def prepare(protocol_path, output, runtime):
    protocol = verified_protocol(protocol_path)
    digest = sha(protocol_path)
    if read(output / "REGISTRATION.json")["protocol_sha256"] != digest:
        raise RuntimeError("Registration identity mismatch")
    if (output / "runs").exists():
        raise RuntimeError("Cannot prepare or restart an existing execution")
    folder = output / "EXECUTION_PLAN"
    folder.mkdir(exist_ok=False)
    snapshot = folder / "source_snapshot"
    snapshot.mkdir()
    source_files = {}
    for name in ("resource_queue.py", "resource_accounting.py", "train_equivalence.py"):
        source = PACKAGE / name
        target = snapshot / name
        target.write_bytes(source.read_bytes())
        source_files[str(source.relative_to(ROOT))] = sha(source)
    resources = measurement()
    plan = dict(schema="hcsn-risk-memory-profile-execution-plan.v1", created_utc=utc(),
        protocol_path=str(protocol_path.relative_to(ROOT)), protocol_sha256=digest,
        scheduler_source_files_sha256=source_files,
        snapshot_files_sha256={str(path.relative_to(ROOT)): sha(path) for path in sorted(snapshot.glob("*.py"))},
        registered_memory_limit_bytes=resources["maximum_bytes"],
        initial_desired_workers=2, maximum_workers=4,
        per_worker_peak_budget_bytes=protocol["execution"]["per_worker_peak_budget_bytes"],
        required_shared_reserve_bytes=protocol["execution"]["required_shared_reserve_bytes"],
        formula="limit - conservative current nonreclaimable - sum(max(worker_budget - verified own worker RssAnon,0)) - new_worker_budget >= 2GiB",
        pid_verification="unique /proc host PPid == coordinator host PID and NSpid[-1] == Popen namespace PID; unknown/ambiguous credit zero",
        preflight=protocol["numerical_revision"],
        minimum_seconds_between_dispatches=10, poll_seconds=.5, heartbeat_seconds=15,
        controls="initial2; increases only after recorded root authorization; maximum4; zero pauses future launches",
        failure="any child failure, new cgroup OOM event or own worker budget exceedance stops dispatch; drain active; preserve all costs; no retries or filling",
        unchanged=["registered112 order", "original frozen fixed128 worker body", "128 updates", "900 trainingCPU cap", "selection/heldout logic", "all four primary statistical comparisons"],
        receipt_schema="exact original equal_updates EXECUTION and COMPLETE/ABORTED keys; resource metadata separate",
        environment=dict(PYTHONPATH=str(runtime.resolve()), OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                         OPENBLAS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1"),
        initial_resources=resources)
    write(folder / "PLAN.json", plan)
    control = dict(desired_workers=2, revision=0, utc=utc(),
        authorization="root instruction: initial2 max4; >=1.1GiB per worker plus2GiB shared; public seal before execution",
        reason="Initial two-worker ceiling; actual dispatch waits for the full guarded budget")
    write(folder / "CONTROL.json", control)
    append(folder / "CONTROL_HISTORY.jsonl", dict(event="initial", control=control, resources=resources))
    print(json.dumps(dict(plan=str(folder / "PLAN.json"), plan_sha256=sha(folder / "PLAN.json"),
                         protocol_sha256=digest, scheduler_source_files_sha256=source_files)), flush=True)


def set_control(output, desired, reason, authorization):
    folder = output / "EXECUTION_PLAN"
    if desired < 0 or desired > read(folder / "PLAN.json")["maximum_workers"]:
        raise ValueError("Worker ceiling must be in [0,4]")
    if not reason.strip() or not authorization.strip():
        raise ValueError("Reason and explicit root authorization must be recorded")
    previous = read(folder / "CONTROL.json")
    current = dict(desired_workers=desired, revision=previous["revision"] + 1,
                   utc=utc(), reason=reason, authorization=authorization)
    append(folder / "CONTROL_HISTORY.jsonl", dict(event="change", previous=previous,
                                                   current=current, resources=measurement()))
    write(folder / "CONTROL.json", current)
    print(json.dumps(current), flush=True)


def run(protocol_path, output, public_commit):
    if not re.fullmatch("[0-9a-f]{40}", public_commit):
        raise ValueError("A public seal commit supplied by root is required")
    protocol = verified_protocol(protocol_path)
    digest = sha(protocol_path)
    folder = output / "EXECUTION_PLAN"
    plan = read(folder / "PLAN.json")
    if plan["protocol_sha256"] != digest:
        raise RuntimeError("Plan identity mismatch")
    for key in ("scheduler_source_files_sha256", "snapshot_files_sha256"):
        for name, expected in plan[key].items():
            if sha(ROOT / name) != expected:
                raise RuntimeError("Sealed execution source changed: " + name)
    if (output / "COMPLETE.json").exists() or (output / "ABORTED.json").exists():
        raise RuntimeError("A terminal cohort cannot be restarted")
    (output / "runs").mkdir()
    (output / "process_logs").mkdir()
    environment = dict(os.environ, **plan["environment"])
    host_parent = own_host_pid()
    initial_resources = measurement()
    initial_oom_kills = initial_resources["events"]["oom_kill"]
    write(folder / "PUBLIC_SEAL.json", dict(public_commit=public_commit, root_supplied_seal=True,
        protocol_sha256=digest, plan_sha256=sha(folder / "PLAN.json"),
        source_files_sha256=protocol["source_files_sha256"], received_utc=utc()))
    write(folder / "LAUNCH.json", dict(utc=utc(), namespace_pid=os.getpid(), host_pid=host_parent,
        public_commit=public_commit, protocol_sha256=digest, command=sys.argv,
        initial_resources=initial_resources, actual_initial_control=read(folder / "CONTROL.json")))
    pending, active, records, stopped = list(protocol["jobs"]), {}, [], False
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    last_dispatch, last_heartbeat, last_control = -float("inf"), -float("inf"), None
    budget, reserve = plan["per_worker_peak_budget_bytes"], plan["required_shared_reserve_bytes"]
    while pending or active:
        try:
            stopped = stopped or (output / "STOP_REQUESTED.json").exists()
            for pid, item in list(active.items()):
                got, wait_status, usage = os.wait4(pid, os.WNOHANG)
                if not got:
                    continue
                process, stream, job, run_folder, log, command, launched = item
                code = os.waitstatus_to_exitcode(wait_status)
                process.returncode = code
                stream.close()
                receipt = dict(job=job, command=command, returncode=code, protocol_sha256=digest,
                    stdout_sha256=sha(log), child_user_cpu_seconds=usage.ru_utime,
                    child_system_cpu_seconds=usage.ru_stime,
                    child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
                    child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter() - launched)
                records.append(receipt)
                del active[pid]
                # Persist complete cost centrally before touching a potentially
                # absent worker folder (e.g. failure during interpreter import).
                write(output / "PROGRESS.json", dict(records=records, expected=len(protocol["jobs"])))
                run_folder.mkdir(exist_ok=True)
                write(run_folder / "EXECUTION.json", receipt)
                stopped = stopped or code != 0 or usage.ru_maxrss * 1024 > budget
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="reaped", utc=utc(),
                    namespace_pid=pid, job=job, returncode=code, peak_rss_bytes=usage.ru_maxrss * 1024,
                    peak_exceeded_budget=usage.ru_maxrss * 1024 > budget, completed=len(records),
                    resources=measurement()))
                print(json.dumps(dict(completed=len(records), expected=len(protocol["jobs"]),
                                      job=job, returncode=code, active_workers=len(active))), flush=True)
            if stopped and not active:
                break
            if stopped:
                time.sleep(plan["poll_seconds"])
                continue
            resources = measurement()
            credits = [anonymous_credit(pid, host_parent) for pid in active]
            if (resources["events"]["oom_kill"] != initial_oom_kills or
                    any(row["credited_anon_bytes"] > budget for row in credits)):
                stopped = True
                write(folder / "RESOURCE_STOP.json", dict(utc=utc(), resources=resources,
                    credits=credits, initial_oom_kills=initial_oom_kills,
                    reason="new cgroup OOM event or own active anonymous memory exceeds declared worker budget"))
                continue
            control = read(folder / "CONTROL.json")
            desired = control["desired_workers"]
            if not isinstance(desired, int) or desired < 0 or desired > plan["maximum_workers"]:
                raise ValueError("Invalid desired worker ceiling")
            control_hash = sha(folder / "CONTROL.json")
            if control_hash != last_control:
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="control_observed", utc=utc(),
                    control=control, control_sha256=control_hash, resources=resources))
                last_control = control_hash
            allowed = decision(resources, credits, desired, budget, reserve,
                               plan["registered_memory_limit_bytes"])
            now = time.perf_counter()
            if now - last_heartbeat >= plan["heartbeat_seconds"]:
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="heartbeat", utc=utc(),
                    completed=len(records), remaining=len(pending), resources=resources, decision=allowed))
                last_heartbeat = now
            if pending and allowed["allowed"] and now - last_dispatch >= plan["minimum_seconds_between_dispatches"]:
                verified_protocol(protocol_path)
                if sha(protocol_path) != digest:
                    raise RuntimeError("Protocol identity changed")
                job = pending[0]
                name = f"{job['task']}__{job['model']}__{job['seed']}"
                run_folder = output / "runs" / name
                log = output / "process_logs" / (name + ".log")
                command = [sys.executable, "-m", "experiments.hcsn_risk_memory_v1.study", "worker",
                    "--protocol", str(protocol_path), "--output", str(run_folder),
                    "--task", job["task"], "--model", job["model"], "--seed", str(job["seed"])]
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="dispatch_authorized", utc=utc(),
                    job=job, command=command, resources=resources, decision=allowed))
                stream = log.open("x")
                launched = time.perf_counter()
                try:
                    process = subprocess.Popen(command, cwd=ROOT, env=environment,
                        stdout=stream, stderr=subprocess.STDOUT)
                except Exception:
                    stream.close()
                    raise
                pending.pop(0)
                active[process.pid] = (process, stream, job, run_folder, log, command, launched)
                last_dispatch = time.perf_counter()
                append(folder / "RESOURCE_JOURNAL.jsonl", dict(event="dispatched", utc=utc(),
                    namespace_pid=process.pid, job=job, active_workers=len(active)))
            time.sleep(plan["poll_seconds"])
        except Exception as error:
            stopped = True
            write(folder / "SCHEDULER_ERROR.json", dict(utc=utc(), error_type=type(error).__name__,
                error=str(error), traceback=traceback.format_exc(), active_namespace_pids=list(active),
                policy="stop dispatch; drain active; no retry"))
    verified_protocol(protocol_path)
    complete = not stopped and len(records) == len(protocol["jobs"])
    final = dict(status="completed" if complete else "aborted", protocol_sha256=digest,
        records=records, expected=len(protocol["jobs"]), completed=len(records), unstarted=pending,
        failures=sum(row["returncode"] != 0 for row in records),
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall)
    write(output / ("COMPLETE.json" if complete else "ABORTED.json"), final)
    if not complete:
        raise RuntimeError("Fresh cohort aborted; preserve all records and do not fill missing cells")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "control"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=ROOT.parent / "hcsn-runtime")
    parser.add_argument("--public-commit")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--reason", default="")
    parser.add_argument("--authorization", default="")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.protocol.resolve(), args.output.resolve(), args.runtime.resolve())
    elif args.action == "control":
        set_control(args.output.resolve(), args.workers, args.reason, args.authorization)
    else:
        run(args.protocol.resolve(), args.output.resolve(), args.public_commit)
