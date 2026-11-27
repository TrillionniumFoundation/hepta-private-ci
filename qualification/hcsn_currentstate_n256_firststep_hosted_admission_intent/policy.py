"""Fail-closed, zero-model policy for a later hosted N256 preflight."""

import hashlib
import json
from pathlib import Path


IDENTITY = "hcsn-n256-firststep-hosted-admission-intent-20261118-c06d-001"
RUNTIME_SHA256 = "0625973f64197245273674586e60ce187571ef1f9d01bc52ea83a30beaa0ad06"
DENSE_ORACLE_SHA256 = "a3aa6a95cd55d254d9fa911d10768d1ec827e2374265a5b0474e0d6243929bfa"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"

GIB = 1024**3
KIB_PER_GIB = 1024**2

POLICY = {
    "minimum_mem_available_kib": 10 * KIB_PER_GIB,
    "minimum_swap_free_kib": 1 * KIB_PER_GIB,
    "minimum_finite_cgroup_headroom_bytes": 6 * GIB,
    "child_rlimit_as_bytes": 4 * GIB,
    "minimum_effective_cpus": 4,
    "maximum_memory_pressure_avg10": 0.05,
    "maximum_capture_age_ns": 30_000_000_000,
    "child_timeout_seconds": 600,
    "job_timeout_minutes": 20,
    "concurrency": 1,
    "thread_count": 1,
}

TARGET = {
    "dynamic_steps": 1,
    "dense_expm_actions": 2,
    "expm_orders": [258, 259],
    "coordinate_denominator": 69728,
}

RUNTIME = {
    "python_version": "3.12.3",
    "python_executable_sha256": "2ce74da59bd24c1301a77e90b94abfe52bc14d54c0f79f565665b5a59d62734b",
    "numpy_version": "2.3.5",
    "numpy_record_sha256": "81412454021a86a9199d8c3ae4b5e1312e7498437ba9e3fdcc6f5919c0a6482c",
    "numpy_init_sha256": "93924ac4b793328947dfd9eb9355e54eccdfd26a92c8dd52188aed2e52c7eb38",
    "scipy_version": "1.17.0",
    "scipy_record_sha256": "d98e3cc57253f7f8c6ca4f5b775a4747815edc9b1bcd5295c9dacc3c8d49c7b0",
    "scipy_init_sha256": "335bc6e0a9909dc7534f9569a3685a92dc8001cb8c63a6da4c239849ff02d4d0",
    "machine": "x86_64",
    "runner_os": "Linux",
    "runner_arch": "X64",
}


class PolicyError(ValueError):
    """Raised while still before authentic input or numerical imports."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _memory_events(raw):
    fields = {}
    for line in raw.splitlines():
        name, value = line.split()
        fields[name] = int(value)
    return fields


def _cpu_count(spec):
    count = 0
    for item in spec.split(","):
        bounds = [int(value) for value in item.split("-")]
        count += 1 if len(bounds) == 1 else bounds[1] - bounds[0] + 1
    return count


def _pressure_avg10(lines):
    values = []
    for line in lines:
        parts = dict(item.split("=", 1) for item in line.split()[1:])
        values.append(float(parts["avg10"]))
    if not values:
        raise PolicyError("memory pressure missing")
    return max(values)


def _require_exact(observed, expected, name):
    if observed != expected:
        raise PolicyError(name)


def assess_preflight(preflight, launch):
    """Validate a future capture without granting numerical admission."""

    _require_exact(preflight.get("schema"), "hcsn-n256-hosted-preflight-v1", "preflight schema")
    _require_exact(launch.get("schema"), "hcsn-n256-hosted-launch-v1", "launch schema")
    _require_exact(preflight.get("runtime_sha256"), RUNTIME_SHA256, "runtime sha256")
    _require_exact(preflight.get("runtime"), RUNTIME, "runtime identity")
    _require_exact(launch.get("identity"), IDENTITY, "launch identity")
    _require_exact(launch.get("dense_oracle_sha256"), DENSE_ORACLE_SHA256, "dense oracle")
    _require_exact(launch.get("input_bundle_sha256"), INPUT_BUNDLE_SHA256, "input bundle")
    _require_exact(launch.get("target"), TARGET, "target envelope")
    _require_exact(launch.get("policy"), POLICY, "launch policy")

    if preflight.get("session_id") != launch.get("session_id"):
        raise PolicyError("same-session binding")
    if preflight.get("boot_id") != launch.get("boot_id"):
        raise PolicyError("same-boot binding")
    if preflight.get("self_cgroup") != launch.get("self_cgroup"):
        raise PolicyError("same-cgroup binding")
    age = launch.get("execution_monotonic_ns", -1) - preflight.get("captured_monotonic_ns", 0)
    if age < 0 or age > POLICY["maximum_capture_age_ns"]:
        raise PolicyError("stale preflight")

    meminfo = preflight.get("meminfo_kib", {})
    if meminfo.get("MemAvailable", 0) < POLICY["minimum_mem_available_kib"]:
        raise PolicyError("MemAvailable threshold")
    if meminfo.get("SwapFree", 0) < POLICY["minimum_swap_free_kib"]:
        raise PolicyError("SwapFree threshold")
    if _pressure_avg10(preflight.get("memory_pressure", [])) > POLICY["maximum_memory_pressure_avg10"]:
        raise PolicyError("memory pressure threshold")

    readable_limits = 0
    effective_cpus = 0
    for item in preflight.get("ancestor_cgroup_chain", []):
        fields = item.get("fields", {})
        if "cpuset.cpus.effective" in fields:
            effective_cpus = max(effective_cpus, _cpu_count(fields["cpuset.cpus.effective"]))
        if "memory.max" not in fields or "memory.current" not in fields:
            continue
        readable_limits += 1
        events = _memory_events(fields.get("memory.events", ""))
        if events.get("oom", 0) or events.get("oom_kill", 0) or events.get("oom_group_kill", 0):
            raise PolicyError("pre-existing cgroup OOM event")
        if fields["memory.max"] != "max":
            headroom = int(fields["memory.max"]) - int(fields["memory.current"])
            if headroom < POLICY["minimum_finite_cgroup_headroom_bytes"]:
                raise PolicyError("finite cgroup headroom")
    if readable_limits == 0:
        raise PolicyError("readable ancestor memory limits")
    if effective_cpus < POLICY["minimum_effective_cpus"]:
        raise PolicyError("effective CPU threshold")

    expected_threads = {name: "1" for name in (
        "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"
    )}
    _require_exact(launch.get("thread_environment"), expected_threads, "thread environment")
    if launch.get("rlimit_as_applied_before_exec") is not True:
        raise PolicyError("RLIMIT_AS ordering")
    if launch.get("numeric_imports_before_child_limit") != 0:
        raise PolicyError("numerical import before child limit")

    return {
        "identity": IDENTITY,
        "preflight_contract_satisfied": True,
        "runtime_admitted": False,
        "resource_admitted": False,
        "n256_numerical_execution_allowed": False,
        "allocation_contract": None,
        "calendar_contract": None,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "all_closed": False,
    }


def canonical_policy_sha256():
    payload = json.dumps(
        {"identity": IDENTITY, "policy": POLICY, "runtime": RUNTIME, "target": TARGET},
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()
