"""Pins and resource limits for one independently authorized fitting probe."""

import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/memory_cell_retention_v2"))
from retention_common import (
    BASE_IDENTITY,
    base_inventory,
    digest,
    file_digest,
    read_json,
    remaining_timeout,
    require,
    retain,
    retained_bytes,
    runtime_versions,
    source_inventory,
)
from evolution_common import canonical


def sources():
    result = source_inventory()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        result[str(path.relative_to(REPO))] = dict(
            bytes=path.stat().st_size, sha256=file_digest(path)
        )
    return dict(sorted(result.items()))


def verify_pin(directory, protocol):
    registered = read_json(directory / "source-identity.json")
    require(
        digest(registered) == protocol["source_identity_sha256"]
        and sources() == registered,
        "registered diagnostic source bytes changed",
    )
    return registered


def resource_state(directory):
    result = dict(free_disk_bytes=shutil.disk_usage(directory).free)
    for name in ("memory.current", "memory.max", "memory.events", "memory.stat"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            result[name] = path.read_text().strip()
    return result


def bounded(directory, protocol):
    verify_pin(directory, protocol)
    require(
        retained_bytes(directory) < 5_000_000, "diagnostic artifact budget exhausted"
    )
    require(
        shutil.disk_usage(directory).free >= 250_000_000,
        "shared disk reserve exhausted",
    )


def two_cpus():
    if hasattr(os, "sched_getaffinity"):
        chosen = sorted(os.sched_getaffinity(0))[:2]
        os.sched_setaffinity(0, chosen)
        return chosen
    raise ValueError("this registered diagnostic requires Linux CPU affinity")


def validate_protocol(directory, expected):
    protocol = read_json(directory / "protocol.json")
    require(
        digest(protocol)
        == expected
        == read_json(directory / "freeze.json")["protocol_sha256"],
        "frozen diagnostic registration changed",
    )
    require(
        protocol["stages"]
        == {
            "training": 256,
            "memory_teacher": 40,
            "reload_teacher": 40,
            "reload_prefill": 40,
        }
        and protocol["limits"]
        == {"seconds": 600, "threads": 2, "artifact_bytes": 5_000_000}
        and protocol["seed"] == 24029
        and protocol["learning_rate"] == 0.001
        and protocol["base_identity"] == BASE_IDENTITY
        and protocol["rank"] == 8
        and protocol["objective"] == "completion_ce"
        and protocol["no_autoregressive_generation"] is True
        and protocol["maximum_actual_model_forwards"] == 376
        and protocol["retry"] is False
        and protocol["budget_refund"] == 0
        and len(protocol["templates"]) == 4
        and len(protocol["expected_training_order"]) == 256
        and all(
            type(i) is int and 0 <= i < 40 for i in protocol["expected_training_order"]
        ),
        "only the single authorized 376-forward diagnostic is admitted",
    )
    bounded(directory, protocol)
    return protocol
