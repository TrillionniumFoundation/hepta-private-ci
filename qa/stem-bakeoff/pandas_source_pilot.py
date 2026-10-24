"""Pinned pandas5 TRAIN build qualification; never execute benchmark tests."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time


REVISIONS = {"base": "4f4282f8a7c1033fc3efe9f4eab5368a70ae5041",
             "candidate": "0babe10f1f3f19bb6183b6fb4cc958583c6860c8"}
SOURCE_URL = "https://github.com/pandas-dev/pandas"
PYTHON = "/tmp/hepta-op-python/cpython-3.8.20-linux-x86_64-gnu/bin/python3.8"
SOURCE_CAP = 750_000_000
BUILD_CAP = 2_000_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value))


def tree_bytes(root):
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file() and not p.is_symlink())


def resources(root):
    root = Path(root)
    stat = Path("/sys/fs/cgroup/memory.stat")
    memory = {} if not stat.exists() else {k: int(v) for k, v in
        (line.split() for line in stat.read_text().splitlines())}
    return {"source_bytes": tree_bytes(root / "sources"),
        "runtime_build_bytes": sum(tree_bytes(root / n) for n in
            ("runtime", "uv-cache", "checkouts", "artifacts")),
        "free_disk_bytes": shutil.disk_usage(root).free,
        "shared_cgroup_memory_current": int(Path("/sys/fs/cgroup/memory.current").read_text()),
        "shared_cgroup_memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
        "shared_cgroup_memory_stat": {k: memory.get(k) for k in
            ("anon", "file", "shmem", "kernel", "slab_reclaimable")},
        "memory_scope": "Shared cgroup observation, includes unrelated processes and reclaimable cache."}


def exceeded(snapshot):
    return (snapshot["source_bytes"] > SOURCE_CAP or snapshot["runtime_build_bytes"] > BUILD_CAP
            or snapshot["free_disk_bytes"] < 1_000_000_000)


def command(root, name, argv, *, cwd=None, env=None, timeout=600):
    """Retain all attempts, including timeout/cap failures, with disjoint child CPU."""
    root = Path(root).resolve()
    directory = root / "commands" / name
    directory.mkdir(parents=True, exist_ok=False)
    before = resources(root)
    if exceeded(before):
        write_new(directory / "receipt.json", {"launched": False, "reason": "resource_preflight", "resources": before})
        raise RuntimeError("pilot preflight resource cap")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    child, reason, usage, code = None, None, None, None
    peak_shared = before["shared_cgroup_memory_current"]
    effective_env = None if env is None else dict(os.environ, **env)
    with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
        try:
            child = subprocess.Popen(list(map(str, argv)), cwd=cwd or root, env=effective_env,
                stdout=stdout, stderr=stderr, start_new_session=True)
            next_check = time.monotonic() + 2
            while True:
                pid, status, usage = os.wait4(child.pid, os.WNOHANG)
                if pid:
                    code = os.waitstatus_to_exitcode(status)
                    child.returncode = code
                    break
                if (time.perf_counter_ns() - started) / 1e9 > timeout:
                    reason = "wall_timeout"
                elif time.monotonic() >= next_check:
                    current = resources(root)
                    peak_shared = max(peak_shared, current["shared_cgroup_memory_current"])
                    if exceeded(current):
                        reason = "resource_cap"
                    if stdout.tell() + stderr.tell() > 16_777_216:
                        reason = "log_cap"
                    next_check = time.monotonic() + 2
                if reason:
                    os.killpg(child.pid, signal.SIGKILL)
                    _, status, usage = os.wait4(child.pid, 0)
                    code = os.waitstatus_to_exitcode(status)
                    child.returncode = code
                    break
                time.sleep(.05)
        except Exception as error:
            reason = type(error).__name__ + ": " + str(error)
            if child is not None and child.returncode is None:
                os.killpg(child.pid, signal.SIGKILL)
                _, status, usage = os.wait4(child.pid, 0)
                code = os.waitstatus_to_exitcode(status)
                child.returncode = code
    report = {"argv": list(map(str, argv)), "cwd": str(cwd or root), "environment_override": env,
        "driver_source_sha256": sha(__file__),
        "launched": child is not None, "exit_code": code, "failure_reason": reason,
        "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
        "child_cpu_ns": None if usage is None else round((usage.ru_utime + usage.ru_stime) * 1e9),
        "interrupted_descendant_cpu_unknown": reason is not None and child is not None,
        "child_peak_rss_bytes": None if usage is None else usage.ru_maxrss * 1024,
        "shared_cgroup_peak_sampled_bytes": peak_shared, "resources_before": before,
        "resources_after": resources(root),
        "logs": {n: {"bytes": (directory / n).stat().st_size, "sha256": sha(directory / n)}
                 for n in ("stdout.log", "stderr.log")},
        "cost_scope": "Disjoint command launch through reaped exit/log close; child wait4 includes waited descendants. Receipt serialization and final resource scan excluded from wall/CPU. Shared cgroup sample is not process RSS."}
    write_new(directory / "receipt.json", report)
    print(json.dumps({"command": name, "exit_code": code, "failure_reason": reason,
                      "wall_seconds": report["wall_ns"] / 1e9}), flush=True)
    if code != 0 or reason or exceeded(report["resources_after"]):
        raise RuntimeError("pilot command failed: " + name)
    return directory / "stdout.log"


def freeze(root, protocol):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = {"schema": "hepta.pandas-source-pilot.v1", "group_id": "bugsinpy/pandas/5",
        "role": "train_build_qualification", "selection": "Only pandas group with full40 base revision; no outcome selection.",
        "revisions": REVISIONS, "url": SOURCE_URL, "python": PYTHON,
        "python_sha256": sha(PYTHON), "protocol": str(Path(protocol).resolve()),
        "protocol_sha256": sha(protocol), "source_cap_bytes": SOURCE_CAP,
        "runtime_build_cap_bytes": BUILD_CAP, "minimum_free_disk_bytes": 1_000_000_000,
        "max_native_builds": 2, "compiler_parallelism": 1, "benchmark_commands_permitted": False,
        "test_outcomes_permitted": False, "authority": "DENY_ALL",
        "source_code_sha256": sha(__file__), "resources": resources(root)}
    write_new(root / "pilot-plan.json", plan)
    return plan


def verify_plan(root):
    plan = json.loads((Path(root) / "pilot-plan.json").read_bytes())
    if (plan["revisions"] != REVISIONS or plan["protocol_sha256"] != sha(plan["protocol"])
            or plan["python_sha256"] != sha(PYTHON)):
        raise ValueError("frozen pilot identity changed")
    return plan


def acquire(root, attempt=1):
    root = Path(root).resolve()
    verify_plan(root)
    store = root / "sources" / "pandas.git"
    store.parent.mkdir(parents=True, exist_ok=True)
    if not store.exists():
        command(root, "01-git-init", ["git", "init", "--bare", store], timeout=30)
    fetch_name = "02-git-fetch" if attempt == 1 else "02-git-fetch-attempt-" + str(attempt)
    command(root, fetch_name, ["git", "--git-dir=" + str(store), "-c", "protocol.file.allow=never",
        "fetch", "--no-tags", "--depth=1", SOURCE_URL, *REVISIONS.values()], timeout=300)
    pins = {}
    for role, revision in REVISIONS.items():
        path = command(root, "03-tree-" + role,
            ["git", "--git-dir=" + str(store), "rev-parse", revision + "^{tree}"], timeout=30)
        pins[role] = {"commit": revision, "tree": path.read_text().strip()}
        work = root / "checkouts" / role
        work.parent.mkdir(parents=True, exist_ok=True)
        command(root, "04-checkout-" + role,
            ["git", "--git-dir=" + str(store), "worktree", "add", "--detach", work, revision], timeout=60)
    packs = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": sha(p)}
             for p in sorted((store / "objects" / "pack").glob("*")) if p.is_file()]
    report = {"revisions": pins, "packs": packs, "resources": resources(root),
              "benchmark_commands_run": 0, "network_transfer_bytes": None}
    write_new(root / "source-acquisition.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "acquire"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--protocol")
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    if args.action == "freeze" and not args.protocol:
        parser.error("freeze requires --protocol")
    print(json.dumps(freeze(args.root, args.protocol) if args.action == "freeze" else acquire(args.root, args.attempt)))
