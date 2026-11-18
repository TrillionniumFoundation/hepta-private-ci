"""Read the current Linux cgroup's accounting without changing its membership.

These sequential snapshots include all work charged to that cgroup. They are
neither process-tree RSS nor a campaign peak unless a separate lifecycle record
establishes the accounting boundary. No energy or complete-cost claim is made.
"""

import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time


FILES = (
    "memory.current",
    "memory.peak",
    "memory.stat",
    "memory.events",
    "cpu.stat",
    "pids.current",
    "pids.max",
    "cgroup.events",
)


def _read_text(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        text = stream.read(1024 * 1024 + 1)
    if len(text) > 1024 * 1024:
        raise ValueError("accounting record exceeds 1 MiB")
    return text


def _unescape(value):
    return re.sub(r"\\(040|011|012|134)", lambda m: chr(int(m[1], 8)), value)


def _path(value):
    if (
        not value.startswith("/")
        or "\0" in value
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError("invalid cgroup path")
    return PurePosixPath(value)


def _location(cgroup, mountinfo):
    rows = [line[3:] for line in cgroup.splitlines() if line.startswith("0::")]
    if len(rows) != 1:
        raise ValueError("one unified cgroup membership is required")
    membership = _path(rows[0])
    candidates = []
    for line in mountinfo.splitlines():
        parts = line.split()
        separator = parts.index("-") if "-" in parts else -1
        if separator < 6 or len(parts) <= separator + 1:
            continue
        if parts[separator + 1] != "cgroup2":
            continue
        root, mount = (_path(_unescape(parts[index])) for index in (3, 4))
        if membership.is_relative_to(root):
            candidates.append((len(root.parts), root, mount))
    if not candidates:
        raise ValueError("no cgroup2 mount maps the current membership")
    depth = max(item[0] for item in candidates)
    selected = {(root, mount) for level, root, mount in candidates if level == depth}
    if len(selected) != 1:
        raise ValueError("ambiguous cgroup2 mount mapping")
    root, mount = selected.pop()
    return {
        "membership": str(membership),
        "mount_root": str(root),
        "mount_point": str(mount),
        "directory": str(mount / membership.relative_to(root)),
    }


def _directory_identity(path):
    info = Path(path).stat()
    return {"device": info.st_dev, "inode": info.st_ino}


def _metric(name, raw):
    text = raw.strip()
    if name == "pids.max" and text == "max":
        return "max"
    if name in {"memory.current", "memory.peak", "pids.current", "pids.max"}:
        if not text.isascii() or not text.isdigit():
            raise ValueError("nonnegative accounting counter required")
        return int(text)
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if (
            len(parts) != 2
            or parts[0] in values
            or not parts[1].isascii()
            or not parts[1].isdigit()
        ):
            raise ValueError("invalid or duplicate accounting counter")
        values[parts[0]] = int(parts[1])
    if not values:
        raise ValueError("empty accounting record")
    return values


def observe_current_cgroup():
    """Return bounded read observations; absent or unstable values stay unknown."""
    report = {
        "schema": "hepta.cgroup-observation.v1",
        "status": "UNAVAILABLE",
        "pid": os.getpid(),
        "capture_started_ns": time.perf_counter_ns(),
        "identity": None,
        "identity_stable": None,
        "metrics": {name: {"status": "UNKNOWN", "value": None} for name in FILES},
        "scope": "current cgroup accounting; sequential file reads, not atomic",
        "memory_peak_scope": "charged memory since cgroup creation or last reset; origin not established",
        "campaign_coverage_verified": False,
        "campaign_process_tree_peak_rss_bytes": None,
        "physical_energy_joules": None,
        "full_system_cost_known": False,
    }
    try:
        if not sys.platform.startswith("linux"):
            report["reason"] = "Linux cgroup2 is required"
            return report
        before = _read_text("/proc/self/cgroup")
        mounts = _read_text("/proc/self/mountinfo")
        location = _location(before, mounts)
        identity = _directory_identity(location["directory"])
        report["identity"] = {**location, **identity}
        for name in FILES:
            observation = {"status": "UNKNOWN", "value": None}
            try:
                raw = _read_text(Path(location["directory"]) / name)
                observation["raw"] = raw
                observation.update(status="OBSERVED", value=_metric(name, raw))
            except (OSError, ValueError) as error:
                observation["error_type"] = type(error).__name__
            observation["read_completed_ns"] = time.perf_counter_ns()
            report["metrics"][name] = observation
        try:
            stable = (
                before == _read_text("/proc/self/cgroup")
                and location == _location(before, _read_text("/proc/self/mountinfo"))
                and identity == _directory_identity(location["directory"])
            )
        except (OSError, ValueError):
            stable = False
        report["identity_stable"] = stable
        if not stable:
            report["status"] = "UNSTABLE_IDENTITY"
            for observation in report["metrics"].values():
                observation["value"] = None
                observation["status"] = "UNKNOWN"
        else:
            report["status"] = (
                "OBSERVED"
                if all(
                    row["status"] == "OBSERVED" for row in report["metrics"].values()
                )
                else "PARTIAL"
            )
        return report
    except (OSError, ValueError) as error:
        report["reason"] = str(error)
        report["error_type"] = type(error).__name__
        return report
    finally:
        report["capture_ended_ns"] = time.perf_counter_ns()


if __name__ == "__main__":
    print(json.dumps(observe_current_cgroup(), sort_keys=True, allow_nan=False))
