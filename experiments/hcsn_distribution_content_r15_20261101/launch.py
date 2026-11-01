"""Bounded parallel workers with separate wait4 process CPU/RSS receipts."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


MODULE = "experiments.hcsn_distribution_content_r15_20261101"


def launch(output, stage, workers):
    protocol = json.loads((output / "PROTOCOL.json").read_text())
    jobs = [(task, seed, mode) for task in protocol["tasks"] for seed in protocol["seeds"]
            for mode in (["value"] if stage.startswith("recovery_") else protocol["modes"])]
    receipts = output / "receipts" / stage
    receipts.mkdir(parents=True, exist_ok=False)
    active, finished = [], []
    start = time.perf_counter()
    while jobs or active:
        while jobs and len(active) < workers:
            task, seed, mode = jobs.pop(0)
            name = f"{task}_s{seed}_{mode}"
            module, action = ("campaign", "train") if stage == "train" else ("evaluate", "group") if stage == "evaluate" else ("recovery_run", stage.removeprefix("recovery_"))
            command = [sys.executable, "-m", MODULE + "." + module, action,
                       "--output", str(output), "--task", task, "--seed", str(seed)]
            if not stage.startswith("recovery_"):
                command += ["--mode", mode]
            out = (receipts / (name + ".stdout.log")).open("x")
            err = (receipts / (name + ".stderr.log")).open("x")
            process = subprocess.Popen(command, stdout=out, stderr=err)
            active.append(dict(process=process, command=command, name=name, task=task, seed=seed,
                               mode=mode, started=time.perf_counter(), out=out, err=err))
        for job in list(active):
            pid, status, usage = os.wait4(job["process"].pid, os.WNOHANG)
            if not pid:
                continue
            exit_code = os.waitstatus_to_exitcode(status)
            job["process"].returncode = exit_code
            job["out"].close(); job["err"].close()
            row = dict(name=job["name"], task=job["task"], seed=job["seed"], train_mode=job["mode"],
                       command=job["command"], exit_code=exit_code, wall_seconds=time.perf_counter()-job["started"],
                       cpu_user_seconds=usage.ru_utime, cpu_system_seconds=usage.ru_stime,
                       maximum_rss_kib=usage.ru_maxrss)
            (receipts / (job["name"] + ".json")).write_text(json.dumps(row, indent=2) + "\n")
            finished.append(row); active.remove(job)
            print(json.dumps(dict(completed=len(finished), name=job["name"], exit_code=exit_code,
                                  cpu_seconds=usage.ru_utime+usage.ru_stime)), flush=True)
        if active:
            time.sleep(.25)
    total = dict(stage=stage, workers=workers, jobs=len(finished),
                 failed=sum(row["exit_code"] != 0 for row in finished),
                 wall_seconds=time.perf_counter()-start,
                 process_cpu_seconds=sum(row["cpu_user_seconds"]+row["cpu_system_seconds"] for row in finished),
                 note="Worker process CPU includes imports, preparation, training/evaluation, validation and file writes. Nested body timers are not added again.")
    (receipts / "TOTAL.json").write_text(json.dumps(total, indent=2) + "\n")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["train", "evaluate", "recovery_fit", "recovery_confirm"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise ValueError("Use one to eight bounded workers")
    result = launch(args.output, args.stage, args.workers)
    print(json.dumps(result))
    raise SystemExit(int(result["failed"] != 0))
