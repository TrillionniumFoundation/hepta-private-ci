"""Declared storage, physical aliases and content equality are separate quantities."""

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import stat
import time


KINDS = {
    "source",
    "source_evidence",
    "base",
    "adapter",
    "router",
    "index",
    "runtime",
    "tools",
    "audit",
    "protocol",
}
STAMP = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def stamp(value):
    return tuple(getattr(value, name) for name in STAMP)


def file_record(path, cache=None):
    """Stream bytes, verify the opened inode and reject changed path bindings."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("inventory requires regular files, not links/devices")
    key = (before.st_dev, before.st_ino)
    cached = (cache or {}).get(key)
    read_bytes = 0
    if cached and cached[0] == stamp(before):
        digest = cached[1]
    else:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            if stamp(os.fstat(stream.fileno())) != stamp(before):
                raise ValueError("file changed while opening")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                read_bytes += len(chunk)
            if stamp(os.fstat(stream.fileno())) != stamp(before):
                raise ValueError("file changed while hashing")
        digest = digest.hexdigest()
        if cache is not None:
            cache[key] = (stamp(before), digest)
    if stamp(path.lstat()) != stamp(before):
        raise ValueError("file path changed during measurement")
    return {
        "path": str(path),
        "bytes": before.st_size,
        "sha256": digest,
        "physical_key": list(key),
        "links": before.st_nlink,
        "allocated_bytes": before.st_blocks * 512
        if hasattr(before, "st_blocks")
        else None,
    }, read_bytes


def summary(files):
    inodes, contents = {}, {}
    for row in files:
        identity = tuple(row["physical_key"])
        if identity in inodes and any(
            inodes[identity][k] != row[k]
            for k in ("bytes", "sha256", "allocated_bytes")
        ):
            raise ValueError("one inode has inconsistent observations")
        inodes[identity] = row
        contents[(row["sha256"], row["bytes"])] = row["bytes"]
    logical = sum(row["bytes"] for row in files)
    physical = sum(row["bytes"] for row in inodes.values())
    content = sum(contents.values())
    allocations = [row["allocated_bytes"] for row in inodes.values()]
    return {
        "file_entries": len(files),
        "physical_files": len(inodes),
        "logical_file_bytes": logical,
        "physical_payload_bytes": physical,
        "allocated_file_bytes": None if None in allocations else sum(allocations),
        "content_unique_bytes": content,
        "hardlink_repeated_path_bytes": logical - physical,
        "content_duplicate_inode_bytes": physical - content,
        "content_deduplication_actually_applied": False,
        "filesystem_metadata_bytes": None,
    }


def inventory(components):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    roots, names, files, cache, read_bytes, observed = [], set(), [], {}, 0, {}
    listings = {}
    for component in components:
        if (
            set(component) != {"name", "kind", "paths"}
            or component["kind"] not in KINDS
            or component["name"] in names
            or not component["paths"]
        ):
            raise ValueError(
                "distinct named components and explicit nonempty roots required"
            )
        names.add(component["name"])
        for raw in component["paths"]:
            root = Path(raw)
            if not root.is_absolute() or root.resolve() != root or not root.exists():
                raise ValueError("explicit existing canonical roots required")
            if any(
                root == old or root.is_relative_to(old) or old.is_relative_to(root)
                for old in roots
            ):
                raise ValueError("overlapping inventory roots")
            roots.append(root)
            paths = [root] if root.is_file() else sorted(root.rglob("*"))
            listings[root] = paths
            for path in paths:
                mode = path.lstat().st_mode
                if stat.S_ISDIR(mode):
                    continue
                row, charged = file_record(path, cache)
                files.append(
                    dict(row, component=component["name"], kind=component["kind"])
                )
                read_bytes += charged
                observed[path] = cache[tuple(row["physical_key"])][0]
    for root, paths in listings.items():
        if ([root] if root.is_file() else sorted(root.rglob("*"))) != paths:
            raise ValueError("component membership changed during measurement")
    if any(stamp(path.lstat()) != old for path, old in observed.items()):
        raise ValueError("component metadata changed before inventory cutoff")
    return {
        "schema": "hepta.memory.storage-inventory.v2",
        "components": components,
        "files": files,
        "totals": summary(files),
        "by_component": {
            name: summary([r for r in files if r["component"] == name])
            for name in sorted(names)
        },
        "inventory_measurement": {
            "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": time.process_time_ns() - cpu,
            "hash_read_bytes": read_bytes,
        },
        "whole_os_bytes": None,
        "dynamic_dependency_closure_complete": False,
        "atomic_filesystem_snapshot": False,
    }


def deployment(inventory_record, placements):
    """Explicit hypothetical hosts share existing components only within a host.

    A repeated pathname is one retained object on the shared host. Moving a
    consumer to a new host copies its required components, including any base it
    actually uses. Equal bytes on different inodes never imply physical dedup.
    """
    by_name = {c["name"] for c in inventory_record["components"]}
    hosts, consumers, references = defaultdict(set), set(), 0
    for row in placements:
        if (
            set(row) != {"host", "consumer", "components"}
            or row["consumer"] in consumers
            or not row["host"]
            or len(row["components"]) != len(set(row["components"]))
            or not set(row["components"]) <= by_name
        ):
            raise ValueError("distinct consumers and registered dependencies required")
        consumers.add(row["consumer"])
        hosts[row["host"]].update(row["components"])
        references += sum(
            r["bytes"]
            for r in inventory_record["files"]
            if r["component"] in row["components"]
        )
    views = {
        host: summary([r for r in inventory_record["files"] if r["component"] in names])
        for host, names in hosts.items()
    }
    quantities = (
        "logical_file_bytes",
        "physical_payload_bytes",
        "allocated_file_bytes",
        "content_unique_bytes",
        "hardlink_repeated_path_bytes",
        "content_duplicate_inode_bytes",
    )
    totals = {
        key: None
        if any(v[key] is None for v in views.values())
        else sum(v[key] for v in views.values())
        for key in quantities
    }
    return {
        "placements": placements,
        "hosts": views,
        "totals": totals,
        "dependency_reference_bytes": references,
        "basis": "explicit deployment projection from observed files; not measured multiple hosts",
    }


def compression_gain(memory_bytes, retrieval_bytes, quality):
    """Require complete paired independent quality and the declared closure."""
    required = {"scope", "minimum_groups", "complete_cost_closure", "rows"}
    if (
        set(quality) != required
        or type(quality["minimum_groups"]) is not int
        or quality["minimum_groups"] < 1
    ):
        raise ValueError("explicit nonzero quality gate required")
    ids, groups = set(), set()
    for row in quality["rows"]:
        if (
            set(row)
            != {
                "task_id",
                "group_id",
                "memory_supported",
                "memory_passed",
                "retrieval_supported",
                "retrieval_passed",
            }
            or row["task_id"] in ids
            or not row["group_id"]
            or any(
                type(row[k]) is not bool
                for k in row
                if k.endswith(("supported", "passed"))
            )
        ):
            raise ValueError(
                "distinct paired tasks and explicit boolean outcomes required"
            )
        ids.add(row["task_id"])
        groups.add(row["group_id"])
    reasons = []
    if quality["scope"] != "independent-future-tasks":
        reasons.append("not_independent_future_quality")
    if len(groups) < quality["minimum_groups"]:
        reasons.append("insufficient_independent_groups")
    if quality["complete_cost_closure"] is not True:
        reasons.append("incomplete_cost_closure")
    if any(
        not row[k]
        for row in quality["rows"]
        for k in row
        if k.endswith(("supported", "passed"))
    ):
        reasons.append("support_or_task_quality_below_required_one")
    if (
        type(memory_bytes) is not int
        or memory_bytes < 0
        or type(retrieval_bytes) is not int
        or retrieval_bytes <= 0
    ):
        reasons.append("missing_positive_storage_denominator")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "tasks": len(ids),
        "independent_groups": len(groups),
        "net_storage_reduction_fraction": None
        if reasons
        else 1 - memory_bytes / retrieval_bytes,
    }
