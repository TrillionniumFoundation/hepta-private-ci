"""Emit one canonical stdlib-only runtime-discovery observation.

The candidate modules are never imported.  The probe only inspects import
specs and distribution-owned metadata/files for the running interpreter.
"""

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import site
import sys
from pathlib import Path


SCHEMA = "hcsn-n256-runtime-discovery-systempy-v1"
CANDIDATES = ("numpy", "scipy")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_paths(values):
    return [str(Path(value).resolve(strict=False)) for value in values]


def _spec_record(name):
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    loader = None
    if spec.loader is not None:
        loader = f"{type(spec.loader).__module__}.{type(spec.loader).__qualname__}"
    locations = spec.submodule_search_locations
    return {
        "name": spec.name,
        "origin": spec.origin,
        "has_location": spec.has_location,
        "loader_type": loader,
        "submodule_search_locations": None
        if locations is None
        else _canonical_paths(locations),
    }


def _distribution_record(name):
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    files = distribution.files
    if files is None:
        raise ValueError(f"{name} distribution file list unavailable")
    record = distribution.read_text("RECORD")
    anchors = []
    record_paths = []
    expected = f"{name}/__init__.py"
    for entry in files:
        normalized = str(entry).replace(os.sep, "/")
        if normalized.endswith(".dist-info/RECORD"):
            record_paths.append(
                str(Path(distribution.locate_file(entry)).resolve(strict=False))
            )
        if normalized != expected:
            continue
        located = Path(distribution.locate_file(entry)).resolve(strict=False)
        item = {"path": str(located), "exists": located.is_file()}
        if located.is_file():
            item["size"] = located.stat().st_size
            item["sha256"] = _sha256(located)
        anchors.append(item)
    return {
        "canonical_name": distribution.metadata.get("Name"),
        "version": distribution.version,
        "record_paths": record_paths,
        "record_present": record is not None,
        "record_sha256": None
        if record is None
        else hashlib.sha256(record.encode()).hexdigest(),
        "distribution_file_count": len(files),
        "module_anchors": anchors,
    }


def discover():
    executable = Path(sys.executable).resolve(strict=True)
    sys_path = _canonical_paths(sys.path)
    if len(sys_path) > 64:
        raise ValueError("unexpected unbounded sys.path")
    candidates = {}
    for name in CANDIDATES:
        candidates[name] = {
            "spec": _spec_record(name),
            "distribution": _distribution_record(name),
        }
    return {
        "schema": SCHEMA,
        "runtime": {
            "python_version": platform.python_version(),
            "python_executable": str(executable),
            "python_executable_sha256": _sha256(executable),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "sys_prefix": str(Path(sys.prefix).resolve(strict=False)),
            "sys_base_prefix": str(Path(sys.base_prefix).resolve(strict=False)),
            "sys_path": sys_path,
            "no_user_site_flag": sys.flags.no_user_site,
            "enable_user_site": site.ENABLE_USER_SITE,
            "user_site": str(Path(site.getusersitepackages()).resolve(strict=False)),
            "site_packages": _canonical_paths(site.getsitepackages()),
        },
        "candidates": candidates,
        "counts": {
            "candidate_module_imports": 0,
            "n256_input_reads": 0,
            "n256_serializer_calls": 0,
            "dynamic_steps": 0,
            "matrix_exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "mutated_runtime": False,
        "runtime_admitted": False,
        "resource_admitted": False,
        "status": "PASS_DISCOVERY_HOLD_RUNTIME_ADMISSION",
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(discover(), allow_nan=False, separators=(",", ":"), sort_keys=True))
