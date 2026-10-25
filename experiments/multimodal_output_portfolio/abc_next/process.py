"""Measure a complete registered experiment subprocess, including Python startup."""

import argparse
import importlib.util
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

from ..abc_recovery.base_recovery import file_sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.module.startswith("experiments.multimodal_output_portfolio.abc_next."):
        raise ValueError("Only this experiment's modules can be measured")
    spec = importlib.util.find_spec(args.module)
    if spec is None or spec.origin is None:
        raise ValueError("Experiment entrypoint is unavailable")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    log_path = args.receipt.with_suffix(".log")
    registration = args.receipt.with_suffix(".registration.json")
    if any(path.exists() for path in (args.receipt, log_path, registration)):
        raise FileExistsError("Process receipts and logs are immutable")
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    command = [sys.executable, "-B", "-m", args.module, *arguments]
    write_json(registration, {
        "schema": "hepta.abc-next.process-registration.v1", "unix_ns": time.time_ns(),
        "command": command, "entrypoint_sha256": file_sha(Path(spec.origin)),
        "wrapper_sha256": file_sha(Path(__file__)), "working_directory": str(Path.cwd())})
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    with log_path.open("x") as log:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        returncode = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "schema": "hepta.abc-next.process-receipt.v1", "exit_code": returncode,
        "registration_sha256": file_sha(registration), "log_sha256": file_sha(log_path),
        "wall_ns": time.perf_counter_ns() - wall, "wrapper_cpu_ns": time.process_time_ns() - cpu,
        "child_cpu_ns": round(1e9 * (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime)),
        "child_maximum_rss_bytes": after.ru_maxrss * 1024,
        "scope": "subprocess launch through exit and log flush; includes imports, fitting and child serialization; excludes this final receipt write"}
    write_json(args.receipt, result)
    print(json.dumps(result), flush=True)
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
