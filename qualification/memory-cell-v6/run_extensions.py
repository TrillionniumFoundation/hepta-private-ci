"""Run every predeclared learning, transfer and lifecycle seed; retain failures."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import time
import traceback

from v6.contracts import canonical
from v6.learning import run_learning_study
from v6.lifecycle import run_lifecycle_study
from v6.transfer import run_transfer_study


def run(output, plan):
    output, plan = Path(output).absolute(), Path(plan).absolute()
    project = Path(__file__).resolve().parent
    repo = project.parents[1]
    configuration = json.loads(plan.read_bytes())
    source_paths = [Path(__file__), *(project / "v6").glob("*.py")]
    source_hashes = {}
    for path in source_paths:
        relative = str(path.relative_to(repo))
        committed = subprocess.check_output(["git", "show", "HEAD:" + relative], cwd=repo)
        if committed != path.read_bytes():
            raise ValueError("commit the frozen execution source before running: " + relative)
        source_hashes[relative] = hashlib.sha256(committed).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    source = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "files": source_hashes,
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seeds": configuration["seeds"],
    }
    (output / "SOURCE.json").write_bytes(canonical(source) + b"\n")
    results = []
    started, cpu = time.perf_counter(), time.process_time()
    for seed in configuration["seeds"]:
        for name, function in (
            ("learning", run_learning_study),
            ("transfer", run_transfer_study),
            ("lifecycle", run_lifecycle_study),
        ):
            path = output / f"seed-{seed}" / name
            path.parent.mkdir(exist_ok=True)
            wall, processor = time.perf_counter(), time.process_time()
            status, failure = "completed", None
            try:
                function(seed, path)
            except Exception:
                status, failure = "failed", traceback.format_exc()
                path.mkdir(exist_ok=True)
                (path / "FAILURE.txt").write_text(failure)
            record = {
                "seed": seed,
                "study": name,
                "status": status,
                "directory": str(path.relative_to(output)),
                "wall_seconds": time.perf_counter() - wall,
                "parent_cpu_seconds": time.process_time() - processor,
                "retained_bytes": sum(file.stat().st_size for file in path.rglob("*") if file.is_file()),
            }
            results.append(record)
            (output / "PROGRESS.json").write_bytes(canonical(results) + b"\n")
            print(json.dumps(record), flush=True)
    report = {
        "schema": "hepta.memory.v6.extensions-execution.v1",
        "source": source,
        "runs": results,
        "all_completed": all(item["status"] == "completed" for item in results),
        "wall_seconds": time.perf_counter() - started,
        "parent_cpu_seconds": time.process_time() - cpu,
        "linux_peak_parent_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "linux_peak_child_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "rss_scope": "process high-water marks, not concurrent aggregate or steady-state model memory",
        "retained_bytes_before_report": sum(file.stat().st_size for file in output.rglob("*") if file.is_file()),
    }
    (output / "EXECUTION.json").write_bytes(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", default=Path(__file__).with_name("PROTOCOL.json"), type=Path)
    arguments = parser.parse_args()
    result = run(arguments.output, arguments.plan)
    raise SystemExit(0 if result["all_completed"] else 1)
