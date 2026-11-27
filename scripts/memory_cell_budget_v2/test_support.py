"""Synthetic format/receipt fixtures; no tensor runtime or model execution."""

import json
from pathlib import Path
import struct

from common import METERS, file_identity, save
from scripts.memory_cell_budget.budget_ledger import GAUGES


def budget(total=100):
    return {
        "limits": dict.fromkeys(METERS, total),
        "gauges": dict.fromkeys(GAUGES, 10**9),
        "prices": dict.fromkeys(METERS, 1),
        "cost_limit": total * len(METERS),
    }


def capacity(components=(), ceiling=460800):
    return {
        "schema": "hepta.memory-budget.capacity.v2",
        "limits": {
            "active_values": ceiling,
            "active_tensor_bytes": ceiling * 4,
            "unique_checkpoint_bytes": 64 * 1024**2,
        },
        "components": list(components),
    }


def process(root, name, cpu=10, wall=10, returncode=0, timeout=False):
    root = Path(root) / name
    root.mkdir()
    (root / "stdout").write_bytes(b"synthetic process evidence\n")
    (root / "stderr").write_bytes(b"")
    report = {
        "attempt_label": name,
        "returncode": returncode,
        "timeout": timeout,
        "error": None,
        "wall_seconds": wall / 10**9,
        "usage": {"user_cpu_seconds": cpu / 10**9, "system_cpu_seconds": 0},
        "stdout": file_identity(root / "stdout"),
        "stderr": file_identity(root / "stderr"),
    }
    save(root / "process.json", report)
    return {
        "kind": "wait4-v2",
        "path": str(root / "process.json"),
        "identity": file_identity(root / "process.json"),
        "id": name,
        "related": [],
    }


def plan(*rows, wall_owner=None):
    return {"rows": list(rows), "wall_owner": wall_owner or rows[0]["id"]}


def tensors(path, shapes):
    header, payload = {}, bytearray()
    for name, (dtype, shape, width) in shapes.items():
        count = 1
        for value in shape:
            count *= value
        start = len(payload)
        payload.extend(b"\0" * (count * width))
        header[name] = {
            "dtype": dtype,
            "shape": shape,
            "data_offsets": [start, len(payload)],
        }
    raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    raw += b" " * (-len(raw) % 8)
    Path(path).write_bytes(struct.pack("<Q", len(raw)) + raw + payload)


def adapter(root, name, rank):
    root = Path(root) / name
    root.mkdir()
    shapes = {}
    for layer in range(30):
        for target, width in (("q_proj", 576), ("v_proj", 192)):
            prefix = f"base_model.model.model.layers.{layer}.self_attn.{target}"
            shapes[prefix + ".lora_A.weight"] = ("F32", [rank, 576], 4)
            shapes[prefix + ".lora_B.weight"] = ("F32", [width, rank], 4)
    checkpoint = root / "adapter_model.safetensors"
    tensors(checkpoint, shapes)
    config = root / "adapter_config.json"
    save(
        config, {"peft_type": "LORA", "r": rank, "target_modules": ["q_proj", "v_proj"]}
    )
    return {
        "id": name,
        "role": "active_adapter",
        "path": str(checkpoint),
        "identity": file_identity(checkpoint),
        "rank": rank,
        "targets": ["q_proj", "v_proj"],
        "config": {"path": str(config), "identity": file_identity(config)},
    }
