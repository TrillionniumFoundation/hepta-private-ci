#!/usr/bin/env python3
"""Record observed Linux memory capacity without inventing missing limits."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import sys

MINIMUM = 12 * 1024**3


def read(path, maximum):
    try:
        with path.open("rb") as handle:
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("probe exceeds its byte bound")
        return dict(path=str(path), content=raw.decode().strip(), error=None)
    except (OSError, UnicodeError, ValueError) as error:
        return dict(path=str(path), content=None, error=type(error).__name__)


def unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def process_paths(groups, mounts):
    """Map this process through observed mount roots; unknown mappings stay out."""
    paths = set()
    for row in groups.splitlines():
        parts = row.split(":", 2)
        if len(parts) != 3:
            continue
        controllers = parts[1].split(",")
        version = (
            2
            if parts[0] == "0" and parts[1] == ""
            else 1
            if "memory" in controllers
            else None
        )
        group = PurePosixPath(parts[2])
        if version is None or not group.is_absolute() or ".." in group.parts:
            continue
        for mount in mounts.splitlines():
            before, separator, after = mount.partition(" - ")
            left, right = before.split(), after.split()
            if not separator or len(left) < 5 or len(right) < 3:
                continue
            if not (
                version == 2
                and right[0] == "cgroup2"
                or version == 1
                and right[0] == "cgroup"
                and "memory" in right[2].split(",")
            ):
                continue
            root, point = PurePosixPath(unescape(left[3])), Path(unescape(left[4]))
            if (
                not root.is_absolute()
                or not point.is_absolute()
                or ".." in root.parts
                or ".." in point.parts
                or not group.is_relative_to(root)
            ):
                continue
            current = point / group.relative_to(root)
            name = "memory.max" if version == 2 else "memory.limit_in_bytes"
            for _ in range(256):
                paths.add(current / name)
                if current == point:
                    break
                current = current.parent
    return paths


def snapshot():
    physical = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    groups = read(Path("/proc/self/cgroup"), 65536)
    mounts = read(Path("/proc/self/mountinfo"), 1024 * 1024)
    mapped = process_paths(groups["content"] or "", mounts["content"] or "")
    candidates = mapped | {
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        Path("/sys/fs/cgroup/memory.limit_in_bytes"),
    }
    probes, finite = [], []
    for path in sorted(candidates):
        probe = read(path, 4096)
        probe.update(
            mapped_to_process=path in mapped, limit_bytes=None, state="unavailable"
        )
        value = probe["content"]
        if value == "max":
            probe["state"] = "explicit-max-at-this-visible-group"
        elif value is not None and value.isdecimal() and int(value) > 0:
            probe.update(state="reported-numeric-limit", limit_bytes=int(value))
            if path in mapped:
                finite.append(int(value))
        elif value is not None:
            probe["state"] = "unrecognized"
        probes.append(probe)
    observed = min(finite) if finite else None
    return dict(
        schema="hepta-observed-linux-host-resources-v2",
        python=sys.version,
        platform=platform.platform(),
        cpu_count=os.cpu_count(),
        physical_memory_bytes=physical,
        physical_capacity_meets_12_gib=physical >= MINIMUM,
        proc_self_cgroup=groups,
        proc_self_mountinfo=mounts,
        cgroup_limit_probes=probes,
        observed_cgroup_limit_upper_bound_bytes=observed,
        effective_memory_upper_bound_bytes=min(physical, observed)
        if observed is not None
        else physical,
        observed_limit_excludes_12_gib=observed is not None and observed < MINIMUM,
        effective_limit_known=False,
        effective_memory_bytes=None,
        resource_capacity_qualified=False,
        resource_scope="resource_limit_unknown",
        limitation="Visible cgroup probes do not attest hidden ancestors or available memory; missing is not unlimited.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = snapshot()
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    if sys.version_info[:3] != (3, 12, 3):
        raise SystemExit("exact CPython 3.12.3 required")
    if (
        not result["physical_capacity_meets_12_gib"]
        or result["observed_limit_excludes_12_gib"]
    ):
        raise SystemExit("observed capacity excludes the required hosted model window")


if __name__ == "__main__":
    main()
