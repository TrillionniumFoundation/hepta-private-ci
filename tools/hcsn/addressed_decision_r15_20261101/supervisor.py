"""Linux research launcher: meter complete child CPU, imports and final I/O."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = "tools.hcsn.addressed_decision_r15_20261101.campaign"


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def launch(kind, run, commit, workers=4, development=False):
    if not hasattr(os, "wait4"):
        raise RuntimeError("This metering launcher explicitly requires POSIX wait4 (Linux run)")
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    seeds = [999] if development else protocol["seeds"]
    run = Path(run).resolve()
    jobs = [(seed, domain) for seed in seeds for domain in
            ([None] if kind == "train" else ["iid", "ood"])]
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    active, receipts, failures = {}, [], []
    env = os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    write_new(run / "supervisor" / f"{kind}_launch.json", dict(
        kind=kind, commit=commit, jobs=jobs, workers=workers, development=development,
        opened_at=datetime.now(timezone.utc).isoformat(), single_thread_libraries=True))
    while jobs or active:
        while jobs and len(active) < workers:
            seed, domain = jobs.pop(0)
            name = f"{kind}_{seed}" + (f"_{domain}" if domain else "")
            command = [sys.executable, "-m", MODULE, kind, "--run", str(run),
                       "--seed", str(seed),
                       "--source-commit" if kind == "train" else "--freeze-commit", commit]
            if domain:
                command += ["--domain", domain]
            if development:
                command.append("--development")
            logfile = run / "logs" / f"{name}.log"
            logfile.parent.mkdir(parents=True, exist_ok=True)
            stream = logfile.open("xb")
            proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT)
            active[proc.pid] = (proc, stream, time.perf_counter(), seed, domain, name, command)
        pid, status, usage = os.wait4(-1, os.WNOHANG)
        if not pid:
            time.sleep(.2)
            continue
        proc, stream, began, seed, domain, name, command = active.pop(pid)
        proc.returncode = os.waitstatus_to_exitcode(status)
        stream.close()
        receipt = dict(kind=kind, seed=seed, domain=domain, command=command,
                       exit_code=proc.returncode, user_cpu_seconds=usage.ru_utime,
                       system_cpu_seconds=usage.ru_stime,
                       total_cpu_seconds=usage.ru_utime + usage.ru_stime,
                       peak_rss_kib=usage.ru_maxrss, wall_seconds=time.perf_counter() - began,
                       completed_at=datetime.now(timezone.utc).isoformat(),
                       cpu_scope="Entire isolated worker including import, output JSON/gzip/fsync",
                       platform_scope="Linux ru_maxrss in KiB; CPU library threads fixed to one")
        write_new(run / "supervisor" / f"{name}.json", receipt)
        receipts.append(receipt)
        print(json.dumps({key: receipt[key] for key in
              ("kind", "seed", "domain", "exit_code", "total_cpu_seconds", "wall_seconds")}), flush=True)
        if proc.returncode:
            failures.append(name)
    summary = dict(kind=kind, receipts=len(receipts), failed=failures,
                   child_cpu_seconds=sum(r["total_cpu_seconds"] for r in receipts),
                   supervisor_cpu_seconds=time.process_time() - started_cpu,
                   wall_seconds=time.perf_counter() - started_wall)
    write_new(run / "supervisor" / f"{kind}_summary.json", summary)
    if failures:
        raise RuntimeError(f"Workers failed; preserve their logs and do not refit silently: {failures}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("train", "confirm"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    print(json.dumps(launch(args.kind, args.run, args.commit, args.workers, args.development)))


if __name__ == "__main__":
    main()
