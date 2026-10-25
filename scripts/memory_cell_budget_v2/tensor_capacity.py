"""Admit pinned safetensors storage without importing torch or loading a model."""

from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

from common import digest, read_json
from scripts.memory_cell_cost_v2.storage_ledger import file_record, stamp


WIDTH = {
    "BOOL": 1,
    "I8": 1,
    "U8": 1,
    "I16": 2,
    "U16": 2,
    "F16": 2,
    "BF16": 2,
    "I32": 4,
    "U32": 4,
    "F32": 4,
    "I64": 8,
    "U64": 8,
    "F64": 8,
}
ROLES = {
    "active_adapter",
    "active_router",
    "retained_parent",
    "frozen_base",
    "optimizer",
    "gradient",
}
LIMITS = {"active_values", "active_tensor_bytes", "unique_checkpoint_bytes"}


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate safetensors JSON key")
        value[key] = item
    return value


def tensor_file(path, expected):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected["bytes"]:
        raise ValueError("pinned regular checkpoint size required")
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        if stamp(os.fstat(stream.fileno())) != stamp(before):
            raise ValueError("checkpoint changed while opening")
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError("missing safetensors header")
        length = struct.unpack("<Q", prefix)[0]
        if not 2 <= length <= min(16 * 1024**2, before.st_size - 8):
            raise ValueError("bounded safetensors header required")
        header = stream.read(length)
        hashed.update(prefix + header)
        for chunk in iter(lambda: stream.read(1024**2), b""):
            hashed.update(chunk)
        if stamp(os.fstat(stream.fileno())) != stamp(before):
            raise ValueError("checkpoint changed while hashing")
    if stamp(path.lstat()) != stamp(before) or hashed.hexdigest() != expected["sha256"]:
        raise ValueError("checkpoint identity changed")
    parsed = json.loads(header, object_pairs_hook=unique)
    if type(parsed) is not dict:
        raise ValueError("safetensors object required")
    metadata = parsed.pop("__metadata__", {})
    if type(metadata) is not dict or any(type(v) is not str for v in metadata.values()):
        raise ValueError("invalid safetensors metadata")
    rows, cursor = [], 0
    for name, tensor in parsed.items():
        if type(tensor) is not dict or set(tensor) != {
            "dtype",
            "shape",
            "data_offsets",
        }:
            raise ValueError("unknown tensor fields")
        dtype, shape, offsets = tensor["dtype"], tensor["shape"], tensor["data_offsets"]
        if (
            dtype not in WIDTH
            or type(shape) is not list
            or any(type(v) is not int or v <= 0 for v in shape)
        ):
            raise ValueError("unsupported tensor dtype or shape")
        count = math.prod(shape)
        if (
            type(offsets) is not list
            or len(offsets) != 2
            or any(type(v) is not int or v < 0 for v in offsets)
            or offsets[1] - offsets[0] != count * WIDTH[dtype]
        ):
            raise ValueError("tensor byte range disagrees with shape/dtype")
        rows.append(
            {"name": name, **tensor, "values": count, "bytes": count * WIDTH[dtype]}
        )
    for row in sorted(rows, key=lambda r: r["data_offsets"]):
        if row["data_offsets"][0] != cursor:
            raise ValueError("tensor overlap or unaccounted payload")
        cursor = row["data_offsets"][1]
    if not rows or cursor != before.st_size - length - 8:
        raise ValueError("checkpoint payload is not completely described")
    return {
        "identity": expected,
        "physical_key": [before.st_dev, before.st_ino],
        "tensors": rows,
        "values": sum(row["values"] for row in rows),
        "tensor_bytes": cursor,
    }


