"""Exclusive, bounded local evidence for C; no upload and no raw deletion."""

import gzip
import hashlib
import json
import os
from pathlib import Path

from .architecture_state import checkpoint_bytes


class EvidenceStore:
    def __init__(self, root, work, raw_root=None, cap_bytes=350 * 1024 ** 2,
                 global_cap_bytes=1024 ** 3, reserve_bytes=2 * 1024 ** 3,
                 cpu_limit=12 * 3600, wall_limit=6 * 3600, microstep_limit=57536):
        self.root = Path(root).resolve()
        self.raw_root = self.root if raw_root is None else Path(raw_root).resolve()
        if not self.root.is_relative_to(self.raw_root):
            raise ValueError("C evidence must be within the declared shared raw root")
        self.root.mkdir(parents=True, exist_ok=False)
        self.work, self.artifacts = work, []
        self.cap_bytes, self.global_cap_bytes, self.reserve_bytes = cap_bytes, global_cap_bytes, reserve_bytes
        self.cpu_limit, self.wall_limit, self.microstep_limit = cpu_limit, wall_limit, microstep_limit

    def sizes(self):
        local = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        total = sum(path.stat().st_size for path in self.raw_root.rglob("*") if path.is_file())
        return local, total

    def check(self, additional=0, failure_record=False):
        stat = os.statvfs(self.root)
        local, total = self.sizes()
        if stat.f_bavail * stat.f_frsize < self.reserve_bytes + additional or stat.f_favail < 2000:
            raise RuntimeError("Registered allocatable disk/inode reserve exhausted")
        if local + additional > self.cap_bytes or total + additional > self.global_cap_bytes:
            raise RuntimeError("Registered C/global raw evidence cap exhausted")
        snapshot = self.work.snapshot()
        if not failure_record and (snapshot["cpu_seconds"] > self.cpu_limit
                                   or snapshot["wall_seconds"] > self.wall_limit):
            raise RuntimeError("Registered C CPU/wall ceiling exhausted")
        steps = sum(value for key, value in self.work.values.items()
                    if key.endswith(".scheduled_gradient_microsteps"))
        if not failure_record and steps > self.microstep_limit:
            raise RuntimeError("Registered C physical gradient ceiling exhausted")

    def bytes(self, name, payload, failure_record=False):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Evidence path escapes the C directory")
        self.check(len(payload), failure_record=failure_record)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        artifact = {"path": str(path.relative_to(self.root)), "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest()}
        self.artifacts.append(artifact)
        return artifact

    def json(self, name, value, failure_record=False):
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        return self.bytes(name, data, failure_record=failure_record)

    def json_gzip(self, name, value, failure_record=False):
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        return self.bytes(name, gzip.compress(data, mtime=0), failure_record=failure_record)

    def checkpoint(self, name, state, metadata, failure_record=False):
        self.work.add("literal_checkpoint_serializations")
        payload = checkpoint_bytes(state, metadata)
        return self.bytes(name, payload, failure_record=failure_record)
