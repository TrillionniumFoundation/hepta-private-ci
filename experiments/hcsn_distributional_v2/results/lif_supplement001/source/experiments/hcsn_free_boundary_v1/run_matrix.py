"""Freeze identities, then execute every predeclared search without outcome tuning."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def jobs(protocol):
    declared = set()
    for section in ("core", "mechanism"):
        config = protocol[section]
        declared.update((task, model, seed) for task in config["tasks"]
                        for model in config["models"] for seed in config["seeds"])
    result = sorted(declared)
    random.Random(protocol["execution"]["job_shuffle_seed"]).shuffle(result)
    priority = [(row["task"], row["model"], row["seed"])
                for row in protocol["execution"].get("priority_jobs", [])]
    if any(job not in declared for job in priority):
        raise ValueError("Priority job must already belong to the declared matrix")
    result = priority + [job for job in result if job not in priority]
    if len(result) != protocol["execution"]["expected_searches"]:
        raise ValueError("Protocol job count disagrees with actual declaration")
    return result


def freeze(protocol_path, data_directory, output):
    """A frozen source/data manifest cannot be overwritten by this runner."""
    protocol_path, data_directory, output = map(Path, (protocol_path, data_directory, output))
    if output.exists():
        raise FileExistsError(f"Freeze already exists: {output}")
    files = [protocol_path, Path(__file__)]
    files.extend(PACKAGE / name for name in (
        "model.py", "oracle.py", "oracle_torch.py", "benchmark_models.py", "training.py",
        "datasets.py", "CONTRACT.md", "MATH.md", "native_bridge.py", "run_native_live.py",
        "live_study.py", "restore_native.py", "vendor/cfc_cell.py", "vendor/LICENSE.ncps", "vendor/PROVENANCE.json"))
    inherited = REPO / "experiments" / "continuous_spiking_network"
    files.extend(inherited / name for name in (
        "__init__.py", "baseline.py", "cell.py", "data.py", "kernels.py", "models.py", "records.py"))
    files.extend(sorted(data_directory.glob("*.json")))
    files.extend(sorted(data_directory.glob("*.npz")))
    protocol = json.loads(protocol_path.read_text())
    manifest = {"schema": "hcsn-study-freeze.v1",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "base_commit": protocol["base_commit"],
                "protocol_path": str(protocol_path.resolve().relative_to(REPO)),
                "data_directory": str(data_directory.resolve().relative_to(REPO)),
                "files": {str(path.resolve().relative_to(REPO)): digest(path) for path in files},
                "jobs": [{"task": task, "model": model, "seed": seed} for task, model, seed in jobs(protocol)],
                "outcomes_available": False}
    manifest["identity_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    write_json(output, manifest)
    return manifest


def verify(manifest):
    mismatches = [path for path, expected in manifest["files"].items()
                  if not (REPO / path).is_file() or digest(REPO / path) != expected]
    if mismatches:
        raise ValueError(f"Frozen study files changed: {mismatches}")


def _run_one(job, protocol, manifest, destination):
    task, model, seed = job["task"], job["model"], job["seed"]
    directory = destination / "runs" / task / model / str(seed)
    if (directory / "summary.json").exists():
        return {**job, "status": "previously_completed", "directory": str(directory.relative_to(destination))}
    if directory.exists() and any(directory.iterdir()):
        return {**job, "status": "preserved_incomplete", "directory": str(directory.relative_to(destination))}
    # Data identities were checked once before execution and are rehashed inside
    # each search before holdout use; code is checked before every new subprocess.
    for path, expected in manifest["files"].items():
        if not path.endswith(".npz") and digest(REPO / path) != expected:
            raise ValueError(f"Frozen source changed while scheduling: {path}")
    config = protocol["optimization"]
    data = REPO / manifest["data_directory"] / f"{task}.npz"
    command = [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.training",
               "--data", str(data), "--model", model, "--seed", str(seed),
               "--output", str(directory), "--cpu-seconds", str(config["training_cpu_seconds_per_lr"]),
               "--width", str(config["width"]), "--depth", str(config["depth"]),
               "--batch-size", str(config["batch_size"]), "--max-updates", str(config["max_updates"])]
    environment = dict(os.environ)
    environment.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                       PYTHONDONTWRITEBYTECODE="1")
    logs = destination / "process_logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"{task}--{model}--{seed}.log"
    start = time.perf_counter()
    child_cpu, child_rss = None, None
    with log_path.open("w") as log:
        with subprocess.Popen(command, cwd=REPO, env=environment,
                              stdout=log, stderr=subprocess.STDOUT) as process:
            if hasattr(os, "wait4"):
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                child_cpu = usage.ru_utime + usage.ru_stime
                child_rss = int(usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024)
            else:
                process.wait()
            returncode = process.returncode
    record = {**job, "status": "completed" if returncode == 0 else "failed",
              "returncode": returncode, "wall_seconds": time.perf_counter() - start,
              "child_cpu_seconds": child_cpu, "whole_child_peak_rss_bytes": child_rss,
              "cpu_scope": "complete process including imports, setup, two LR searches, validation, IO and heldout evaluation",
              "directory": str(directory.relative_to(destination)), "log": str(log_path.relative_to(destination))}
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "EXECUTION.json", record)
    return record


def execute(freeze_path, destination, workers=3):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(freeze_path).read_text())
    verify(manifest)
    protocol = json.loads((REPO / manifest["protocol_path"]).read_text())
    if workers < 1 or workers > protocol["execution"]["parallel_workers"]:
        raise ValueError("Worker count must respect the frozen maximum")
    existing = destination / "IDENTITY.json"
    if existing.exists() and json.loads(existing.read_text())["identity_sha256"] != manifest["identity_sha256"]:
        raise ValueError("Output directory belongs to a different frozen study")
    write_json(existing, manifest)
    results, start = [], time.perf_counter()
    parent_start = time.process_time()
    try:
        import resource
        child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    except ImportError:
        child_start = None
    queue = iter(manifest["jobs"])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        for _ in range(workers):
            job = next(queue, None)
            if job is not None:
                pending[pool.submit(_run_one, job, protocol, manifest, destination)] = job
        while pending:
            done, _ = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                try:
                    result = future.result()
                except Exception as error:
                    result = {**job, "status": "scheduler_failure", "error": str(error)}
                results.append(result)
                progress = {"identity_sha256": manifest["identity_sha256"],
                            "scheduled_searches": len(manifest["jobs"]), "finished_searches": len(results),
                            "statuses": {status: sum(row["status"] == status for row in results)
                                         for status in sorted({row["status"] for row in results})},
                            "wall_seconds": time.perf_counter() - start, "results": results}
                write_json(destination / "PROGRESS.json", progress)
                print(json.dumps({"finished": len(results), "total": len(manifest["jobs"]),
                                  **{key: result[key] for key in ("task", "model", "seed", "status")}}), flush=True)
                following = next(queue, None)
                if following is not None:
                    pending[pool.submit(_run_one, following, protocol, manifest, destination)] = following
    verify(manifest)
    progress["scheduler_cpu_seconds"] = time.process_time() - parent_start
    if child_start is not None:
        child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        progress["all_child_process_cpu_seconds"] = (
            child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime)
        progress["child_cpu_scope"] = "all search subprocesses including Python/Torch import, startup, fitting, validation, checkpoints and holdouts"
    else:
        progress["all_child_process_cpu_seconds"] = None
    write_json(destination / "COMPLETE.json", progress)
    return progress


def main():
    parser = argparse.ArgumentParser()
    command = parser.add_subparsers(dest="command", required=True)
    make = command.add_parser("freeze")
    make.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    make.add_argument("--data", type=Path, default=PACKAGE / "data/study001")
    make.add_argument("--output", type=Path, default=PACKAGE / "FREEZE.json")
    run = command.add_parser("run")
    run.add_argument("--freeze", type=Path, default=PACKAGE / "FREEZE.json")
    run.add_argument("--output", type=Path, default=PACKAGE / "results/study001")
    run.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.command == "freeze":
        print(json.dumps(freeze(args.protocol, args.data, args.output), indent=2))
    else:
        execute(args.freeze, args.output, args.workers)


if __name__ == "__main__":
    main()
