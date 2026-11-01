"""Run the registered training/execution addendum after the original stages.

This helper only orders existing commands. It waits for the original bounded
worker launchers to finish so the addendum never adds parallel training load.
Its timers are operational wall time, not additional worker CPU charges.
This operational revision uses the ENOSPC-aware v3 ledger and a fresh output
directory; it does not change any registered model or scientific condition.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


REPO = Path(__file__).resolve().parents[3]
MODULE = "experiments.hcsn_distribution_content_r15_20261101"
PUBLICATION = REPO / "experiments/hcsn_distribution_content_r15_20261101/publication"


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def commands(output, source_commit):
    ledger = output / "RUNTIME_LEDGER_V3.json"
    report = output / "report"
    return [
        ("cross_launch", [sys.executable, "-m", MODULE + ".train_execution_cross", "launch",
                          "--output", str(output), "--workers", "2"]),
        ("cross_index", [sys.executable, "-m", MODULE + ".train_execution_cross", "index",
                         "--output", str(output)]),
        ("runtime_ledger", [sys.executable, str(PUBLICATION / "runtime_ledger_v3.py"), "build",
                            "--results", str(output.parent), "--output", str(ledger)]),
        ("report", [sys.executable, str(PUBLICATION / "build_report.py"), "build",
                    "--run", str(output), "--runtime-ledger", str(ledger),
                    "--output-dir", str(report), "--source-commit", source_commit]),
        ("figures", [sys.executable, str(PUBLICATION / "plot_results.py"), "render",
                     "--review", str(report / "ACCEPTANCE_REVIEW.json"),
                     "--online-index", str(output / "FULL_ONLINE_CONFIRMATION_INDEX.json"),
                     "--output", str(report / "figures")]),
    ]


def run(output, source_commit):
    registration = output / "train_execution_cross/SELF_REGISTRATION.json"
    if not registration.is_file():
        raise ValueError("Register the addendum before launching this continuation")
    dest = output / "operational_addendum_02"
    dest.mkdir(exist_ok=False)
    write(dest / "START.json", dict(utc=utc(), source_commit=source_commit,
          helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          cross_registration_sha256=hashlib.sha256(registration.read_bytes()).hexdigest(),
          note="Ordering helper only; complete original stages before starting two addendum workers."))
    parent = output / "operational_continuation/COMPLETE.json"
    while not parent.is_file():
        time.sleep(10)
    if json.loads(parent.read_text()).get("all_exit_zero") is not True:
        raise ValueError("Original operational stages did not finish successfully")
    rows = []
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    for name, command in commands(output, source_commit):
        row = dict(stage=name, command=command, started_utc=utc())
        print(json.dumps(dict(stage=name, state="starting", utc=row["started_utc"])), flush=True)
        start = time.perf_counter()
        with (dest / (name + ".stdout.log")).open("x") as out, \
                (dest / (name + ".stderr.log")).open("x") as err:
            result = subprocess.run(command, cwd=REPO, env=env, stdout=out, stderr=err)
        row.update(exit_code=result.returncode, finished_utc=utc(),
                   wall_seconds=time.perf_counter()-start)
        rows.append(row)
        write(dest / "STAGES.json", rows)
        print(json.dumps(dict(stage=name, exit_code=result.returncode,
                              wall_seconds=row["wall_seconds"])), flush=True)
        if result.returncode:
            raise RuntimeError("Addendum/reporting stage failed: " + name)
    write(dest / "COMPLETE.json", dict(utc=utc(), stages=len(rows), all_exit_zero=True,
          note="Successful execution does not assert a positive scientific result."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is None:
        parser.error("--source-commit must be a 40-character published Git SHA")
    if args.plan:
        print(json.dumps(commands(args.output.resolve(), args.source_commit), indent=2))
    else:
        run(args.output.resolve(), args.source_commit)
