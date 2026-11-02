"""Assign one fresh ordinary process subtree to one measured research stage.

Only the outer wait4 CPU belongs in the phase ledger. The nested stable v9
meter supplies diagnostics; adding those again would count the same work twice.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INNER = ROOT / "experiments/hcsn_v9_followup_20261101/economics/family_cost.py"
STAGES = ("prepare", "train", "execute", "audit", "validation", "combined_train_execute", "capability")


def run_stage(study, stage, attempt, out, command, timeout=900):
    if stage not in STAGES or not study or attempt < 1:
        raise ValueError("Named study, supported phase and positive attempt required")
    if not command or not all(isinstance(x, str) and x for x in command):
        raise ValueError("Nonempty command argument vector required")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    command = list(command)
    configuration = {"study": study, "stage": stage, "attempt": attempt, "command": command,
                     "timeout_seconds": timeout, "inner_meter": str(INNER),
                     "inner_meter_sha256": hashlib.sha256(INNER.read_bytes()).hexdigest(),
                     "stage_meter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out / "CONFIG.json").write_text(json.dumps(configuration, indent=2) + "\n")
    # The reservation is local to this attempt and prevents accidental concurrent reuse.
    with (out / "RUNNING.lock").open("x") as lock, (out / "meter.log").open("wb") as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        began = time.monotonic_ns()
        child = subprocess.Popen([sys.executable, str(INNER), "--out", str(out / "inner"),
                                  "--interval", "0.10", "--timeout", str(timeout), "--", *command],
                                 stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        ended = time.monotonic_ns()
    inner_path = out / "inner/RECEIPT.json"
    inner = json.loads(inner_path.read_text()) if inner_path.exists() else None
    outer_cpu = usage.ru_utime + usage.ru_stime
    inner_cpu = inner["enclosing_observed_cpu_seconds"] if inner else None
    row = {"schema": "hcsn-v10-disjoint-phase-cost.v1", **configuration,
           "boundary_begin_ns": began, "boundary_end_ns": ended,
           "outer_wait4_cpu_seconds": outer_cpu, "outer_user_cpu_seconds": usage.ru_utime,
           "outer_system_cpu_seconds": usage.ru_stime, "wall_seconds": (ended - began) / 1e9,
           "outer_largest_process_hwm_bytes": usage.ru_maxrss * 1024,
           "inner_task_cpu_seconds_diagnostic": inner["task_cpu_seconds"] if inner else None,
           "inner_monitor_cpu_seconds_diagnostic": inner["measurement_cpu_seconds"] if inner else None,
           "meter_bootstrap_and_serialization_cpu_seconds_diagnostic":
               outer_cpu - inner_cpu if inner_cpu is not None else None,
           "exit_code": child.returncode,
           "complete_ordinary_waitable_cpu": bool(inner and inner["cpu_complete_for_ordinary_waitable_family"]),
           "success": child.returncode == 0 and bool(inner and inner["task_success"]),
           "inner_receipt_sha256": hashlib.sha256(inner_path.read_bytes()).hexdigest() if inner else None,
           "accounting_rule": "Only outer_wait4_cpu_seconds is additive across disjoint phase receipts; all inner fields are already included diagnostics",
           "boundary": "Before fresh inner-meter process creation through its wait4 exit; includes its interpreter/import/probes, command startup/all waited descendants, sampling, and inner receipt serialization",
           "outside_boundary": "Stage launcher imports, CONFIG and final PHASE_RECEIPT serialization, code authoring/tool transfer, and any unrecorded historical work",
           "historical_preparation_cpu_seconds": None, "device_energy_joules": None,
           "continuous_exact_family_memory_peak_bytes": None,
           "memory_scope": "outer ru_maxrss is a largest-process high-water diagnostic, never a process-family sum or simultaneous peak"}
    (out / "PHASE_RECEIPT.json").write_text(json.dumps(row, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"study": study, "stage": stage, "attempt": attempt,
                      "success": row["success"], "outer_wait4_cpu_seconds": outer_cpu,
                      "out": str(out)}), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    row = run_stage(args.study, args.stage, args.attempt, args.out, command, args.timeout)
    return 0 if row["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
