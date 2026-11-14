"""Bounded development inputs; bindings are not production authorization."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

LIMIT = 1024 * 1024
ID = re.compile(r"[A-Za-z0-9_.:/-]{1,160}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_bound(path, limit=LIMIT):
    path = Path(path)
    require(not path.is_symlink(), "symlink input")
    # Nonblocking open ensures a FIFO cannot hang before the regular-file check.
    fd = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and before.st_size <= limit,
            "oversize/nonregular input",
        )
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    named = path.lstat()
    identity = lambda info: (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    require(
        len(raw) <= limit and identity(before) == identity(after) == identity(named),
        "input changed during read",
    )
    return raw


def load(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)

    return json.loads(read_bound(path), object_pairs_hook=pairs, parse_constant=invalid)


def write_new(path, value):
    raw = canonical(value) + b"\n"
    require(len(raw) <= LIMIT, "oversize output")
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def corpus_documents(corpus):
    require(corpus.get("schema") == "hepta.repo-mdv.corpus.v1", "unknown corpus")
    documents = corpus.get("documents")
    require(
        type(documents) is list and 1 <= len(documents) <= 8, "bounded corpus required"
    )
    seen = set()
    for row in documents:
        require(
            type(row) is dict and ID.fullmatch(row.get("id", "")), "invalid document ID"
        )
        require(row["id"] not in seen, "duplicate document ID")
        seen.add(row["id"])
        require(
            row.get("exposure") == "development",
            "only exposed development material admitted",
        )
        require(
            type(row.get("text")) is str and 0 < len(row["text"].encode()) <= 8192,
            "invalid document size",
        )
        source = row.get("source", {})
        require(
            type(source) is dict and SHA.fullmatch(source.get("sha256", "")),
            "missing source byte pin",
        )
        require(
            type(source.get("reference")) is str
            and 0 < len(source["reference"]) <= 4096,
            "missing provenance reference",
        )
    return documents


def validate_task(task, corpus):
    require(task.get("schema") == "hepta.repo-mdv.dev-task.v1", "unknown task")
    # No caller-provided custody string can silently enable confirmation.
    require(
        task.get("split") == "development",
        "HOLD: independent custody/freeze is not implemented",
    )
    for key in ("task_id", "lineage_group"):
        require(
            type(task.get(key)) is str and ID.fullmatch(task[key]), "invalid " + key
        )
    require(
        type(task.get("query")) is str and 0 < len(task["query"].encode()) <= 8192,
        "invalid query",
    )
    require(
        task.get("origin", {}).get("kind")
        in {"observed_repository_ci", "declared_development_followup"},
        "real development origin required",
    )
    require(
        SHA.fullmatch(task["origin"].get("evidence_sha256", "")),
        "origin evidence pin required",
    )
    budget = task.get("budget", {})
    wall = budget.get("wall_seconds")
    require(
        type(wall) in (int, float) and math.isfinite(wall) and 2 < wall <= 3600,
        "invalid wall budget",
    )
    calls = budget.get("tool_calls")
    require(type(calls) is int and 1 <= calls <= 24, "invalid tool budget")
    documents = corpus_documents(corpus)
    recipes = task.get("recipes", {})
    require(
        type(recipes) is dict and set(recipes) == {row["id"] for row in documents},
        "same document/recipe roster required",
    )
    for steps in recipes.values():
        require(type(steps) is list and 1 <= len(steps) <= calls, "invalid recipe")
        require(
            steps[-1].get("kind") == "verify", "mandatory final verification required"
        )
        for step in steps:
            require(
                step.get("kind") in {"observe", "repair", "verify"},
                "invalid action kind",
            )
            argv = step.get("argv")
            require(type(argv) is list and 1 <= len(argv) <= 64, "invalid argv")
            require(
                all(
                    type(v) is str and 0 < len(v.encode()) <= 8192 and "\0" not in v
                    for v in argv
                ),
                "invalid argument",
            )
            timeout = step.get("timeout_seconds")
            require(
                type(timeout) in (int, float)
                and math.isfinite(timeout)
                and 1 < timeout <= wall,
                "invalid tool timeout",
            )
            require(
                type(step.get("expected_returncode", 0)) is int,
                "invalid expected return code",
            )
            output = step.get("required_output", {})
            require(
                type(output) is dict and set(output) <= {"stdout", "stderr"},
                "invalid output predicate",
            )
            require(
                all(type(v) is str and 0 < len(v) <= 4096 for v in output.values()),
                "invalid output text",
            )
    return task
