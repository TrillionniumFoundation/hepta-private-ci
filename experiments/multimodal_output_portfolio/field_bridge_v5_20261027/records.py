"""Append-only trace chains and exact, study-bound phase seals for V5."""

import gzip
import json
from pathlib import Path
import time

from ..field_bridge_v3_20261027.training_common import canonical, file_hash, object_hash, require, write_json


class Journal:
    """Flush each hash-linked record before the next operation starts."""

    def __init__(self, path):
        self.stream = gzip.open(path, "xt", encoding="utf-8")
        self.count, self.head = 0, None

    def append(self, value):
        record = {**value, "record_index": self.count, "committed_monotonic_ns": time.monotonic_ns(),
                  "previous_record_sha256": self.head}
        identity = object_hash(record)
        record["record_sha256"] = identity
        self.stream.write(canonical(record).decode() + "\n")
        self.stream.flush()
        self.count, self.head = self.count + 1, identity
        return identity

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.stream.close()


def complete(path, extra):
    require(not (path / "FAILED.json").exists(), "Cannot seal a failed phase")
    files = {str(p.relative_to(path)): file_hash(p) for p in sorted(path.rglob("*")) if p.is_file()}
    write_json(path / "COMPLETE.json", {**extra, "completed_unix_ns": time.time_ns(), "files": files})


def verify_complete(path, expected=None):
    path = Path(path)
    require(not (path / "FAILED.json").exists(), "Prior stage has a failure receipt")
    record = json.loads((path / "COMPLETE.json").read_text())
    actual = {str(p.relative_to(path)) for p in path.rglob("*")
              if p.is_file() and p != path / "COMPLETE.json"}
    require(actual == set(record["files"]), "Prior stage file inventory changed")
    for name, identity in record["files"].items():
        p = (path / name).resolve()
        require(p.is_relative_to(path.resolve()) and file_hash(p) == identity, "Prior stage changed")
    start = json.loads((path / "START.json").read_text())
    require(record["completed_unix_ns"] >= start["started_unix_ns"], "Invalid phase clock")
    if expected is not None:
        require(all(start.get(k) == v for k, v in expected.items()), "Prior stage belongs to another freeze/study")
    return record
