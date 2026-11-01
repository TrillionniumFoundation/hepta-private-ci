"""Run the already registered stages, in order, after all training jobs finish.

This operational helper changes no scientific source, protocol or data. It
refuses partial/failed training and never skips a failed stage. Child launchers
own the CPU receipts; the wall times here are not additional compute costs.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


MODULE = "experiments.hcsn_distribution_content_r15_20261101"
REPOSITORY = Path(__file__).resolve().parents[3]


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def check_freeze(output):
    freeze = json.loads((output / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        if hashlib.sha256((REPOSITORY / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen source changed: " + name)
    for name, field in [("PROTOCOL.json", "protocol_sha256"),
                        ("TRAINING_DATA_CONTEXTS.json", "training_data_contexts_sha256")]:
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != freeze[field]:
            raise ValueError("Frozen registration changed: " + name)


def commands(output):
    stages = [
        ("training_index", "campaign", ["index"]),
        ("recovery_prepare", "recovery_run", ["prepare"]),
        ("recovery_fit", "launch", ["recovery_fit", "--workers", "2"]),
        ("recovery_freeze", "recovery_run", ["freeze"]),
        ("main_evaluate", "launch", ["evaluate", "--workers", "2"]),
        ("main_index", "evaluate", ["index"]),
        ("online_confirm", "online_confirm", ["launch", "--workers", "2"]),
        ("online_index", "online_confirm", ["index"]),
        ("recovery_confirm", "launch", ["recovery_confirm", "--workers", "2"]),
        ("recovery_aggregate", "recovery_run", ["aggregate"]),
        ("independent_audit", "audit", ["--run", str(output)]),
        ("frozen_summary", "summarize", []),
    ]
    result = []
    for name, module, args in stages:
        target = output / "INDEPENDENT_AUDIT.json" if name == "independent_audit" else output
        result.append((name, [sys.executable, "-m", MODULE + "." + module,
                              *args, "--output", str(target)]))
    return result


def continue_run(output, wait_for_training):
    check_freeze(output)
    registration = output / "full_online_confirmation" / "SELF_REGISTRATION.json"
    if not registration.is_file():
        raise ValueError("The full online confirmation addendum must be registered first")
    record = output / "operational_continuation"
    record.mkdir(exist_ok=False)
    write(record / "START.json", dict(utc=utc(), output=str(output),
          helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          online_registration_sha256=hashlib.sha256(registration.read_bytes()).hexdigest(),
          note="Operational ordering only; no changed protocol or scientific source."))
    total_path = output / "receipts" / "train" / "TOTAL.json"
    while not total_path.is_file():
        if not wait_for_training:
            raise ValueError("Training is not complete")
        time.sleep(10)
    training = json.loads(total_path.read_text())
    protocol = json.loads((output / "PROTOCOL.json").read_text())
    expected = {f"{task}_s{seed}_{mode}" for task in protocol["tasks"]
                for seed in protocol["seeds"] for mode in protocol["modes"]}
    actual = {p.parent.name for p in output.glob("fits/*/SUMMARY.json")}
    if training["failed"] or training["jobs"] != len(expected) or actual != expected:
        write(record / "BLOCKED_TRAINING.json", dict(utc=utc(), training=training,
              missing=sorted(expected-actual), unexpected=sorted(actual-expected)))
        raise ValueError("Training failed or its completed groups do not match the registration")
    rows = []
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    for name, command in commands(output):
        check_freeze(output)
        row = dict(stage=name, command=command, started_utc=utc())
        print(json.dumps(dict(stage=name, state="starting", utc=row["started_utc"])), flush=True)
        start = time.perf_counter()
        with (record / (name + ".stdout.log")).open("x") as out, \
                (record / (name + ".stderr.log")).open("x") as err:
            process = subprocess.run(command, cwd=REPOSITORY, env=env, stdout=out, stderr=err)
        row.update(exit_code=process.returncode, wall_seconds=time.perf_counter()-start,
                   finished_utc=utc())
        rows.append(row)
        write(record / "STAGES.json", rows)
        print(json.dumps(dict(stage=name, state="complete", exit_code=process.returncode,
                              wall_seconds=row["wall_seconds"])), flush=True)
        if process.returncode:
            raise RuntimeError("Registered stage failed: " + name)
    write(record / "COMPLETE.json", dict(utc=utc(), stages=len(rows), all_exit_zero=True,
          note="Exit success is an execution result, not a claim of scientific benefit."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-for-training", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.plan:
        check_freeze(output)
        print(json.dumps(commands(output), indent=2))
    else:
        continue_run(output, args.wait_for_training)
