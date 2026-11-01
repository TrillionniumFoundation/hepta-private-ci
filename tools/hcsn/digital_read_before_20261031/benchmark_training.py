"""Linux whole-process resource measurement for a deterministic training replay.

This wrapper does not change model, data, selection, or optimizer settings.
Primary fitted policies remain the first campaign's frozen final iterates.
Every replay model must be byte-identical before its timings are admitted.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .task import save, sha

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", type=int, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--primary", type=Path, required=True)
    args = parser.parse_args()
    if not hasattr(os, "wait4"):
        raise RuntimeError("Linux wait4 resource measurement required")
    logs = args.runs.resolve()/"logs"
    logs.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "tools.hcsn.digital_read_before_20261031.run_training",
               "--fit", str(args.fit), "--runs", str(args.runs.resolve())]
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    with (logs/f"fit_{args.fit}.log").open("x") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    wall = time.perf_counter()-start
    protocol = json.loads((HERE/"protocol.json").read_text())
    matches = []
    if process.returncode == 0:
        for family in protocol["families"]:
            primary = args.primary/f"fit_{args.fit}"/"models"/f"{family}.json"
            replay = args.runs/f"fit_{args.fit}"/"models"/f"{family}.json"
            matches.append(dict(family=family, primary_sha256=sha(primary), replay_sha256=sha(replay),
                                byte_identical=primary.read_bytes() == replay.read_bytes()))
    record = dict(schema="digital-read-before-process-timing-v1", fit=args.fit,
                  started_at=started_at, finished_at=datetime.now(timezone.utc).isoformat(),
                  command=command, returncode=process.returncode, wall_seconds=wall,
                  user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
                  total_cpu_seconds=usage.ru_utime+usage.ru_stime, peak_rss_kib=usage.ru_maxrss,
                  major_faults=usage.ru_majflt, minor_faults=usage.ru_minflt,
                  voluntary_context_switches=usage.ru_nvcsw, involuntary_context_switches=usage.ru_nivcsw,
                  model_equality=matches, primary_models_unchanged=True,
                  extra_independent_fits=0,
                  scope="Entire child process: interpreter/import, calibration, actual-content cohort preparation, serialization, optimizer, diagnostics, export and shutdown. Parent measurement harness excluded.",
                  rationale="Original fit timers excluded interpreter and outer data serialization. This separate exact reproduction measures those costs; timings are not retroactively attributed to the primary campaign.")
    save(logs/f"fit_{args.fit}_process.json", record)
    if process.returncode != 0 or not all(x["byte_identical"] for x in matches):
        raise RuntimeError("timing replay failed or changed a primary model; retain and reject measurement")
    print(json.dumps(dict(fit=args.fit, total_cpu_seconds=record["total_cpu_seconds"],
                          wall_seconds=wall, all_models_byte_identical=True)), flush=True)


if __name__ == "__main__":
    main()
