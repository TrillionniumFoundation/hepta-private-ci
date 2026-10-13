"""Dependency-free byte contracts shared by model and private browser experiments.

Importing a controller must not initialize Torch, NumPy or pretrained models.
These helpers retain the original canonical bytes and create-only write rules.
"""
import hashlib
import json
import os


class InputError(ValueError):
    """An input cannot be interpreted under the frozen experiment contract."""


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(raw: bytes):
    def invalid(value):
        raise InputError(f"nonfinite JSON number: {value}")
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)
    canonical(value)
    return value


def write_once(path, value):
    raw = canonical(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)