def adapter_shape(component, tensors):
    rank, targets = component["rank"], component["targets"]
    if (
        type(rank) is not int
        or not 1 <= rank <= 256
        or not targets
        or len(targets) != len(set(targets))
    ):
        raise ValueError("explicit bounded adapter rank and targets required")
    spec = component["config"]
    config = read_json(spec["path"], spec["identity"])
    if (
        config.get("peft_type") != "LORA"
        or type(config.get("r")) is not int
        or config.get("r") != rank
        or sorted(config.get("target_modules", [])) != sorted(targets)
        or config.get("rank_pattern")
        or config.get("modules_to_save")
        or config.get("use_dora")
        or config.get("bias", "none") != "none"
    ):
        raise ValueError("adapter configuration differs from admitted tensor contract")
    pairs = defaultdict(dict)
    for row in tensors:
        match = re.fullmatch(r"(.+)\.lora_([AB])\.weight", row["name"])
        if (
            not match
            or match[1].rsplit(".", 1)[-1] not in targets
            or row["dtype"] not in {"F16", "BF16", "F32", "F64"}
        ):
            raise ValueError("unexpected adapter tensor or target")
        pairs[match[1]][match[2]] = row["shape"]
    if {name.rsplit(".", 1)[-1] for name in pairs} != set(targets):
        raise ValueError("declared adapter target missing from checkpoint")
    for pair in pairs.values():
        if (
            set(pair) != {"A", "B"}
            or any(len(s) != 2 for s in pair.values())
            or pair["A"][0] != rank
            or pair["B"][1] != rank
        ):
            raise ValueError("tensor rank or A/B pair mismatch")
    record, _ = file_record(spec["path"])
    if {k: record[k] for k in ("bytes", "sha256")} != spec["identity"]:
        raise ValueError("adapter configuration changed")
    return record


def admit(manifest):
    if (
        set(manifest) != {"schema", "limits", "components"}
        or manifest["schema"] != "hepta.memory-budget.capacity.v2"
    ):
        raise ValueError("registered capacity manifest required")
    limits = manifest["limits"]
    if set(limits) != LIMITS or any(
        type(v) is not int or v < 0 for v in limits.values()
    ):
        raise ValueError("explicit nonnegative capacity limits required")
    roles = {name: {"components": 0, "values": 0, "tensor_bytes": 0} for name in ROLES}
    seen, storage, rows = set(), {}, []
    for component in manifest["components"]:
        if (
            set(component)
            != {"id", "role", "path", "identity", "rank", "targets", "config"}
            or component["id"] in seen
            or not component["id"]
            or component["role"] not in ROLES
        ):
            raise ValueError("distinct controller-owned component roles required")
        seen.add(component["id"])
        result = tensor_file(component["path"], component["identity"])
        storage[tuple(result["physical_key"])] = component["identity"]["bytes"]
        if component["role"] in {"active_adapter", "retained_parent"}:
            config = adapter_shape(component, result["tensors"])
            storage[tuple(config["physical_key"])] = config["bytes"]
        elif (
            component["rank"] is not None
            or component["targets"]
            or component["config"] is not None
        ):
            raise ValueError("non-adapter role must not carry adapter settings")
        totals = roles[component["role"]]
        totals["components"] += 1
        totals["values"] += result["values"]
        totals["tensor_bytes"] += result["tensor_bytes"]
        rows.append({"id": component["id"], "role": component["role"], **result})
    used = {
        "active_values": sum(
            roles[r]["values"] for r in ("active_adapter", "active_router")
        ),
        "active_tensor_bytes": sum(
            roles[r]["tensor_bytes"] for r in ("active_adapter", "active_router")
        ),
        "unique_checkpoint_bytes": sum(storage.values()),
    }
    if any(used[key] > limits[key] for key in LIMITS):
        raise ValueError("actual checkpoint tensors exceed shared capacity")
    return {
        "schema": "hepta.memory-budget.capacity-admission.v2",
        "manifest_sha256": digest(manifest),
        "accepted": True,
        "used": used,
        "roles": roles,
        "components": rows,
        "model_loaded": False,
        "training_updates": 0,
        "scope": "Pinned serialized tensors and controller-declared roles; not runtime allocations, dynamic model parameters or full deployment storage.",
    }
