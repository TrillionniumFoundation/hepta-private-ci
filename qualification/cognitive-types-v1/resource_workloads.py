"""Byte-boundary inputs for the existing production codec, not new contracts.

The Rust decoder, not this fixture builder, decides structural validity. Keep
field/count/path ceilings aligned with hnmf.rs; never pad unknown JSON fields.
"""
from __future__ import annotations

import copy
import hashlib
import json

EVENT_PAYLOAD_LIMIT = 262_144
EVENT_ENVELOPE_LIMIT = EVENT_PAYLOAD_LIMIT + 1_024
PATH_LIMIT = 4_096
ID_LIMIT = 128


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def byte_boundary_event(maximum_count_event, payload_bytes):
    """Fill only registered path fields to an exact payload-byte size."""
    if type(payload_bytes) is not int or not 1 <= payload_bytes <= EVENT_PAYLOAD_LIMIT + 1:
        raise ValueError("unsupported event payload boundary")
    event = copy.deepcopy(maximum_count_event)
    if event.get("contract") != "MemoryEventV1":
        raise ValueError("byte-boundary workload requires MemoryEventV1")
    payload = event["payload"]
    spans, bindings = payload["modalitySpans"], payload["crossModalBindings"]
    if len(spans) != 32 or len(bindings) != 32:
        raise ValueError("byte-boundary workload requires the reviewed maximum-count fixture")
    for index, span in enumerate(spans):
        span["spanId"] = f"span:bytes:{index:02}:".ljust(ID_LIMIT, "x")
        structured = index % 2 == 0
        span["modality"] = "structured_data" if structured else "code_ast"
        span["range"] = ({"kind": "json_pointer", "pointer": "/"} if structured
                         else {"kind": "ast_path", "path": "/"})
    for index, binding in enumerate(bindings):
        binding["bindingId"] = f"binding:bytes:{index:02}:".ljust(ID_LIMIT, "x")
        binding["spanRefs"] = [span["spanId"] for span in spans[:16]]
    for index, source in enumerate(payload["provenance"]):
        source["sourceId"] = f"source:bytes:{index:02}:".ljust(ID_LIMIT, "x")
    for field in ("causalParents", "temporalNeighbors"):
        payload[field] = [f"event:{field}:{index:02}:".ljust(ID_LIMIT, "x")
                          for index in range(len(payload[field]))]
    remaining = payload_bytes - len(canonical(payload))
    if remaining < 0:
        raise ValueError("target smaller than the unpadded registered payload")
    for span in spans:
        field = "pointer" if span["modality"] == "structured_data" else "path"
        added = min(remaining, PATH_LIMIT - 1)
        span["range"][field] += "x" * added
        remaining -= added
    if remaining or len(canonical(payload)) != payload_bytes:
        raise ValueError("registered field ceilings cannot reach the requested byte boundary")
    return event


def boundary_cases(maximum_count_event):
    """Return positive and hostile cases with explicit expected refusal classes."""
    cases = []
    for size in (EVENT_PAYLOAD_LIMIT - 1, EVENT_PAYLOAD_LIMIT):
        envelope = byte_boundary_event(maximum_count_event, size)
        cases.append((f"payload-{size}", canonical(envelope), envelope, None))
    too_large = byte_boundary_event(maximum_count_event, EVENT_PAYLOAD_LIMIT + 1)
    cases.append(("payload-over-limit", canonical(too_large), None, "limit_exceeded"))
    valid = byte_boundary_event(maximum_count_event, EVENT_PAYLOAD_LIMIT)
    wire = canonical(valid)
    cases.append(("noncanonical-at-envelope-limit",
                  b" " * (EVENT_ENVELOPE_LIMIT - len(wire)) + wire,
                  None, "non_canonical_encoding"))
    cases.append(("envelope-over-limit",
                  b" " * (EVENT_ENVELOPE_LIMIT + 1 - len(wire)) + wire,
                  None, "limit_exceeded"))
    cases.append(("malformed-near-limit", wire[:-1] + b"]", None, "invalid_value"))
    conflict = copy.deepcopy(valid)
    provenance = conflict["payload"]["provenance"]
    provenance[-1]["sourceId"] = provenance[-2]["sourceId"]
    cases.append(("logical-conflict-near-limit", canonical(conflict), None, "duplicate_identity"))
    return cases


def workload_identity(name, wire):
    return {"case": name, "input_bytes": len(wire),
            "input_sha256": hashlib.sha256(wire).hexdigest()}
