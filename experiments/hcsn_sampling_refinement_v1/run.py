"""Single-worker, source-verified refinement queue; no training or retries."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .common import HERE, ROOT, read, write, sha, utc, verify
from experiments.hcsn_risk_memory_v1.resource_accounting import measurement, anonymous_credit


MEMORY = ROOT / "experiments/hcsn_risk_memory_v1/results/memory_profile002"


def append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")


def resources(protocol):
    plan = read(MEMORY / "EXECUTION_PLAN/PLAN.json")
    control = read(MEMORY / "EXECUTION_PLAN/CONTROL.json")
    launch = read(MEMORY / "EXECUTION_PLAN/LAUNCH.json")
    journal = MEMORY / "EXECUTION_PLAN/RESOURCE_JOURNAL.jsonl"
    before = journal.stat().st_mtime_ns
    active = set()
    for line in journal.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return dict(allowed=False, reason="partial resource-journal write")
        if event["event"] == "dispatched": active.add(event["namespace_pid"])
        elif event["event"] == "reaped": active.discard(event["namespace_pid"])
    credits = [anonymous_credit(pid, launch["host_pid"]) for pid in sorted(active)]
    terminal = (MEMORY / "COMPLETE.json").exists() or (MEMORY / "ABORTED.json").exists()
    desired = 0 if terminal else control["desired_workers"]
    budget = plan["per_worker_peak_budget_bytes"]
    future = sum(max(0, budget-row["credited_anon_bytes"]) for row in credits)
    future += max(0, desired-len(active)) * budget
    current = measurement()
    remaining = current["estimated_headroom_bytes"] - future - protocol["resource"]["worker_budget_bytes"]
    stable = before == journal.stat().st_mtime_ns
    return dict(allowed=stable and remaining >= protocol["resource"]["shared_reserve_bytes"], utc=utc(),
        memory_active_workers=len(active), memory_desired_workers=desired, memory_terminal=terminal,
        memory_future_reservation_bytes=future, memory_verified_credits=credits,
        new_worker_budget_bytes=protocol["resource"]["worker_budget_bytes"],
        remaining_shared_reserve_bytes=remaining, required_shared_reserve_bytes=protocol["resource"]["shared_reserve_bytes"],
        journal_snapshot_stable=stable, resources=current)


def child(command, log, environment):
    started = time.perf_counter()
    before = measurement()
    with log.open("x") as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        while True:
            got, status, usage = os.wait4(process.pid, os.WNOHANG)
            if got: break
            time.sleep(.5)
    code = os.waitstatus_to_exitcode(status)
    process.returncode = code
    after = measurement()
    return dict(command=command, returncode=code, log_sha256=sha(log),
        child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
        child_total_cpu_seconds=usage.ru_utime+usage.ru_stime, child_peak_rss_bytes=usage.ru_maxrss*1024,
        wall_seconds=time.perf_counter()-started, resources_before=before, resources_after=after,
        oom_counters_unchanged=all(before["events"][key]==after["events"][key] for key in ("oom", "oom_kill")))


def run(output, public_commit, authorization):
    if not re.fullmatch("[0-9a-f]{40}", public_commit) or not authorization:
        raise ValueError("Root public seal and explicit shared-resource authorization required")
    protocol = read(HERE / "PROTOCOL.json")
    verify(protocol)
    registration = read(output / "REGISTRATION.json")
    if registration["protocol_sha256"] != sha(HERE / "PROTOCOL.json") or registration["freeze_sha256"] != sha(HERE / "FREEZE.json"):
        raise ValueError("Local freeze identity differs")
    write(output / "PUBLIC_SEAL.json", dict(public_commit=public_commit, root_supplied_seal=True,
        received_utc=utc(), protocol_sha256=registration["protocol_sha256"], freeze_sha256=registration["freeze_sha256"]))
    write(output / "RUN_PLAN.json", dict(started_utc=utc(), public_commit=public_commit,
        authorization=authorization, source_sha256=sha(Path(__file__)), workers=1,
        resource_policy=protocol["resource"], jobs=protocol["jobs"], no_retries=True))
    environment = dict(os.environ, PYTHONPATH=str(ROOT.parent / "hcsn-runtime"),
        OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    started, records, stopped = time.perf_counter(), [], False
    for job in protocol["jobs"]:
        while True:
            decision = resources(protocol)
            append(output / "RESOURCE_JOURNAL.jsonl", decision)
            if decision["allowed"]: break
            time.sleep(5)
        verify(protocol)
        command = [sys.executable, "-m", "experiments.hcsn_sampling_refinement_v1.study", "worker",
            "--output", str(output), "--model", job["model"], "--seed", str(job["seed"])]
        receipt = child(command, output / f"{job['model']}__{job['seed']}.log", environment)
        records.append(dict(job=job, **receipt))
        append(output / "CHILDREN.jsonl", records[-1])
        print(json.dumps(dict(model=job["model"], seed=job["seed"], completed_workers=len(records),
            returncode=receipt["returncode"], cpu_seconds=receipt["child_total_cpu_seconds"],
            peak_rss_bytes=receipt["child_peak_rss_bytes"])), flush=True)
        if receipt["returncode"] or not receipt["oom_counters_unchanged"] or receipt["child_peak_rss_bytes"] > protocol["resource"]["worker_budget_bytes"]:
            stopped = True
            break
    if not stopped:
        command = [sys.executable, "-m", "experiments.hcsn_sampling_refinement_v1.study", "analyze", "--output", str(output)]
        receipt = child(command, output / "analysis.log", environment)
        records.append(dict(stage="analysis", **receipt))
        append(output / "CHILDREN.jsonl", records[-1])
        stopped = receipt["returncode"] != 0
    verify(protocol)
    write(output / ("ABORTED.json" if stopped else "COMPLETE.json"), dict(completed=not stopped,
        records=records, full_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds_including_imports=time.process_time(), wall_seconds=time.perf_counter()-started,
        maximum_worker_peak_rss_bytes=max(row["child_peak_rss_bytes"] for row in records),
        cpu_scope="Complete wait4 child processes plus coordinator; nested factor costs are not added", energy_joules=None))
    if stopped: raise RuntimeError("Refinement queue stopped; preserve all attempts and costs")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--public-commit",required=True)
    parser.add_argument("--authorization",required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(HERE / "results"): raise ValueError("New isolated results directory required")
    run(output,args.public_commit,args.authorization)
