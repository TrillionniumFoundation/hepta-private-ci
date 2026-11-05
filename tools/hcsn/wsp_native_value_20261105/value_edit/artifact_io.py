"""Deterministic, create-only research artifacts; no external application writes."""
import gzip
import hashlib
import json
import os
from pathlib import Path

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False,
                       default=lambda x: x.tolist() if isinstance(x, np.ndarray) else x.item()) + "\n").encode()


def save(path, value):
    path = Path(path)
    data = json_bytes(value)
    if path.suffix == ".gz":
        data = gzip.compress(data, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(data)


def read(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def identity(path):
    path = Path(path)
    data = path.read_bytes()
    return dict(bytes=len(data), sha256=sha(data))


def verify_manifest(root, files):
    for name, expected in files.items():
        if identity(Path(root) / name) != expected:
            raise ValueError("source/input identity mismatch: " + name)


class EventChain:
    """A local ordering record, explicitly not an external preregistration."""
    def __init__(self, root):
        self.root = Path(root)
        self.sequence = 0
        self.previous = None

    def add(self, kind, payload):
        import datetime
        record = dict(sequence=self.sequence, previous_sha256=self.previous,
                      utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      kind=kind, payload=payload)
        path = self.root / "events" / f"{self.sequence:04d}_{kind}.json"
        self.previous = save(path, record)
        self.sequence += 1
        return self.previous
