"""Bounded, read-only primitives for the four-gate research review.

Digests and caller timestamps establish consistency, NOT signer authority,
physical execution, independent outcomes, or deployment permission.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat
from collections import defaultdict
from datetime import datetime, timezone

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
COST_AXES = ("cpu_ns", "gpu_ns", "energy_uj", "wall_ns")
PHASES = ("load", "warmup", "inference", "training", "search", "evaluation", "migration")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, minimum=0):
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum,
            f"invalid finite {name}")
    return value


def integer(value, name, minimum=0, maximum=MAX_ROWS):
    require(type(value) is int and minimum <= value <= maximum, f"invalid {name}")
    return value


def sha(value, size=64):
    require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{size}}}", value)
            and value != "0" * size, "missing immutable SHA identity")
    return value


def text(value, name):
    require(isinstance(value, str) and 0 < len(value) <= 256, f"invalid {name}")
    return value


def timestamp(value):
    require(isinstance(value, str), "missing timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "timezone required")
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid timezone-aware timestamp") from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_loads(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")

    def finite(value):
        if isinstance(value, float):
            require(math.isfinite(value), "overflowed JSON number")
        elif isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)

    require(len(raw) <= MAX_BYTES, "oversized JSON")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        finite(value)
        return value
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid or excessively nested JSON") from exc


def read_pinned(root, reference, *, form="json"):
    """Read a contained, nonsymlink regular file; verify original bytes first.

    The caller must supply a trusted, private evidence root. This is not a
    hostile-directory sandbox or an authenticated Artifact CAS reader.
    """
    require(type(reference) is dict and set(reference) == {"path", "sha256"},
            "evidence reference requires path and sha256 only")
    sha(reference["sha256"])
    root = Path(root).resolve(strict=True)
    relative = Path(reference["path"])
    require(not relative.is_absolute() and relative.parts and
            all(p not in (".", "..") for p in relative.parts), "escaping evidence path")
    path = root
    for part in relative.parts:
        path = path / part
        require(not path.is_symlink(), "symlink evidence is not admitted")
    require(path.resolve(strict=True).is_relative_to(root), "escaping evidence path")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES,
                "evidence must be a bounded regular file")
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == reference["sha256"],
            "evidence byte SHA mismatch")
    if form == "bytes":
        return raw
    if form == "jsonl":
        lines = raw.splitlines()
        require(0 < len(lines) <= MAX_ROWS and all(line.strip() for line in lines),
                "blank or excessive JSONL records")
        rows = [strict_loads(line) for line in lines]
        require(all(type(row) is dict for row in rows), "JSONL requires objects")
        return rows
    require(form == "json", "unsupported evidence format")
    return strict_loads(raw)


def write_once(path, value):
    raw = canonical(value) + b"\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Directory durability is asserted only for this POSIX path.
    if os.name == "posix":
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def percentile(values, quantile):
    require(bool(values) and 0 <= quantile <= 1, "empty percentile")
    values = sorted(values)
    index = (len(values) - 1) * quantile
    lo = math.floor(index)
    hi = math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def grouped_interval(rows, *, alpha, replicates, seed, min_groups):
    """Equal-source-cluster paired percentile bootstrap; not an iid Cell CI.

    rows are (source_cluster, candidate-minus-control). Cluster independence is
    a design assumption, not established by strings or signatures.
    """
    require(0 < alpha < 1, "invalid comparison alpha")
    integer(replicates, "bootstrap replicates", 1000, 100_000)
    integer(min_groups, "minimum groups", 2, MAX_ROWS)
    groups = defaultdict(list)
    for group, delta in rows:
        text(group, "source cluster")
        require(type(delta) in (int, float) and math.isfinite(delta), "invalid paired delta")
        groups[group].append(delta)
    require(bool(groups), "missing paired groups")
    means = [sum(groups[group]) / len(groups[group]) for group in sorted(groups)]
    n = len(means)
    require(n * replicates <= 20_000_000, "bootstrap work budget exceeded")
    rng = random.Random(seed)
    samples = sorted(sum(means[rng.randrange(n)] for _ in range(n)) / n
                     for _ in range(replicates))
    return {"groups": n, "rows": sum(map(len, groups.values())),
            "mean": sum(means) / n,
            "lcb": percentile(samples, alpha / 2),
            "ucb": percentile(samples, 1 - alpha / 2),
            "enough_groups": n >= min_groups, "alpha": alpha,
            "method": "equal_source_cluster_paired_percentile_bootstrap",
            "independence_authenticated": False}


def costs(value, required_axes):
    require(type(value) is dict and set(value) == set(COST_AXES), "complete cost axes required")
    for axis in COST_AXES:
        if value[axis] is None:
            require(axis not in required_axes, f"missing measured {axis}")
        else:
            number(value[axis], axis)
    return value


def lifecycle(value, required_axes):
    require(type(value) is dict and set(value) == set(PHASES), "complete lifecycle phases required")
    totals = {axis: 0 for axis in COST_AXES}
    seen = set()
    for phase in PHASES:
        row = value[phase]
        require(type(row) is dict and set(row) == {"job_id", "cost"}, "invalid lifecycle job")
        job = text(row["job_id"], "physical job id")
        require(job not in seen, "physical work charged in multiple lifecycle phases")
        seen.add(job)
        measured = costs(row["cost"], required_axes)
        for axis in COST_AXES:
            totals[axis] = (None if totals[axis] is None or measured[axis] is None
                            else totals[axis] + measured[axis])
    return totals


def result(passed, metrics, blockers=()):
    return {"status": "diagnostic_pass" if passed else "not_passed",
            "metrics": metrics, "blockers": list(blockers),
            "execution_authenticated": False,
            "independent_outcomes_authenticated": False,
            "production_promotion_permitted": False}
