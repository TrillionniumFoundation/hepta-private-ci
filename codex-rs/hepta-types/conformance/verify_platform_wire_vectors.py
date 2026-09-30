#!/usr/bin/env python3
"""Independent Prompt V2 / Topology V1 strict-JSON -> HPTC oracle."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_types_strict_json import MAX_RAW_BYTES, parse_strict_json, assert_unsigned_integer_tokens

ROOT = Path(__file__).resolve().parents[3]
VECTOR_PATH = ROOT / "codex-rs/hepta-types/PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json"
DOMAIN = b"hepta.platform.types.canonical-digest.v1"
STABLE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
U64 = re.compile(r"^(0|[1-9][0-9]*)$")
U64_MAX = (1 << 64) - 1
MAX_HPTC_ITEMS = 4096

PROMPT_KEYS = {
    "kind", "compilation_id", "provider_request_digest", "delivered",
    "rejected_reason", "observed_token_positions", "truncation_observed",
    "legacy_v1_digest",
}
TOPOLOGY_KEYS = {
    "kind", "proposal_digest", "candidate_id", "candidate_digest",
    "baseline_generation", "candidate_generation", "selected_topology_digest",
    "evaluation_digest", "rollback_predecessor_digest", "changed", "deltas",
}
DELTA_KEYS = {
    "module_id", "operation", "related_module_ids", "predecessor_digest",
    "candidate_digest", "evidence_digest",
}
OPERATIONS = {"add", "replace", "retire", "rewire", "split", "merge"}


def u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def label(value: str) -> bytes:
    raw = value.encode()
    return u16(len(raw)) + raw


def strict_keys(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name}: object")
    actual = set(value)
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise ValueError(f"{name}: fields extra={extra} missing={missing}")
    return value


def stable_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.encode()) <= 128:
        raise ValueError(f"{name}: stable id")
    if not STABLE_ID.fullmatch(value):
        raise ValueError(f"{name}: stable id")
    return value


def digest(value: Any, name: str, *, nonzero: bool = False) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f"{name}: digest")
    if nonzero and value == "0" * 64:
        raise ValueError(f"{name}: zero digest")
    return value


def canonical_u64(value: Any, name: str, *, positive: bool = False) -> int:
    if not isinstance(value, str) or len(value) > 20 or not U64.fullmatch(value):
        raise ValueError(f"{name}: canonical_integer")
    result = int(value)
    if result > U64_MAX or (positive and result == 0):
        raise ValueError(f"{name}: canonical_integer")
    return result


def encode_value(kind: str, value: Any) -> bytes:
    if kind == "bool":
        return b"\x01" + bytes([1 if value else 0])
    if kind == "u64":
        return b"\x02" + int(value).to_bytes(8, "big")
    if kind == "text":
        raw = value.encode()
        return b"\x06" + u32(len(raw)) + raw
    if kind == "digest":
        return b"\x07" + bytes.fromhex(value)
    if kind == "stable_id":
        raw = value.encode()
        return b"\x08" + u16(len(raw)) + raw
    if kind == "array":
        if len(value) > MAX_HPTC_ITEMS:
            raise ValueError("HPTC: too many items")
        return b"\x09" + u32(len(value)) + b"".join(
            encode_value(item_kind, item) for item_kind, item in value
        )
    raise ValueError(f"unsupported canonical value: {kind}")


def hptc(type_id: str, schema_version: int, fields: dict[str, tuple[str, Any]]) -> str:
    type_raw = type_id.encode()
    entries = sorted(fields.items(), key=lambda item: item[0].encode())
    if len(entries) > MAX_HPTC_ITEMS:
        raise ValueError("HPTC: too many fields")
    encoded = (
        b"HPTC" + u16(1) + u16(len(DOMAIN)) + DOMAIN
        + u16(len(type_raw)) + type_raw + u32(schema_version) + u32(len(entries))
        + b"".join(label(name) + encode_value(*value) for name, value in entries)
    )
    if len(encoded) > 262144:
        raise ValueError("HPTC: too large")
    return hashlib.sha256(encoded).hexdigest()


def prompt_digest(value: Any) -> str:
    value = strict_keys(value, PROMPT_KEYS, "prompt")
    if value["kind"] != "prompt_delivery_observation_v2":
        raise ValueError("prompt: kind")
    compilation_id = stable_id(value["compilation_id"], "compilation_id")
    provider = digest(value["provider_request_digest"], "provider_request_digest", nonzero=True)
    delivered = value["delivered"]
    truncation = value["truncation_observed"]
    if not isinstance(delivered, bool) or not isinstance(truncation, bool):
        raise ValueError("prompt: bool")
    reason = value["rejected_reason"]
    if reason is not None:
        reason = stable_id(reason, "rejected_reason")
        if len(reason.encode()) > 64:
            raise ValueError("rejected_reason: bound")
    if delivered == (reason is not None):
        raise ValueError("prompt: disposition")
    positions = value["observed_token_positions"]
    if positions is not None:
        if not isinstance(positions, list) or not 1 <= len(positions) <= MAX_HPTC_ITEMS:
            raise ValueError("prompt: positions")
        if any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 0xFFFF_FFFF for item in positions):
            raise ValueError("prompt: positions")
        if any(left >= right for left, right in zip(positions, positions[1:])):
            raise ValueError("prompt: positions order")
    legacy = value["legacy_v1_digest"]
    if legacy is not None:
        legacy = digest(legacy, "legacy_v1_digest", nonzero=True)
    return hptc(
        "platform.types:prompt-delivery-observation-v2",
        2,
        {
            "compilation_id": ("stable_id", compilation_id),
            "delivered": ("bool", delivered),
            "legacy_v1_digest": ("array", [] if legacy is None else [("digest", legacy)]),
            "observed_token_positions": (
                "array", [] if positions is None else [("u64", item) for item in positions]
            ),
            "provider_request_digest": ("digest", provider),
            "rejected_reason": ("array", [] if reason is None else [("stable_id", reason)]),
            "truncation_observed": ("bool", truncation),
        },
    )


def delta_projection(value: Any) -> tuple[str, dict[str, Any]]:
    value = strict_keys(value, DELTA_KEYS, "topology delta")
    module_id = stable_id(value["module_id"], "module_id")
    operation = value["operation"]
    if operation not in OPERATIONS:
        raise ValueError("operation")
    related = value["related_module_ids"]
    if not isinstance(related, list) or len(related) > 256:
        raise ValueError("related_module_ids")
    related = [stable_id(item, "related_module_ids") for item in related]
    if related != sorted(set(related)) or module_id in related:
        raise ValueError("related_module_ids: order")
    predecessor = digest(value["predecessor_digest"], "predecessor_digest")
    candidate = digest(value["candidate_digest"], "candidate_digest")
    evidence = digest(value["evidence_digest"], "evidence_digest", nonzero=True)
    zero = "0" * 64
    if operation == "add":
        shape = not related and predecessor == zero and candidate != zero
    elif operation == "retire":
        shape = not related and predecessor != zero and candidate == zero
    elif operation in {"replace", "rewire"}:
        shape = not related and predecessor != zero and candidate != zero and predecessor != candidate
    else:
        shape = bool(related) and predecessor != zero and candidate != zero and predecessor != candidate
    if not shape:
        raise ValueError("delta shape")
    return hptc(
        "platform.types:runtime-topology-delta-v1",
        1,
        {
            "candidate_digest": ("digest", candidate),
            "evidence_digest": ("digest", evidence),
            "module_id": ("stable_id", module_id),
            "operation": ("text", operation),
            "predecessor_digest": ("digest", predecessor),
            "related_module_ids": ("array", [("stable_id", item) for item in related]),
        },
    ), {"module_id": module_id, "operation": operation, "related": related}


def topology_digest(value: Any) -> str:
    value = strict_keys(value, TOPOLOGY_KEYS, "topology")
    if value["kind"] != "runtime_topology_candidate_v1":
        raise ValueError("topology: kind")
    proposal = digest(value["proposal_digest"], "proposal_digest", nonzero=True)
    candidate_id = stable_id(value["candidate_id"], "candidate_id")
    stored_candidate = digest(value["candidate_digest"], "candidate_digest", nonzero=True)
    baseline = canonical_u64(value["baseline_generation"], "baseline_generation", positive=True)
    candidate_generation = canonical_u64(
        value["candidate_generation"], "candidate_generation", positive=True
    )
    if candidate_generation != baseline + 1:
        raise ValueError("generation successor")
    selected = digest(value["selected_topology_digest"], "selected_topology_digest", nonzero=True)
    evaluation = digest(value["evaluation_digest"], "evaluation_digest", nonzero=True)
    rollback = digest(
        value["rollback_predecessor_digest"], "rollback_predecessor_digest", nonzero=True
    )
    if rollback != selected:
        raise ValueError("rollback predecessor")
    changed = value["changed"]
    deltas = value["deltas"]
    if not isinstance(changed, bool) or not isinstance(deltas, list) or len(deltas) > 256:
        raise ValueError("candidate shape")
    if changed == (len(deltas) == 0):
        raise ValueError("candidate shape")
    projected = [delta_projection(item) for item in deltas]
    metadata = [item[1] for item in projected]
    module_ids = [item["module_id"] for item in metadata]
    if module_ids != sorted(set(module_ids)):
        raise ValueError("delta order")
    by_module = {item["module_id"]: item for item in metadata}
    for item in metadata:
        if item["operation"] == "split":
            if any(by_module.get(related, {}).get("operation") != "add" for related in item["related"]):
                raise ValueError("split participant")
        if item["operation"] == "merge":
            if any(by_module.get(related, {}).get("operation") != "retire" for related in item["related"]):
                raise ValueError("merge participant")
    computed = hptc(
        "platform.types:runtime-topology-candidate-v1",
        1,
        {
            "baseline_generation": ("u64", baseline),
            "candidate_generation": ("u64", candidate_generation),
            "candidate_id": ("stable_id", candidate_id),
            "changed": ("bool", changed),
            "deltas": ("array", [("digest", item[0]) for item in projected]),
            "evaluation_digest": ("digest", evaluation),
            "proposal_digest": ("digest", proposal),
            "rollback_predecessor_digest": ("digest", rollback),
            "selected_topology_digest": ("digest", selected),
        },
    )
    if computed != stored_candidate:
        raise ValueError("candidate digest")
    return computed


def raw_protocol_digest(raw: str, protocol: str) -> Any:
    value = parse_strict_json(raw)
    if protocol == "PromptDeliveryObservationV2":
        assert_unsigned_integer_tokens(raw)
        return prompt_digest(value)
    if protocol == "RuntimeTopologyCandidateV1":
        return topology_digest(value)
    if protocol == "parser":
        return value
    raise ValueError(f"unknown raw protocol: {protocol}")


def verify_raw_invalid(vector: dict[str, Any]) -> None:
    raw = vector["rawJson"]
    expected = vector["expectedError"]
    try:
        raw_protocol_digest(raw, vector["protocol"])
        raise AssertionError(f"raw invalid vector accepted: {vector['id']}")
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(
                f"{vector['id']}: expected {expected!r}, got {error!r}"
            ) from error


def verify_strict_json_boundaries() -> None:
    for raw in ('{"x":1,"\\u0078":2}', '{"outer":{"x":1,"x":2}}', '[{"x":1,"x":2}]'):
        try:
            parse_strict_json(raw)
        except ValueError as error:
            if str(error) != "duplicate_key":
                raise AssertionError(f"wrong duplicate rejection: {error}") from error
        else:
            raise AssertionError(f"decoded duplicate object key accepted: {raw}")
    for raw in ('[{"x":1},{"x":2}]', '{"x":{"x":1}}', '{"x":"\\\"x\\\":1"}'):
        parse_strict_json(raw)
    parse_strict_json('[-0,1.0,1e0]')
    assert_unsigned_integer_tokens('["-0","1.0","1e0",0,1]')
    parse_strict_json("0" + " " * (MAX_RAW_BYTES - 1))
    try:
        parse_strict_json("0" + " " * MAX_RAW_BYTES)
    except ValueError as error:
        if str(error) != "size_exceeded":
            raise AssertionError(f"wrong size rejection: {error}") from error
    else:
        raise AssertionError("strict JSON admitted oversized raw input")


def verify_prompt_capacity() -> None:
    """Keep the protocol and the generic HPTC encoder within the same bound."""
    for count in (1, 4095, 4096, 4097, 8192, 8193):
        value = {
            "kind": "prompt_delivery_observation_v2",
            "compilation_id": "compilation-1",
            "provider_request_digest": "11" * 32,
            "delivered": True,
            "rejected_reason": None,
            "observed_token_positions": list(range(count)),
            "truncation_observed": False,
            "legacy_v1_digest": None,
        }
        try:
            result = prompt_digest(value)
        except ValueError:
            if count <= 4096:
                raise AssertionError(f"accepted boundary rejected: {count}")
        else:
            if count > 4096:
                raise AssertionError(f"unhashable V2 boundary accepted: {count}")
            if count == 4096 and result != "c499a4a2479291376878d2f3a506d342c7f96b3eaa0fea3d206aafcbaf5a4e36":
                raise AssertionError("frozen 4096-position commitment changed")
    try:
        encode_value("array", [("u64", 0)] * 4097)
    except ValueError:
        pass
    else:
        raise AssertionError("generic HPTC array bound bypassed")


def main() -> int:
    document = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    for vector in document["validVectors"]:
        value = vector["json"]
        if vector["protocol"] == "PromptDeliveryObservationV2":
            actual = prompt_digest(value)
        elif vector["protocol"] == "RuntimeTopologyCandidateV1":
            actual = topology_digest(value)
        else:
            raise AssertionError(f"unknown protocol: {vector['protocol']}")
        if actual != vector["expectedHptcSha256"]:
            raise AssertionError(
                f"{vector['id']}: {actual} != {vector['expectedHptcSha256']}"
            )
    for vector in document["rawInvalidVectors"]:
        verify_raw_invalid(vector)
    verify_strict_json_boundaries()
    verify_prompt_capacity()
    print(
        "platform.types prompt/topology Python conformance: ok "
        f"({len(document['validVectors'])} valid, "
        f"{len(document['rawInvalidVectors'])} raw invalid, 6 capacity boundaries)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
