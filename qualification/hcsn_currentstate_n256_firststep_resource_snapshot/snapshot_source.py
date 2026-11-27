"""Emit one canonical, zero-model resource and runtime observation.

This source never opens the N256 input bundle and never imports any HCSN
candidate/oracle/serializer module.  It observes the host only so a later,
separately frozen execution admission can decide whether it is safe to run.
"""

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path


SCHEMA = "hcsn-n256-firststep-resource-snapshot-v1"
EXPECTED_COORDINATES = 69_728
EXPECTED_DYNAMIC_STEPS = 1
EXPECTED_DENSE_EXPM_ACTIONS = 2
CGROUP_FIELDS = (
    "memory.current",
    "memory.peak",
    "memory.min",
    "memory.low",
    "memory.high",
    "memory.max",
    "memory.swap.current",
    "memory.swap.max",
    "memory.events",
    "pids.current",
    "pids.max",
    "cpu.max",
    "cpuset.cpus.effective",
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    return Path(path).read_text().strip()


def _meminfo():
    selected = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            fields = value.split()
            if len(fields) != 2 or fields[1] != "kB":
                raise ValueError("meminfo unit")
            selected[name] = int(fields[0])
    if set(selected) != {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
        raise ValueError("meminfo field set")
    return selected


def _cgroup_chain():
    unified = None
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        hierarchy, controllers, path = line.split(":", 2)
        if hierarchy == "0" and controllers == "":
            unified = path
    if unified is None:
        raise ValueError("unified cgroup path")
    current = Path("/sys/fs/cgroup") / unified.lstrip("/")
    root = Path("/sys/fs/cgroup")
    chain = []
    while True:
        fields = {}
        for name in CGROUP_FIELDS:
            path = current / name
            if path.is_file():
                fields[name] = path.read_text().strip()
        chain.append({"level": len(chain), "path": str(current), "fields": fields})
        if current == root:
            break
        if root not in current.parents:
            raise ValueError("cgroup escaped unified root")
        current = current.parent
    return unified, chain


def _distribution(name):
    distribution = importlib.metadata.distribution(name)
    record = distribution.read_text("RECORD")
    if not record:
        raise ValueError(f"{name} RECORD unavailable")
    return {
        "name": name,
        "version": distribution.version,
        "record_sha256": hashlib.sha256(record.encode()).hexdigest(),
    }


def _runtime():
    import numpy
    import scipy

    return {
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": _sha256(sys.executable),
        "numpy": _distribution("numpy"),
        "numpy_init_sha256": _sha256(numpy.__file__),
        "scipy": _distribution("scipy"),
        "scipy_init_sha256": _sha256(scipy.__file__),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "thread_environment": {
            name: os.environ.get(name)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
    }


def _events(raw):
    result = {}
    for line in raw.splitlines():
        name, value = line.split()
        result[name] = int(value)
    return result


def observe():
    runtime = _runtime()
    meminfo = _meminfo()
    unified, chain = _cgroup_chain()
    finite_max = []
    for item in chain:
        value = item["fields"].get("memory.max")
        if value not in (None, "max"):
            finite_max.append({"level": item["level"], "bytes": int(value)})
    app = next((item for item in chain if item["path"].endswith("/app.slice")), None)
    app_events = _events(app["fields"]["memory.events"]) if app else None
    pressure = Path("/proc/pressure/memory").read_text().strip().splitlines()
    runtime_sha256 = hashlib.sha256(
        json.dumps(runtime, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {
        "schema": SCHEMA,
        "runtime": runtime,
        "runtime_sha256": runtime_sha256,
        "boot_id": _read("/proc/sys/kernel/random/boot_id"),
        "self_cgroup": unified,
        "meminfo_kib": meminfo,
        "memory_pressure": pressure,
        "ancestor_cgroup_chain": chain,
        "finite_memory_max": finite_max,
        "app_slice_memory_events": app_events,
        "frozen_future_envelope": {
            "coordinate_denominator": EXPECTED_COORDINATES,
            "dynamic_steps": EXPECTED_DYNAMIC_STEPS,
            "dense_expm_actions": EXPECTED_DENSE_EXPM_ACTIONS,
            "expm_orders": [258, 259],
        },
        "counts": {
            "n256_input_reads": 0,
            "n256_serializer_calls": 0,
            "dynamic_steps": 0,
            "matrix_exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "allocation_contract": None,
        "calendar_contract": None,
        "resource_admitted": False,
        "status": "PASS_OBSERVATION_HOLD_ADMISSION",
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(observe(), allow_nan=False, separators=(",", ":"), sort_keys=True))
