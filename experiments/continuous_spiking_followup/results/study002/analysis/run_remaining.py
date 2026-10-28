"""Serial stdlib continuation; explicit retries retain every prior output."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    pending.replace(path)


def verify_seal(package):
    seal = read(package / "SOURCE_SEAL.json")
    if canonical(seal["files"]) != seal["sha256"]:
        raise ValueError("source seal mapping changed")
    for relative, expected in seal["files"].items():
        path = package / relative
        if sha(path) != expected:
            raise ValueError("sealed scientific file changed: " + str(path))
    return seal["sha256"]


def plan_cases(jobs, protocol):
    cases = [
        {
            "id": f"boundary/seed{seed}",
            "kind": "boundary",
            "seed": seed,
            "result_name": "RESULT.json",
        }
        for seed in protocol["boundary"]["actor_seeds"]
    ]
    selected = [
        spec
        for spec in jobs
        if (spec["stage"] == "representation" and spec["seed"] == 6201)
        or (spec["stage"] == "scaling" and spec["seed"] == 7301)
    ]
    for spec in selected:
        cases.append(
            {
                "id": "measurements/" + spec["id"],
                "kind": "measurement",
                "run_id": spec["id"],
                "spec": spec,
                "result_name": "MEASUREMENT.json",
                "cross_process": spec["stage"] == "representation"
                and spec["task"] == "mnist",
            }
        )
    if (
        len(selected) != protocol["stream_measurement"]["cases"]
        or sum(row.get("cross_process", False) for row in cases) != 7
    ):
        raise ValueError("preselected measurement inventory changed")
    return cases


def training_ready(study, jobs, seals, cache):
    missing, failed, ready = [], [], []
    for spec in jobs:
        directory = study / spec["id"]
        if (directory / "FAILED.json").exists():
            failed.append(spec["id"])
            continue
        result, receipts = (
            directory / "RESULT.json",
            sorted(directory.glob("EXECUTION_*.json")),
        )
        if not result.exists() or not receipts:
            missing.append(spec["id"])
            continue
        receipt = receipts[-1]
        stamp = tuple(
            (p.stat().st_size, p.stat().st_mtime_ns) for p in (result, receipt)
        )
        if cache.get(spec["id"], {}).get("stamp") != stamp:
            value, execution = read(result), read(receipt)
            if value["spec"] != spec or value["source_seals"] != seals:
                raise ValueError("training identity mismatch: " + spec["id"])
            if (
                execution["id"] != spec["id"]
                or execution["exit_code"] != 0
                or not execution["result_exists"]
            ):
                missing.append(spec["id"])
                continue
            cache[spec["id"]] = {
                "stamp": stamp,
                "result_sha256": sha(result),
                "execution_path": str(receipt.relative_to(study)),
                "execution_sha256": sha(receipt),
            }
        ready.append(spec["id"])
    return {
        "ready": len(ready) == len(jobs) and not failed,
        "completed": len(ready),
        "planned": len(jobs),
        "missing_result_or_success_receipt": missing,
        "current_failed": failed,
    }


def build_command(args, case, output, invocation, attempt):
    options, flags = {"--output": output}, []
    if case["kind"] == "boundary":
        module = "boundary_online"
        options.update({"--seed": case["seed"], "--base-results": args.base_results})
        if case["seed"] == args.native_seed:
            work = (
                args.native_work
                / f"seed{case['seed']}_invocation{invocation:02d}_attempt{attempt:02d}"
            )
            options.update(
                {"--native-binary": args.native_binary, "--native-work": work}
            )
    else:
        module = "stream_measure"
        options.update(
            {
                "--run": args.study / case["run_id"],
                "--cache-dir": args.cache_dir,
                "--batch-size": args.batch_size,
                "--repeats": args.repeats,
            }
        )
        if case["cross_process"]:
            flags.append("--cross-process")
    values = [
        part for option, value in options.items() for part in (option, str(value))
    ]
    return (
        [sys.executable, "-m", "experiments.continuous_spiking_followup." + module]
        + values
        + flags
    )


def complete_case(study, case, seals):
    output = study / case["id"]
    path = output / case["result_name"]
    executions = sorted(
        (study / "remaining_execution" / case["id"]).glob("EXECUTION_*.json")
    )
    if not path.exists() or not executions or (output / "FAILED.json").exists():
        return False
    receipt, result = read(executions[-1]), read(path)
    if receipt["exit_code"] != 0 or not receipt["result_exists"]:
        return False
    if receipt["result_sha256"] != sha(path) or receipt["source_seals"] != seals:
        raise ValueError("completed continuation evidence changed")
    if case["kind"] == "boundary":
        if result["seed"] != case["seed"] or result["source_seals"] != seals:
            raise ValueError("completed boundary identity changed")
    elif (
        result["identity"]["spec"] != case["spec"]
        or result["identity"]["source_seals"] != seals
    ):
        raise ValueError("completed measurement identity changed")
    return True


def execute(args, case, seals, invocation, progress):
    output = args.study / case["id"]
    evidence = args.study / "remaining_execution" / case["id"]
    evidence.mkdir(parents=True, exist_ok=True)
    previous = sorted(evidence.glob("ATTEMPT_START_*.json"))
    attempt = max((int(p.stem.rsplit("_", 1)[1]) for p in previous), default=0) + 1
    if previous and not args.retry_failed:
        raise FileExistsError(
            "prior incomplete attempt requires explicit --retry-failed: " + case["id"]
        )
    if previous and not (evidence / f"EXECUTION_{attempt - 1:02d}.json").exists():
        prior = read(previous[-1])
        proc = Path(f"/proc/{prior.get('child_pid', -1)}/stat")
        if (
            proc.exists()
            and prior.get("child_start_ticks")
            == proc.read_text().rsplit(")", 1)[1].split()[19]
        ):
            raise RuntimeError(
                "previous continuation child is still alive; refusing concurrent execution"
            )
    if output.exists():
        if not args.retry_failed:
            raise FileExistsError(
                f"incomplete output exists: {output}; explicit --retry-failed is required"
            )
        target = (
            args.study
            / "failed_attempts/remaining"
            / case["id"]
            / f"before_attempt{attempt:02d}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        output.rename(target)
    command = build_command(args, case, output, invocation, attempt)
    environment = dict(os.environ)
    environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    start = {
        "id": case["id"],
        "attempt": attempt,
        "command": command,
        "source_seals": seals,
        "controller_sha256": sha(Path(__file__)),
        "started_unix": time.time(),
    }
    write(evidence / f"ATTEMPT_START_{attempt:02d}.json", start)
    began, interrupted = time.perf_counter(), False
    with (evidence / f"execution_{attempt:02d}.log").open("x") as log:
        process = subprocess.Popen(
            command,
            cwd=args.package.parents[1],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        start["child_pid"] = process.pid
        proc = Path(f"/proc/{process.pid}/stat")
        start["child_start_ticks"] = (
            proc.read_text().rsplit(")", 1)[1].split()[19] if proc.exists() else None
        )
        write(evidence / f"ATTEMPT_START_{attempt:02d}.json", start)
        progress(
            {
                "phase": "running",
                "case": case["id"],
                "attempt": attempt,
                "pid": process.pid,
            }
        )
        try:
            _, status, usage = os.wait4(process.pid, 0)
        except KeyboardInterrupt:
            interrupted = True
            process.terminate()
            _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    path = output / case["result_name"]
    receipt = {
        **start,
        "ended_unix": time.time(),
        "exit_code": process.returncode,
        "wait_status": status,
        "wall_seconds": time.perf_counter() - began,
        "child_user_cpu_seconds": usage.ru_utime,
        "child_system_cpu_seconds": usage.ru_stime,
        "child_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "max_rss_platform_units": usage.ru_maxrss,
        "rss_units": "KiB on Linux; bytes on macOS",
        "result_exists": path.exists(),
        "result_sha256": sha(path) if path.exists() else None,
        "failed_marker_exists": (output / "FAILED.json").exists(),
        "interrupted": interrupted,
        "cpu_scope": "exact direct child PID from POSIX wait4; nested descendants may be included when the child waits for them",
        "wall_scope": "launch through reaping the exact direct child, including interpreter startup/shutdown and logging",
    }
    write(evidence / f"EXECUTION_{attempt:02d}.json", receipt)
    if output.exists():
        write(output / f"EXECUTION_{attempt:02d}.json", receipt)
    return receipt


def run(args):
    if not hasattr(os, "wait4"):
        raise RuntimeError("POSIX wait4 is required")
    sys.path.insert(0, str(args.package.parents[1]))
    # Frozen controller module imports only the standard library.
    from experiments.continuous_spiking_followup.run_matrix import (
        resource_headroom,
        disk_headroom,
    )

    args.study.mkdir(parents=True, exist_ok=True)
    lock = (args.study / "REMAINING.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    protocol, jobs = (
        read(args.package / "PROTOCOL.json"),
        read(args.package / "RUNS.json"),
    )
    seals = {
        "followup": verify_seal(args.package),
        "base": verify_seal(args.package.parent / "continuous_spiking_network"),
    }
    if canonical(jobs) != protocol["runs_sha256"] or len(jobs) != sum(
        protocol["jobs"].values()
    ):
        raise ValueError("frozen training inventory mismatch")
    if (
        seals["base"] != protocol["base_source_seal"]
        or sha(args.native_binary) != protocol["native_binary_sha256"]
    ):
        raise ValueError("historical source/native binary identity mismatch")
    args.native_seed = protocol["boundary"]["native"]["actor_seed"]
    args.batch_size, args.repeats = (
        protocol["stream_measurement"][name] for name in ("batch_size", "repeats")
    )
    cases = plan_cases(jobs, protocol)
    invocation = len(list(args.study.glob("REMAINING_START_*.json"))) + 1
    began = time.perf_counter()
    state = {"invocation": invocation, "completed": [], "planned_cases": len(cases)}

    def progress(update):
        state.update(update)
        state["updated_unix"] = time.time()
        write(args.study / "REMAINING_PROGRESS.json", state)
        write(args.study / f"REMAINING_PROGRESS_{invocation:02d}.json", state)

    write(
        args.study / f"REMAINING_START_{invocation:02d}.json",
        {
            "started_unix": time.time(),
            "source_seals": seals,
            "inventory_sha256": canonical(jobs),
            "case_plan_sha256": canonical(cases),
            "cases": cases,
            "controller_sha256": sha(Path(__file__)),
            "resource_estimator_sha256": sha(args.package / "run_matrix.py"),
            "python": sys.executable,
            "argv": sys.argv,
            "min_memory_mb": args.min_memory_mb,
            "min_disk_mb": args.min_disk_mb,
            "retry_failed_explicit": args.retry_failed,
            "scope": "5 fixed boundary seeds, then 55 fixed measurements; 7 selected fresh-process replays; no heavy audits launched",
        },
    )
    training_lock = (args.study / "CONTROLLER.lock").open("a+")
    cache, receipts = {}, []
    try:
        while True:
            ready = training_ready(args.study, jobs, seals, cache)
            progress({"phase": "waiting_for_training", "training": ready})
            if ready["ready"]:
                try:
                    fcntl.flock(training_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    progress({"phase": "waiting_for_training_controller_exit"})
            time.sleep(args.poll_seconds)
        write(
            args.study / f"REMAINING_TRAINING_READY_{invocation:02d}.json",
            {
                "source_seals": seals,
                "inventory_sha256": canonical(jobs),
                "verified_jobs": cache,
                "verified_unix": time.time(),
                "training_lock_held_until_continuation_exit": True,
            },
        )
        for case in cases:
            if complete_case(args.study, case, seals):
                state["completed"].append(case["id"])
                continue
            while True:
                memory, disk = resource_headroom(), disk_headroom(args.study)
                allowed = (
                    memory is None or memory >= args.min_memory_mb * 1024**2
                ) and disk >= args.min_disk_mb * 1024**2
                progress(
                    {
                        "phase": "resource_check" if allowed else "resource_wait",
                        "case": case["id"],
                        "memory_headroom_bytes": memory,
                        "disk_free_bytes": disk,
                    }
                )
                if allowed:
                    break
                time.sleep(args.poll_seconds)
            if (
                verify_seal(args.package) != seals["followup"]
                or verify_seal(args.package.parent / "continuous_spiking_network")
                != seals["base"]
            ):
                raise ValueError("scientific source changed during continuation")
            receipt = execute(args, case, seals, invocation, progress)
            receipts.append(receipt)
            if (
                receipt["interrupted"]
                or receipt["exit_code"] != 0
                or not receipt["result_exists"]
                or receipt["failed_marker_exists"]
            ):
                raise RuntimeError(
                    "continuation child failed; retained attempt: " + case["id"]
                )
            state["completed"].append(case["id"])
            progress({"phase": "completed_case", "case": case["id"]})
            print(
                json.dumps(
                    {
                        "completed": len(state["completed"]),
                        "planned": len(cases),
                        "id": case["id"],
                    }
                ),
                flush=True,
            )
        progress({"phase": "complete", "case": None})
        code, error = 0, None
    except Exception:
        code, error = 1, traceback.format_exc()
        progress({"phase": "failed", "error": error})
    finally:
        fcntl.flock(training_lock, fcntl.LOCK_UN)
        training_lock.close()
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    write(
        args.study / f"REMAINING_RESULT_{invocation:02d}.json",
        {
            "exit_code": code,
            "error": error,
            "completed": state["completed"],
            "planned": len(cases),
            "wall_seconds": time.perf_counter() - began,
            "executions_this_invocation": len(receipts),
            "known_child_cpu_seconds_this_invocation": sum(
                row["child_cpu_seconds"] for row in receipts
            ),
            "scope": "All actual reaped child attempts, including failures, are included. Individual receipts remain under remaining_execution.",
        },
    )
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument(
        "--package", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--base-results", required=True, type=Path)
    parser.add_argument("--native-binary", required=True, type=Path)
    parser.add_argument(
        "--native-work",
        type=Path,
        default=Path("/dev/shm/hcsn-followup-native-20261028/formal"),
    )
    parser.add_argument("--min-memory-mb", type=int, default=450)
    parser.add_argument("--min-disk-mb", type=int, default=12)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--retry-failed", action="store_true")
    arguments = parser.parse_args()
    if (
        arguments.min_memory_mb < 450
        or arguments.min_disk_mb < 1
        or not 0 < arguments.poll_seconds <= 60
    ):
        parser.error(
            "memory must be >=450 MiB, disk >=1 MiB, polling in (0,60] seconds"
        )
    for name in (
        "study",
        "package",
        "cache_dir",
        "base_results",
        "native_binary",
        "native_work",
    ):
        setattr(arguments, name, getattr(arguments, name).resolve())
    raise SystemExit(run(arguments))
