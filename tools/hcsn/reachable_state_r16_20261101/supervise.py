"""Run each frozen main worker once, retaining process costs and all failures."""

import argparse
import concurrent.futures
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .campaign import PROTOCOL, ROOT, write_new


def worker(seed, domain, folder, commit):
    name = f"{seed}_{domain}"
    argv = [sys.executable, "-m", "tools.hcsn.reachable_state_r16_20261101.campaign",
            "--seed", str(seed), "--domain", domain, "--freeze-commit", commit,
            "--out", str(folder / name)]
    started = time.perf_counter()
    with (folder / "process" / f"{name}.log").open("xb") as log:
        process = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(argv=argv, returncode=process.returncode,
                   elapsed_seconds=time.perf_counter() - started,
                   user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
                   max_rss_kib_linux=usage.ru_maxrss,
                   scope="Whole child process including imports and final serialization; nested worker CPU is not additive")
    write_new(folder / "process" / f"{name}.json", receipt)
    print(json.dumps(dict(worker=name, returncode=process.returncode,
                          cpu_seconds=usage.ru_utime + usage.ru_stime)), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "process").mkdir()
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, seed, domain, folder, args.freeze_commit)
                   for seed, domain in itertools.product(PROTOCOL["fit_seeds"], PROTOCOL["domains"])]
        receipts = [future.result() for future in futures]
    write_new(folder / "SUPERVISOR.json", dict(
        workers=len(receipts), failed=sum(r["returncode"] != 0 for r in receipts),
        child_cpu_seconds=sum(r["user_cpu_seconds"] + r["system_cpu_seconds"] for r in receipts),
        wall_seconds=time.perf_counter() - started, worker_concurrency=4,
        freeze_commit=args.freeze_commit, platform=sys.platform,
        scope="Correctness/utility campaign with process CPU accounting; no isolated deployment throughput claim"))
    if any(r["returncode"] for r in receipts):
        raise SystemExit("At least one worker failed; all unaffected workers were still attempted")


if __name__ == "__main__":
    main()
