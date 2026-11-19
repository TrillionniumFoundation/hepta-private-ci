"""Small immutable-file and measurement helpers for the development solver."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import time

from edit_protocol import canonical, sha


class IntegrityError(RuntimeError):
    """Execution cannot be admitted as a valid study observation."""


def retained_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def file_identity(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_pinned(path, expected, limit=8 * 1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular pinned file required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or sha(raw) != expected:
        raise ValueError("pinned input identity changed")
    return json.loads(raw)


def measurement():
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    io = {
        k: int(v)
        for k, v in (
            line.split(": ") for line in Path("/proc/self/io").read_text().splitlines()
        )
    }
    return {
        "monotonic_ns": time.monotonic_ns(),
        "self_cpu_seconds": own.ru_utime + own.ru_stime,
        "waited_child_cpu_seconds": child.ru_utime + child.ru_stime,
        "self_peak_rss_bytes": own.ru_maxrss * 1024,
        "waited_child_peak_rss_bytes": child.ru_maxrss * 1024,
        "process_io": io,
    }


def delta(before, after):
    return {
        "wall_seconds": (after["monotonic_ns"] - before["monotonic_ns"]) / 1e9,
        "self_cpu_seconds": after["self_cpu_seconds"] - before["self_cpu_seconds"],
        "waited_child_cpu_seconds": after["waited_child_cpu_seconds"]
        - before["waited_child_cpu_seconds"],
        "self_peak_rss_bytes": after["self_peak_rss_bytes"],
        "waited_child_peak_rss_bytes": after["waited_child_peak_rss_bytes"],
        "process_io_delta": {
            k: after["process_io"][k] - before["process_io"][k]
            for k in before["process_io"]
        },
    }


def runtime():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "distributions": {
            d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
        },
        "whole_os_dependency_closure_pinned": False,
    }
