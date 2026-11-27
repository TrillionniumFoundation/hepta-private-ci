"""Small POSIX controller: fixed jobs, actual child costs, retained retries.

The controller imports only the standard library, keeping the tensor runtime
out of the parent. CPU-budget worker reproducibility is specified in study.py.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def resource_headroom():
    root = Path("/sys/fs/cgroup")
    try:
        maximum = (root / "memory.max").read_text().strip()
        current = int((root / "memory.current").read_text())
        statistics = {
            line.split()[0]: int(line.split()[1])
            for line in (root / "memory.stat").read_text().splitlines()
        }
        # Inactive file cache is reclaimable; tmpfs/shmem is not added back.
        # This is a scheduling estimate, not a guarantee against resource kills.
        memory = (
            None
            if maximum == "max"
            else int(maximum) - current + statistics.get("inactive_file", 0)
        )
    except (OSError, ValueError):
        memory = None
    return memory


def disk_headroom(path):
    """Use space actually allocatable to this process's filesystem identity.

    POSIX f_bavail excludes reserved blocks even for uid 0, which may legally
    allocate them. No quota, mount, ownership or permission is changed here.
    """
    if hasattr(os, "statvfs") and hasattr(os, "geteuid"):
        stat = os.statvfs(path)
        blocks = stat.f_bfree if os.geteuid() == 0 else stat.f_bavail
        return blocks * stat.f_frsize
    return shutil.disk_usage(path).free


def preserve_failure(directory, attempt):
    target = directory / "failed_attempts" / f"attempt{attempt:02d}"
    target.mkdir(parents=True, exist_ok=False)
    for path in list(directory.iterdir()):
        if path.name in {"failed_attempts", "SPEC.json"} or path.name.startswith(
            "EXECUTION_"
        ):
            continue
        shutil.move(str(path), str(target / path.name))


def run(output, cache_dir, workers, min_memory_mb, min_disk_mb):
    if not hasattr(os, "wait4"):
        raise RuntimeError(
            "the execution controller requires POSIX wait4 resource accounting"
        )
    package = Path(__file__).resolve().parent
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads((package / "PROTOCOL.json").read_text())
    jobs = json.loads((package / "RUNS.json").read_text())
    declared_seals = {
        "followup": json.loads((package / "SOURCE_SEAL.json").read_text())["sha256"],
        "base": json.loads(
            (
                package.parent / "continuous_spiking_network" / "SOURCE_SEAL.json"
            ).read_text()
        )["sha256"],
    }
    digest = hashlib.sha256(json.dumps(jobs, sort_keys=True).encode()).hexdigest()
    if digest != protocol["runs_sha256"]:
        raise ValueError("inventory does not match the frozen protocol")
    import fcntl

    lock = (output / "CONTROLLER.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    queue, completed = [], []
    for spec in jobs:
        directory = output / spec["id"]
        saved = directory / "SPEC.json"
        if saved.exists() and json.loads(saved.read_text()) != spec:
            raise ValueError("existing run spec disagrees with inventory")
        write_json(saved, spec)
        if (directory / "RESULT.json").exists():
            result = json.loads((directory / "RESULT.json").read_text())
            if result["spec"] != spec:
                raise ValueError("completed result has a different spec")
            if result["source_seals"] != declared_seals:
                raise ValueError(
                    "completed result belongs to different scientific source"
                )
            completed.append(spec["id"])
        else:
            queue.append(spec)
    random.Random(92017).shuffle(queue)
    environment = dict(os.environ)
    environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    active, failures, receipts = {}, [], []
    began, last_progress = time.time(), 0.0
    invocation = len(list(output.glob("CONTROLLER_START_*.json"))) + 1
    write_json(
        output / f"CONTROLLER_START_{invocation:02d}.json",
        {
            "started_unix": began,
            "workers": workers,
            "min_memory_mb": min_memory_mb,
            "min_disk_mb": min_disk_mb,
            "inventory_sha256": digest,
            "execution_order_seed": 92017,
            "already_completed": completed,
            "python": sys.executable,
            "source_seals": declared_seals,
        },
    )
    while queue or active:
        memory = resource_headroom()
        disk = disk_headroom(output)
        allowed = (
            memory is None or memory >= min_memory_mb * 1024**2
        ) and disk >= min_disk_mb * 1024**2
        while queue and len(active) < workers and allowed and not failures:
            spec = queue.pop(0)
            directory = output / spec["id"]
            previous = sorted(directory.glob("EXECUTION_*.json"))
            attempt = len(previous) + 1
            if (directory / "START.json").exists():
                preserve_failure(directory, attempt - 1)
            command = [
                sys.executable,
                "-m",
                "experiments.continuous_spiking_followup.budget_training",
                "--spec",
                str(directory / "SPEC.json"),
                "--output",
                str(directory),
                "--cache-dir",
                str(Path(cache_dir).resolve()),
            ]
            log = (directory / f"execution_{attempt:02d}.log").open("w")
            process = subprocess.Popen(
                command,
                cwd=package.parents[1],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            active[process.pid] = {
                "process": process,
                "log": log,
                "spec": spec,
                "directory": directory,
                "attempt": attempt,
                "command": command,
                "started_unix": time.time(),
                "started_perf": time.perf_counter(),
            }
            memory = resource_headroom()
            disk = disk_headroom(output)
            allowed = (
                memory is None or memory >= min_memory_mb * 1024**2
            ) and disk >= min_disk_mb * 1024**2
        for pid, item in list(active.items()):
            done, status, usage = os.wait4(pid, os.WNOHANG)
            if not done:
                continue
            code = os.waitstatus_to_exitcode(status)
            item["process"].returncode = code
            item["log"].close()
            result_exists = (item["directory"] / "RESULT.json").exists()
            receipt = {
                "id": item["spec"]["id"],
                "attempt": item["attempt"],
                "command": item["command"],
                "exit_code": code,
                "result_exists": result_exists,
                "started_unix": item["started_unix"],
                "ended_unix": time.time(),
                "wall_seconds": time.perf_counter() - item["started_perf"],
                "child_user_cpu_seconds": usage.ru_utime,
                "child_system_cpu_seconds": usage.ru_stime,
                "child_cpu_seconds": usage.ru_utime + usage.ru_stime,
                "max_rss_platform_units": usage.ru_maxrss,
                "rss_units": "KiB on Linux; bytes on macOS",
            }
            write_json(
                item["directory"] / f"EXECUTION_{item['attempt']:02d}.json", receipt
            )
            receipts.append(receipt)
            if code == 0 and result_exists:
                completed.append(item["spec"]["id"])
            else:
                failures.append(receipt)
            del active[pid]
            print(
                json.dumps(
                    {
                        "completed": len(completed),
                        "planned": len(jobs),
                        "id": receipt["id"],
                        "exit_code": code,
                    }
                ),
                flush=True,
            )
        if time.time() - last_progress >= 15 or (not active and not queue):
            progress = {
                "updated_unix": time.time(),
                "planned": len(jobs),
                "completed": completed,
                "failed_attempts_this_invocation": failures,
                "running": [item["spec"]["id"] for item in active.values()],
                "queued": len(queue),
                "memory_headroom_bytes": memory,
                "disk_free_bytes": disk,
                "resource_wait": bool(queue and not active and not allowed),
            }
            write_json(output / "PROGRESS.json", progress)
            write_json(output / f"CONTROLLER_PROGRESS_{invocation:02d}.json", progress)
            last_progress = time.time()
        if failures and not active:
            break
        time.sleep(0.25 if active else 5)
    write_json(
        output / f"CONTROLLER_RESULT_{invocation:02d}.json",
        {
            "completed": len(completed),
            "planned": len(jobs),
            "failures": failures,
            "wall_seconds": time.time() - began,
            "execution_receipts": len(receipts),
            "child_cpu_seconds": sum(row["child_cpu_seconds"] for row in receipts),
            "cumulative_job_wall_seconds": sum(row["wall_seconds"] for row in receipts),
            "scope": "this invocation only; job wall may overlap and is not calendar elapsed",
        },
    )
    fcntl.flock(lock, fcntl.LOCK_UN)
    lock.close()
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--min-memory-mb", type=int, default=450)
    parser.add_argument("--min-disk-mb", type=int, default=12)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    raise SystemExit(
        run(
            args.output,
            args.cache_dir,
            args.workers,
            args.min_memory_mb,
            args.min_disk_mb,
        )
    )
