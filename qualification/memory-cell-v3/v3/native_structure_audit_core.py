"""Read-only evidence loading and numerical assertions for independent audits."""

import hashlib
import json
import math
from pathlib import Path, PurePosixPath

import numpy as np


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def same(actual, expected, label):
    if isinstance(expected, dict):
        require(
            isinstance(actual, dict) and set(actual) == set(expected),
            f"{label}: dictionary keys differ",
        )
        for key in expected:
            same(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, list):
        require(
            isinstance(actual, list) and len(actual) == len(expected),
            f"{label}: list length differs",
        )
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            same(left, right, f"{label}[{index}]")
    elif isinstance(expected, float):
        require(
            isinstance(actual, (float, int))
            and math.isfinite(actual)
            and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
            f"{label}: {actual!r} != {expected!r}",
        )
    else:
        require(
            type(actual) is type(expected) and actual == expected,
            f"{label}: {actual!r} != {expected!r}",
        )


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key {key}")
        result[key] = value
    return result


class Reader:
    def __init__(self, root, seal=None):
        self.root, self.seal = Path(root).resolve(), seal
        self.files = {}

    def path(self, name):
        relative = PurePosixPath(name)
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            f"unsafe evidence path {name}",
        )
        path = self.root.joinpath(*relative.parts)
        cursor = path
        while cursor != self.root:
            require(not cursor.is_symlink(), f"symlink in evidence path {name}")
            cursor = cursor.parent
        require(
            path.is_file() and path.stat().st_size <= 256_000_000,
            f"missing/oversized evidence {name}",
        )
        return path

    def raw(self, name):
        payload = self.path(name).read_bytes()
        identity = {"bytes": len(payload), "sha256": sha(payload)}
        if self.seal is not None and name != "MANIFEST.json":
            require(name in self.seal["files"], f"unsealed evidence {name}")
            same(identity, self.seal["files"][name], name)
        if name in self.files:
            same(identity, self.files[name], f"evidence changed during audit: {name}")
        self.files[name] = identity
        return payload

    def json(self, name):
        return json.loads(
            self.raw(name),
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                AuditError(f"nonfinite JSON {value}")
            ),
        )


def _prefix(prefix, name):
    return f"{prefix}/{name}" if prefix else name


def _packed(reader, name, count):
    raw = reader.raw(name)
    require(len(raw) == (count + 7) // 8, f"{name}: bit count differs")
    flags = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little")
    require(not flags[count:].any(), f"{name}: noncanonical padding")
    return flags[:count].astype(bool)
