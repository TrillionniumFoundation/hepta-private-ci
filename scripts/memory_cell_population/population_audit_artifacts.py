"""Independent artifact hashing, byte inventories and immutable tensor states."""

import hashlib
import json
import math
from pathlib import Path
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


def _read(path):
    path = Path(path)
    _require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size <= 64 * 1024 * 1024,
        f"missing, linked or oversized evidence: {path.name}",
    )
    return path.read_bytes()


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
