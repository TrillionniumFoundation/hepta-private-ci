"""Bounded parallel child processes with per-child OS CPU/RSS receipts."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run_one(stage, fit, root, protocol, training, freeze):
    command = [sys.executable, "-m", "tools.hcsn.digital_mechanisms_20261101.run_study",
               stage, "--fit", str(fit), "--root", str(root), "--protocol", str(protocol)]
    if training is not None:
        command += ["--training", str(training)]
    if freeze is not None:
        command += ["--freeze", str(freeze)]
    logs = root / "process_receipts"
    logs.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with (logs / f"fit_{fit}.stdout").open("xb") as stdout, (logs / f"fit_{fit}.stderr").open("xb") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        pid, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(stage=stage, fit=fit, command=command, pid=pid, returncode=child.returncode,
                   user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
                   whole_process_cpu_seconds=usage.ru_utime + usage.ru_stime,
                   whole_process_wall_seconds=time.perf_counter() - started,
                   peak_rss_kib=usage.ru_maxrss,
                   scope="OS wait4 child including Python imports, setup, all work, serialization and shutdown; Linux RSS units")
    with (logs / f"fit_{fit}.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(receipt), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("development", "train", "confirm"))
    parser.add_argument("--fits", type=int, nargs="+", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if len(set(args.fits)) != len(args.fits) or not 1 <= args.workers <= 8:
        raise ValueError("distinct fits and one to eight workers required")
    args.root.mkdir(parents=True, exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(run_one, args.stage, fit, args.root.resolve(), args.protocol.resolve(),
                            args.training.resolve() if args.training else None,
                            args.freeze.resolve() if args.freeze else None) for fit in args.fits]
        for job in as_completed(jobs):
            result = job.result()
            if result["returncode"]:
                failed.append(result["fit"])
    if failed:
        raise SystemExit("retained failed fit IDs: " + str(failed))


if __name__ == "__main__":
    main()
