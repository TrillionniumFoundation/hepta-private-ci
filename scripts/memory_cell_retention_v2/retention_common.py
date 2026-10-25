"""Bounded source pins and immutable evidence for the development screen."""

import importlib.metadata
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[2]
for dependency in (
    "memory_cell",
    "memory_cell_service",
    "memory_cell_network",
    "memory_cell_evolution",
):
    sys.path.insert(0, str(REPO / "scripts" / dependency))

from evolution_common import digest, file_digest, read_json, require, retain

BASE_IDENTITY = "46b83e37620f8bb1ae57754856718886c6aa1b12d267b5b0993e779f9596f96f"
CAMPAIGN = REPO / "scripts/memory_cell_evolution/longitudinal-campaign-002.json"


def source_inventory():
    paths = []
    for name in (
        "memory_cell",
        "memory_cell_service",
        "memory_cell_catalog",
        "memory_cell_retention_v2",
    ):
        paths.extend((REPO / "scripts" / name).glob("*.py"))
    paths.extend(
        REPO / "scripts" / name
        for name in (
            "memory_cell_network/model_process.py",
            "memory_cell_network/model_child.py",
            "memory_cell_evolution/evolution_common.py",
            "memory_cell_evolution/longitudinal_protocol.py",
            "memory_cell_evolution/longitudinal_runtime.py",
            "memory_cell_evolution/longitudinal_scoring.py",
        )
    )
    return {
        str(p.relative_to(REPO)): dict(bytes=p.stat().st_size, sha256=file_digest(p))
        for p in sorted(paths)
    }


def base_inventory(base):
    result = {}
    for path in sorted(Path(base).rglob("*")):
        require(not path.is_symlink(), "model inventory cannot contain symlinks")
        if path.is_file() and ".cache" not in path.relative_to(base).parts:
            result[str(path.relative_to(base))] = dict(
                bytes=path.stat().st_size, sha256=file_digest(path)
            )
    return result


def verify_source_pin(path, expected):
    registered = read_json(path)
    require(digest(registered) == expected, "source pin document changed")
    require(source_inventory() == registered, "runtime source bytes changed")
    return registered


def runtime_versions():
    return dict(
        python=sys.version,
        executable=sys.executable,
        packages={
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "transformers",
                "peft",
                "safetensors",
                "numpy",
                "tokenizers",
            )
        },
    )


def retained_bytes(directory):
    return sum(p.stat().st_size for p in Path(directory).rglob("*") if p.is_file())


def remaining_timeout(deadline, maximum):
    remaining = deadline - time.monotonic()
    require(remaining > 0, "whole-screen time reservation exhausted before dispatch")
    return min(maximum, remaining)
