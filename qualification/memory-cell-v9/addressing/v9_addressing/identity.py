"""Closed runtime import identity, separate from public training inputs."""

import hashlib
from pathlib import Path

from addressing.contracts import digest


SCHEMA = "hepta.memory.v9.compatibility-intent-model.v1"
MAX_ARTIFACT_BYTES = 16_000_000


def runtime_paths():
    here = Path(__file__).resolve().parent
    qualification = here.parents[2]
    paths = [here / name for name in ("__init__.py", "identity.py", "model.py", "artifact.py", "policy.py", "capabilities.py")]
    paths += [here.parent / name for name in ("worker.py", "qualification_shadow_worker.py", "bootstrap.py")]
    paths += [qualification / "memory-cell-v7/addressing" / name for name in (
        "__init__.py", "contracts.py", "capabilities.py", "model.py", "planner.py", "worker.py")]
    paths += [qualification / "memory-cell-v6/v6" / name for name in ("__init__.py", "encoder.py")]
    return qualification, sorted(paths)


def policy_digest():
    qualification, paths = runtime_paths()
    return digest({path.relative_to(qualification).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in paths})


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model field")
        result[key] = value
    return result
