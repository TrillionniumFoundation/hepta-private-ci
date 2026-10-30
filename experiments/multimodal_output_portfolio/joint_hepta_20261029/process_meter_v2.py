"""Linux whole-process research metering, including interpreter startup and exit.

This receipt complements per-episode service costs. It is not an instruction to
add a whole training run to every delivery or to count episode CPU twice.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


PACKAGE = "experiments.multimodal_output_portfolio.joint_hepta_20261029"
MODULES = ("controller_v2", "observer_v2")
TARIFF = {"cpu_second": 0.02, "wall_second": 0.001}


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_snapshot(root):
    """Bind relevant executable bytes; historical results are not executable inputs."""
    root = Path(root)
    base = root / "experiments/multimodal_output_portfolio"
    files = []
    for name in ("joint_hepta_20261029", "unified_20261028", "closure_20261028"):
        directory = base / name
        files.extend(directory.glob("*.py"))
        files.extend(directory.glob("*.json"))
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(set(files))}
    if not hashes:
        raise ValueError("Research source tree is absent")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                            text=True, capture_output=True)
    return {"commit": result.stdout.strip(), "files": hashes,
            "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True,
                         separators=(",", ":")).encode()).hexdigest()}


def meter_command(command, directory, *, timeout_seconds, environment=None):
    """Reap exactly our process; failed and timed-out work remains in the receipt.

Linux wait4 includes descendants already reaped by the child. Descendants must
not be detached; registered study entry points wait for their codec children.
"""
    if sys.platform != "linux" or not hasattr(os, "wait4"):
        raise RuntimeError("This process resource meter requires Linux wait4")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("A positive process deadline is required")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    start_wall = time.monotonic()
    own = resource.getrusage(resource.RUSAGE_SELF)
    start_cpu = own.ru_utime + own.ru_stime
    started_at = datetime.now(timezone.utc).isoformat()
    timed_out = False
    escalated = False
    with (directory / "process.log").open("xb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=environment, start_new_session=True)
        terminated_at = None
        while True:
            waited, status, usage = os.wait4(process.pid, os.WNOHANG)
            if waited:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            now = time.monotonic()
            if now - start_wall >= timeout_seconds and terminated_at is None:
                timed_out = True
                terminated_at = now
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # It exited between wait4 and the deadline check; reap next.
            elif terminated_at is not None and now - terminated_at >= 10 and not escalated:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                escalated = True
            time.sleep(0.05)
    own = resource.getrusage(resource.RUSAGE_SELF)
    cpu_child = usage.ru_utime + usage.ru_stime
    cpu_supervisor = own.ru_utime + own.ru_stime - start_cpu
    wall = time.monotonic() - start_wall
    result = {
        "schema": "hepta.joint-process-meter.v2", "started_at_utc": started_at,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command, "exit_code": process.returncode, "timed_out": timed_out,
        "sigkill_required": escalated, "child_reaped": True,
        "child_cpu_seconds": cpu_child, "supervisor_cpu_seconds": cpu_supervisor,
        "wall_seconds": wall, "child_peak_rss_bytes": usage.ru_maxrss * 1024,
        "process_log_sha256": hashlib.sha256((directory / "process.log").read_bytes()).hexdigest(),
        "tariff": TARIFF,
        "measured_process_tariff_cost": (cpu_child + cpu_supervisor) * TARIFF["cpu_second"]
                                         + wall * TARIFF["wall_second"],
        "scope": "Child interpreter startup, imports, model loading, all executed study phases, exit and reaped descendants; active supervisor measured separately",
        "excluded": ["Environment provisioning and package installation", "Supervisor interpreter startup before meter entry", "External infrastructure and acquisition fees"],
        "episode_costs_are_subtotals_not_additional_process_cost": True,
        "detached_descendant_cpu_not_supported": True,
        "descendant_accounting_complete_under_registered_reaping_contract": not timed_out and process.returncode == 0,
        "abnormal_exit_cost_is_only_measured_lower_bound": timed_out or process.returncode != 0,
        "abnormal_exit_limit": "An interrupted parent may not have reaped its active codec children; their missing CPU is not estimated as zero",
        "physical_resource_tail_bound_proved": False,
        "lifetime_savings_qualified": False,
    }
    write_new(directory / "PROCESS_RECEIPT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", choices=MODULES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=5400)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if args.output.exists():
        raise FileExistsError("A new run directory is required; evidence may not be overwritten")
    extra = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    if any(value == "--output" or value.startswith("--output=") for value in extra):
        raise ValueError("The meter owns the child output directory")
    before = source_snapshot(root)
    command = [sys.executable, "-B", "-m", f"{PACKAGE}.{args.module}",
               "--output", str(args.output.resolve() / "run"), *extra]
    report = meter_command(command, args.output, timeout_seconds=args.timeout_seconds)
    after = source_snapshot(root)
    write_new(args.output / "SOURCE_RECEIPT.json", {
        "before": before, "after": after,
        "source_bytes_unchanged": before == after,
        "immutable_public_registration_required_for_confirmation": True,
    })
    print(json.dumps({"output": str(args.output), "exit_code": report["exit_code"],
                      "process_cost": report["measured_process_tariff_cost"],
                      "source_unchanged": before == after}, sort_keys=True), flush=True)
    return report["exit_code"] if report["exit_code"] else int(before != after)


if __name__ == "__main__":
    raise SystemExit(main())
