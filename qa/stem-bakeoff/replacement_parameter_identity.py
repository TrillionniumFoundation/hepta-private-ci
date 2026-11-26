"""Bounded local loaded-parameter consistency, never publisher attestation.

CPU float32 contiguous parameters only: no device transfer, cast or clone.
Aliases of the same Parameter object are named but their bytes are read once.
Distinct objects sharing storage are charged separately. Caller must exclude
concurrent mutation; two snapshots do not detect change-and-restore in between.
"""

import hashlib
import json

MAX_PARAMETER_BYTES = 1536 * 1024 * 1024
MAX_PARAMETER_NAMES = 4096
CHUNK_BYTES = 1024 * 1024
METHOD = "cpu-f32-named-parameter-sha256-v1"
SCOPE = "local_before_after_consistency_not_execution_or_publisher_attestation"


def parameter_identity(module):
    """Validate the complete bounded layout before reading any parameter bytes."""
    import torch

    groups, names, total = {}, set(), 0
    for name, parameter in module.named_parameters(remove_duplicate=False):
        if (not isinstance(name, str) or not name or len(name.encode()) > 1024
                or name in names or len(names) >= MAX_PARAMETER_NAMES):
            raise ValueError("bounded unique parameter names required")
        names.add(name)
        if (parameter.device.type != "cpu" or parameter.dtype != torch.float32
                or parameter.layout != torch.strided or not parameter.is_contiguous()
                or parameter.ndim > 8 or parameter.numel() == 0):
            raise ValueError("nonempty contiguous CPU float32 parameters required")
        identity = id(parameter)
        if identity not in groups:
            total += parameter.numel() * parameter.element_size()
            if total > MAX_PARAMETER_BYTES:
                raise ValueError("loaded parameter byte cap exceeded")
            groups[identity] = (parameter, [])
        groups[identity][1].append(name)
    if not names:
        raise ValueError("nonempty parameter census required")
    ordered = sorted(groups.values(), key=lambda item: min(item[1]))
    digest = hashlib.sha256(METHOD.encode() + b"\0")
    for parameter, aliases in ordered:
        metadata = json.dumps([sorted(aliases), list(parameter.shape), "torch.float32"],
                              separators=(",", ":"), ensure_ascii=True).encode()
        digest.update(len(metadata).to_bytes(8, "big"))
        digest.update(metadata)
        # detach/reshape/view/numpy share CPU storage; never call contiguous/cpu.
        raw = memoryview(parameter.detach().reshape(-1).view(torch.uint8).numpy())
        digest.update(len(raw).to_bytes(8, "big"))
        for offset in range(0, len(raw), CHUNK_BYTES):
            digest.update(raw[offset:offset + CHUNK_BYTES])
    return {"sha256": digest.hexdigest(), "parameter_bytes": total,
            "parameter_objects": len(groups), "parameter_names": len(names)}


def validate_identity_receipt(value):
    """Validate self-report only; bytes_hashed counts payload, excluding metadata."""
    keys = {"method", "scope", "before", "after", "bytes_hashed",
            "hash_cpu_ns", "hash_wall_ns", "chunk_bytes", "byte_cap"}
    if not isinstance(value, dict) or set(value) != keys:
        return False
    before, after = value["before"], value["after"]
    for snapshot in (before, after):
        if (not isinstance(snapshot, dict)
                or set(snapshot) != {"sha256", "parameter_bytes", "parameter_objects", "parameter_names"}):
            return False
        sha = snapshot["sha256"]
        if (not isinstance(sha, str) or len(sha) != 64 or set(sha) - set("0123456789abcdef")
                or any(type(snapshot[k]) is not int for k in
                       ("parameter_bytes", "parameter_objects", "parameter_names"))):
            return False
    if before != after:
        return False
    return (value["method"] == METHOD and value["scope"] == SCOPE
            and 0 < before["parameter_bytes"] <= MAX_PARAMETER_BYTES
            and before["parameter_bytes"] % 4 == 0
            and before["parameter_bytes"] >= 4 * before["parameter_objects"]
            and 0 < before["parameter_objects"] <= before["parameter_names"] <= MAX_PARAMETER_NAMES
            and all(type(value[k]) is int for k in
                    ("bytes_hashed", "hash_cpu_ns", "hash_wall_ns", "chunk_bytes", "byte_cap"))
            and value["bytes_hashed"] == 2 * before["parameter_bytes"]
            and value["hash_cpu_ns"] >= 0 and value["hash_wall_ns"] >= 0
            and value["chunk_bytes"] == CHUNK_BYTES and value["byte_cap"] == MAX_PARAMETER_BYTES)
