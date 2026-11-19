"""Independent artifact hashing, byte inventories and immutable tensor states."""

from contextvars import ContextVar
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct


SEEDS = (1907, 2719, 4051)


ARMS = ("parent", "single", "split")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _hash(_bytes(value))


_READ_DIGESTS = ContextVar("population_audit_read_digests", default=None)


def _consistent_reads(function):
    """Bind repeated helper reads for one audit, including nested trial audits."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        if _READ_DIGESTS.get() is not None:
            return function(*args, **kwargs)
        token = _READ_DIGESTS.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _READ_DIGESTS.reset(token)

    return wrapped


def _read(path):
    path = Path(path)
    message = f"missing, linked, changed or oversized evidence: {path.name}"

    def identity(info):
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    try:
        before = path.lstat()
        _require(
            stat.S_ISREG(before.st_mode) and before.st_size <= 64 * 1024 * 1024,
            message,
        )
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(identity(opened) == identity(before), message)
            raw = stream.read(opened.st_size + 1)
            _require(
                len(raw) == opened.st_size
                and identity(os.fstat(stream.fileno())) == identity(opened),
                message,
            )
    except OSError as error:
        raise ValueError(message) from error
    bindings = _READ_DIGESTS.get()
    if bindings is not None:
        key = os.path.abspath(path)
        actual = _hash(raw)
        previous = bindings.setdefault(key, actual)
        _require(previous == actual, f"evidence changed during audit: {path.name}")
    return raw


def _json(path):
    return json.loads(_read(path))


def _same(actual, expected, name):
    if isinstance(expected, float):
        _require(
            type(actual) in (int, float)
            and math.isfinite(actual)
            and abs(actual - expected) <= 1e-10,
            name,
        )
    elif isinstance(expected, dict):
        _require(isinstance(actual, dict) and set(actual) == set(expected), name)
        for key in expected:
            _same(actual[key], expected[key], f"{name}.{key}")
    elif isinstance(expected, list):
        _require(isinstance(actual, list) and len(actual) == len(expected), name)
        for index, value in enumerate(expected):
            _same(actual[index], value, f"{name}[{index}]")
    else:
        _require(type(actual) is type(expected) and actual == expected, name)


def _checkpoint(version):
    directory = Path(version["directory"])
    manifest_raw = _read(directory / "lineage.json")
    _require(
        _hash(manifest_raw) == version["manifest_sha256"], "checkpoint manifest pin"
    )
    manifest = json.loads(manifest_raw)
    raw, config_raw = (
        _read(directory / "adapter_model.safetensors"),
        _read(directory / "adapter_config.json"),
    )
    config = json.loads(config_raw)
    _require(
        _hash(raw) == manifest["adapter_sha256"]
        and _hash(config_raw) == manifest["config_sha256"],
        "checkpoint payload pins",
    )
    _require(
        config["r"] == version["rank"] and config["lora_alpha"] / config["r"] == 2,
        "actual rank and LoRA scaling",
    )
    _require(
        manifest["roots"] == version["roots"]
        and manifest["production_accepted"] is False
        and manifest["model_install_authority"] is False,
        "checkpoint ancestry and authority",
    )
    header_length = struct.unpack("<Q", raw[:8])[0]
    _require(0 < header_length <= 1024 * 1024, "bounded tensor header")
    header, data = json.loads(raw[8 : 8 + header_length]), raw[8 + header_length :]
    tensors, intervals, state = {}, [], hashlib.sha256()
    for name in sorted(set(header) - {"__metadata__"}):
        row = header[name]
        begin, end = row["data_offsets"]
        shape = row["shape"]
        _require(
            row["dtype"] == "F32"
            and len(shape) == 2
            and all(type(v) is int and v > 0 for v in shape)
            and end - begin == math.prod(shape) * 4
            and 0 <= begin < end <= len(data),
            "actual tensor layout",
        )
        payload = data[begin:end]
        _require(
            all(math.isfinite(v[0]) for v in struct.iter_unpack("<f", payload)),
            "finite adapter tensors",
        )
        state.update(_digest([name, shape, "torch.float32"]).encode())
        state.update(payload)
        tensors[name] = (shape, payload)
        intervals.append((begin, end))
    cursor = 0
    for begin, end in sorted(intervals):
        _require(begin == cursor, "contiguous nonoverlapping tensor payload")
        cursor = end
    _require(cursor == len(data), "no unaccounted adapter bytes")
    _require(
        state.hexdigest() == manifest["training"]["adapter_state_sha256"],
        "actual adapter-state receipt",
    )
    return {
        "manifest": manifest,
        "tensors": tensors,
        "state": state.hexdigest(),
        "private_bytes": len(data),
        "retained_bytes": sum(
            p.stat().st_size for p in directory.iterdir() if p.is_file()
        ),
    }
