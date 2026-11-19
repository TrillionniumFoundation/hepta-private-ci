"""Create-only receipts and exact bounded artifact reads."""

import hashlib
import json
import os
from pathlib import Path
import stat


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(path):
    path = Path(path); before = path.stat(); hasher = hashlib.sha256()
    require(stat.S_ISREG(before.st_mode), "regular identity source")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns),
            "source changed during hashing")
    return {"path": str(path), "bytes": after.st_size, "sha256": hasher.hexdigest()}


def read_exact(row):
    path = Path(row["path"])
    require(not path.is_symlink() and path.is_file(), "regular unsymlinked selected D artifact")
    before = identity(path)
    require(before["sha256"] == row["sha256"] and before["bytes"] == row["bytes"]
            and 0 < before["bytes"] <= 8 * 1024**2, "exact bounded D file identity")
    data = path.read_bytes()
    require(len(data) == row["bytes"] and digest(data) == row["sha256"], "exact loaded D bytes")
    return data


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    return identity(path)


def verify_sources(root):
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        require(identity(root / name)["sha256"] == expected, "frozen source changed: " + name)
    return identity(root / "SOURCE_FREEZE.json")
