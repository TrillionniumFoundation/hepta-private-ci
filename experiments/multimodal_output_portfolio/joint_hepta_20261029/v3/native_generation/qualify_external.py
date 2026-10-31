"""Measure the full qualification child process, including its imports/build.

This standard-library launcher is separate from qualify.py so Torch imports,
compiler invocations, all numerical comparisons, native processes and evidence
writes are inside the observed child-process interval. The tiny outer report
assembly is outside that interval and is not a serving-policy cost claim.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rustc", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Qualification output must be a new directory")
    command = [sys.executable, "-B", "-m",
               "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.native_generation.qualify",
               "--checkpoint", str(args.checkpoint.resolve()), "--output", str(output),
               "--rustc", args.rustc]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True)
    finished = time.perf_counter()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    output.mkdir(parents=True, exist_ok=True)
    (output / "PROCESS.stdout").write_text(result.stdout)
    (output / "PROCESS.stderr").write_text(result.stderr)
    sources = [Path(__file__), Path(__file__).with_name("qualify.py"),
               Path(__file__).parent.parent / "native_bridge.py"]
    report = {"schema": "hepta.native-qualification-whole-process.v3",
              "returncode": result.returncode, "command": command,
              "scope": "whole qualification process including imports, compilation, differential, stream and evidence writes",
              "excluded": "outer standard-library launcher startup and this process-report assembly",
              "wall_seconds": finished - started,
              "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
              "max_child_rss_kib": after.ru_maxrss,
              "rss_scope": "Linux maximum observed individual child RSS, not summed concurrent memory",
              "python_source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              "serving_cost_or_quality_comparison": False}
    (output / "PROCESS.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(result.stdout, end="")
    if result.returncode:
        print(result.stderr, end="", file=sys.stderr)
    print(json.dumps({"whole_process_wall_seconds": report["wall_seconds"],
                      "whole_process_cpu_seconds": report["child_cpu_seconds"],
                      "returncode": result.returncode}))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
