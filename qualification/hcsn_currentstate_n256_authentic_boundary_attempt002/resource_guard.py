"""Fail-closed hosted resource and runtime admission before numerical imports."""

import hashlib
import importlib.metadata
import json
import os
import resource
import sys
from pathlib import Path


KEY = "hcsn-n256-authentic-boundary-hosted-20261121-c06d-002"
MIN_AVAILABLE_KIB = 8 * 1024 * 1024
MIN_CGROUP_HEADROOM = 2 * 1024**3
THREADS = ("MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")
EXPECTED_RUNTIME = {
    "numpy": {
        "version": "2.3.5",
        "record_sha256": "81412454021a86a9199d8c3ae4b5e1312e7498437ba9e3fdcc6f5919c0a6482c",
        "init_sha256": "93924ac4b793328947dfd9eb9355e54eccdfd26a92c8dd52188aed2e52c7eb38",
    },
    "scipy": {
        "version": "1.17.0",
        "record_sha256": "d98e3cc57253f7f8c6ca4f5b775a4747815edc9b1bcd5295c9dacc3c8d49c7b0",
        "init_sha256": "335bc6e0a9909dc7534f9569a3685a92dc8001cb8c63a6da4c239849ff02d4d0",
    },
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    path = Path(path)
    return path.read_text().strip() if path.is_file() else None


def _meminfo():
    result = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        fields = value.split()
        if fields and fields[0].isdigit():
            result[name] = int(fields[0])
    return result


def _cgroups():
    relative = None
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[:2] == ["0", ""]:
            relative = fields[2].lstrip("/")
    if relative is None:
        raise ValueError("unified cgroup path")
    root = Path("/sys/fs/cgroup")
    current = root / relative
    result = []
    while True:
        result.append(
            {
                "path": str(current),
                "memory.current": _read(current / "memory.current"),
                "memory.max": _read(current / "memory.max"),
                "memory.events": _read(current / "memory.events"),
                "cpu.max": _read(current / "cpu.max"),
                "cpuset.cpus.effective": _read(current / "cpuset.cpus.effective"),
            }
        )
        if current == root:
            break
        current = current.parent
        if root not in (current, *current.parents):
            raise ValueError("cgroup escaped root")
    return result


def _runtime():
    result = {}
    for name, expected in EXPECTED_RUNTIME.items():
        distribution = importlib.metadata.distribution(name)
        record = distribution.read_text("RECORD")
        init_path = Path(distribution.locate_file(f"{name}/__init__.py"))
        observed = {
            "version": distribution.version,
            "record_sha256": _sha(record.encode()),
            "init_sha256": _sha(init_path.read_bytes()),
        }
        if observed != expected:
            raise ValueError(f"runtime identity: {name}")
        result[name] = observed
    return result


def capture():
    return {
        "meminfo_kib": _meminfo(),
        "cgroups": _cgroups(),
        "python": sys.version,
        "python_executable_sha256": _sha(Path(sys.executable).read_bytes()),
        "thread_environment": {name: os.environ.get(name) for name in THREADS},
        "github": {
            name: os.environ.get(name)
            for name in (
                "GITHUB_REPOSITORY",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_SHA",
                "RUNNER_NAME",
                "RUNNER_OS",
                "RUNNER_ARCH",
            )
        },
    }


def admit():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != KEY:
        raise ValueError("unique execution key")
    if os.environ.get("GITHUB_REPOSITORY") != "TrillionniumFoundation/hepta-private-ci":
        raise ValueError("repository identity")
    if (os.environ.get("RUNNER_OS"), os.environ.get("RUNNER_ARCH")) != ("Linux", "X64"):
        raise ValueError("runner identity")
    if sys.version_info[:3] != (3, 12, 3):
        raise ValueError("python identity")
    if any(os.environ.get(name) != "1" for name in THREADS):
        raise ValueError("thread environment")
    if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
        raise ValueError("numerical import before admission")
    snapshot = capture()
    if snapshot["meminfo_kib"].get("MemAvailable", 0) < MIN_AVAILABLE_KIB:
        raise ValueError("MemAvailable admission")
    effective = next(
        (item["cpuset.cpus.effective"] for item in snapshot["cgroups"] if item["cpuset.cpus.effective"]),
        None,
    )
    if effective is None:
        raise ValueError("effective CPU identity")
    cpus = 0
    for group in effective.split(","):
        ends = [int(value) for value in group.split("-")]
        cpus += 1 if len(ends) == 1 else ends[1] - ends[0] + 1
    if cpus < 2:
        raise ValueError("effective CPU admission")
    for item in snapshot["cgroups"]:
        maximum, current = item["memory.max"], item["memory.current"]
        if maximum not in (None, "max") and int(maximum) - int(current) < MIN_CGROUP_HEADROOM:
            raise ValueError("finite cgroup headroom")
    snapshot["runtime"] = _runtime()
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(256, hard), hard))
    snapshot["admitted"] = True
    snapshot["effective_cpus"] = cpus
    return snapshot


def canonical(value):
    return json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
