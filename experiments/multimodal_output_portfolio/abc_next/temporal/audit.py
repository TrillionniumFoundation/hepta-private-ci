"""Durable artifact writes with no speech observer import or hidden state."""

import hashlib
import json
import os
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_hashes(names):
    root = Path(__file__).parent
    return {name: sha256(root / name) for name in names}
