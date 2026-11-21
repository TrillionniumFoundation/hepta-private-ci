"""Fail-closed hosted admission; this module never imports numerical packages."""

import hashlib
import importlib.metadata
import json
import os
import resource
import sys
from pathlib import Path

KEY = "hcsn-n256-dense-compatible-firststep-hosted-20261121-c06d-001"
MIN_AVAILABLE_KIB = 8 * 1024 * 1024
MIN_CGROUP_HEADROOM = 2 * 1024**3
AS_BYTES = 4 * 1024**3
THREADS = ("MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")
EXPECTED_RUNTIME = {
    "numpy": ("2.3.5", "81412454021a86a9199d8c3ae4b5e1312e7498437ba9e3fdcc6f5919c0a6482c", "93924ac4b793328947dfd9eb9355e54eccdfd26a92c8dd52188aed2e52c7eb38"),
    "scipy": ("1.17.0", "d98e3cc57253f7f8c6ca4f5b775a4747815edc9b1bcd5295c9dacc3c8d49c7b0", "335bc6e0a9909dc7534f9569a3685a92dc8001cb8c63a6da4c239849ff02d4d0"),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    path = Path(path)
    return path.read_text().strip() if path.is_file() else None


def cgroups():
    relative = None
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[:2] == ["0", ""]:
            relative = fields[2].lstrip("/")
    if relative is None:
        raise ValueError("unified cgroup path")
    root, current, result = Path("/sys/fs/cgroup"), Path("/sys/fs/cgroup") / relative, []
    while True:
        result.append({name: read(current / name) for name in (
            "memory.current", "memory.max", "memory.events", "cpu.max", "cpuset.cpus.effective"
        )} | {"path": str(current)})
        if current == root:
            return result
        current = current.parent
        if root not in (current, *current.parents):
            raise ValueError("cgroup escaped root")


def meminfo():
    result = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        fields = value.split()
        if fields and fields[0].isdigit():
            result[name] = int(fields[0])
    return result


def runtime():
    result = {}
    for name, expected in EXPECTED_RUNTIME.items():
        distribution = importlib.metadata.distribution(name)
        observed = (
            distribution.version,
            sha(distribution.read_text("RECORD").encode()),
            sha(Path(distribution.locate_file(f"{name}/__init__.py")).read_bytes()),
        )
        if observed != expected:
            raise ValueError(f"runtime identity: {name}")
        result[name] = dict(zip(("version", "record_sha256", "init_sha256"), observed))
    return result


def capture():
    return {
        "meminfo_kib": meminfo(),
        "cgroups": cgroups(),
        "python": sys.version,
        "python_executable_sha256": sha(Path(sys.executable).read_bytes()),
        "thread_environment": {name: os.environ.get(name) for name in THREADS},
        "github": {name: os.environ.get(name) for name in (
            "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA",
            "GITHUB_REF", "GITHUB_EVENT_NAME", "GITHUB_HEAD_REF", "GITHUB_BASE_REF",
            "ADMITTED_SOURCE_SHA", "RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH"
        )},
    }


def admit():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != KEY:
        raise ValueError("unique execution key")
    if os.environ.get("GITHUB_REPOSITORY") != "TrillionniumFoundation/hepta-private-ci":
        raise ValueError("repository identity")
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event == "push":
        if os.environ.get("GITHUB_REF") != "refs/heads/research/hcsn-n256-dense-compatible-firststep-20261121-c06d":
            raise ValueError("single research ref identity")
    elif event == "pull_request":
        if os.environ.get("GITHUB_HEAD_REF") != "research/hcsn-n256-dense-compatible-firststep-activation-20261121-c06d":
            raise ValueError("single activation head identity")
        if os.environ.get("GITHUB_BASE_REF") != "intent/hcsn-n256-dense-compatible-firststep-execution-20261121-c06d":
            raise ValueError("single activation base identity")
    else:
        raise ValueError("single dispatch event identity")
    source_sha = os.environ.get("ADMITTED_SOURCE_SHA", "")
    if len(source_sha) != 40 or any(character not in "0123456789abcdef" for character in source_sha):
        raise ValueError("admitted source commit identity")
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
    effective = next((item["cpuset.cpus.effective"] for item in snapshot["cgroups"] if item["cpuset.cpus.effective"]), None)
    if effective is None:
        raise ValueError("effective CPU identity")
    cpus = sum((ends[-1] - ends[0] + 1) for ends in ([int(x) for x in group.split("-")] for group in effective.split(",")))
    if cpus < 2:
        raise ValueError("effective CPU admission")
    for item in snapshot["cgroups"]:
        maximum, current = item["memory.max"], item["memory.current"]
        if maximum not in (None, "max") and int(maximum) - int(current) < MIN_CGROUP_HEADROOM:
            raise ValueError("finite cgroup headroom")
    snapshot["runtime"], snapshot["effective_cpus"], snapshot["admitted"] = runtime(), cpus, True
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (AS_BYTES, AS_BYTES))
    return snapshot


def canonical(value):
    return json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
