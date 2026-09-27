#!/usr/bin/env python3
"""Register the authenticated memory.federation wire protocol canonically."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs/contracts/CONTRACTS.json"
PROTOCOLS = ROOT / "docs/contracts/PROTOCOL_SCHEMAS.json"
TECHNICAL = ROOT / "docs/modules/memory.federation/TECHNICAL.md"
SCHEMA = ROOT / "docs/modules/memory.federation/memory-federation-wire-v1.schema.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement, found {text.count(old)}")
    return text.replace(old, new, 1)


def contract(contract_id: str, payload_class: str) -> dict:
    return {
        "id": contract_id,
        "version": 1,
        "kind": "typed_protocol",
        "producer": "memory.federation",
        "consumers": ["memory.federation"],
        "transport": "canonical_json_over_authenticated_peer_transport",
        "bounded": True,
        "authorityDelta": "none",
        "payloadClass": payload_class,
        "compatibility": "deny_unknown_critical_fields",
    }


def field(name: str, field_type: str, max_bytes: int | None = None) -> dict:
    row = {"name": name, "type": field_type, "required": True}
    if max_bytes is not None:
        row["maxBytes"] = max_bytes
    return row


def protocol(protocol_id: str, fields: list[dict], invariants: list[str]) -> dict:
    return {
        "id": protocol_id,
        "contractId": protocol_id,
        "canonicalEncoding": "canonical_json_utf8",
        "denyUnknownCriticalFields": True,
        "maximumEncodedBytes": 8192,
        "digestScope": "all_semantic_fields_except_detached_signature",
        "fields": fields,
        "invariants": invariants,
    }


def upsert(rows: list[dict], value: dict) -> None:
    rows[:] = [row for row in rows if row.get("id") != value["id"]]
    rows.append(value)
    rows.sort(key=lambda row: row["id"])


def patch_registries() -> None:
    contracts = load(CONTRACTS)
    upsert(
        contracts["contracts"],
        contract("MemoryFederationWireRequestV1", "authenticated_query_bound_request"),
    )
    upsert(
        contracts["contracts"],
        contract("MemoryFederationWireResponseV1", "authenticated_cut_bound_response"),
    )
    dump(CONTRACTS, contracts)

    common = [
        field("protocolVersion", "u32"),
        field("credentialKeyId", "id128", 128),
        field("ownerEpoch", "u64"),
        field("issuedUnixMs", "u64"),
        field("expiresUnixMs", "u64"),
        field("nonceDigest", "sha256", 64),
        field("signature", "utf8", 128),
    ]
    invariants = [
        "bounded_lengths",
        "canonical_field_order",
        "semantic_digest_stable",
        "authority_delta_none",
        "unknown_critical_fields_rejected",
        "current_peer_credential_required",
        "owner_epoch_and_source_cut_bound",
        "bounded_replay_window_required",
    ]
    protocols = load(PROTOCOLS)
    upsert(
        protocols["protocols"],
        protocol(
            "MemoryFederationWireRequestV1",
            [
                field("requestId", "id128", 128),
                field("senderPeerId", "id128", 128),
                field("receiverPeerId", "id128", 128),
                field("queryBindingDigest", "sha256", 64),
                field("scopeDigest", "sha256", 64),
                field("purposeDigest", "sha256", 64),
                field("sourceCutDigest", "sha256", 64),
                *common,
            ],
            invariants + ["request_nonce_unique_per_sender_key_epoch"],
        ),
    )
    upsert(
        protocols["protocols"],
        protocol(
            "MemoryFederationWireResponseV1",
            [
                field("responseId", "id128", 128),
                field("requestId", "id128", 128),
                field("responderPeerId", "id128", 128),
                field("receiverPeerId", "id128", 128),
                field("queryBindingDigest", "sha256", 64),
                field("responseDigest", "sha256", 64),
                field("sourceCutDigest", "sha256", 64),
                *common,
            ],
            invariants
            + [
                "response_window_within_request_window",
                "response_nonce_distinct_from_request_nonce",
            ],
        ),
    )
    dump(PROTOCOLS, protocols)


def patch_technical() -> None:
    text = TECHNICAL.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "Registered cross-host wire protocol schemas:\n\nNone.",
        "Registered cross-host wire protocol schemas:\n\n"
        "- `MemoryFederationWireRequestV1`;\n"
        "- `MemoryFederationWireResponseV1`.\n\n"
        "Their canonical field registry is `docs/contracts/PROTOCOL_SCHEMAS.json`; "
        "the module-local JSON Schema is a navigation and codec-conformance aid, not a second authority.",
        "technical wire protocol registration",
    )
    TECHNICAL.write_text(text, encoding="utf-8")


def patch_json_schema() -> None:
    schema = load(SCHEMA)
    rename = {
        "protocol_version": "protocolVersion",
        "credential_key_id": "credentialKeyId",
        "owner_epoch": "ownerEpoch",
        "issued_unix_ms": "issuedUnixMs",
        "expires_unix_ms": "expiresUnixMs",
        "nonce_digest": "nonceDigest",
        "request_id": "requestId",
        "sender_peer_id": "senderPeerId",
        "receiver_peer_id": "receiverPeerId",
        "query_binding_digest": "queryBindingDigest",
        "scope_digest": "scopeDigest",
        "purpose_digest": "purposeDigest",
        "source_cut_digest": "sourceCutDigest",
        "response_id": "responseId",
        "responder_peer_id": "responderPeerId",
        "response_digest": "responseDigest",
    }

    def walk(value):
        if isinstance(value, dict):
            if "required" in value and isinstance(value["required"], list):
                value["required"] = [rename.get(item, item) for item in value["required"]]
            if "properties" in value and isinstance(value["properties"], dict):
                value["properties"] = {
                    rename.get(key, key): child for key, child in value["properties"].items()
                }
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
    dump(SCHEMA, schema)


def patch_state_generator() -> None:
    path = ROOT / "scripts/hepta-memory-federation-state.py"
    text = path.read_text(encoding="utf-8")
    anchor = '    "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json",\n'
    additions = (
        anchor
        + '    "scripts/memory_federation_registry_closure.py",\n'
        + '    "docs/contracts/CONTRACTS.json",\n'
        + '    "docs/contracts/PROTOCOL_SCHEMAS.json",\n'
        + '    "docs/modules/MODULE_DOCS.json",\n'
        + '    "docs/modules/SOURCE_BINDINGS.json",\n'
    )
    if additions not in text:
        if text.count(anchor) != 1:
            raise SystemExit("state source registry anchor drift")
        text = text.replace(anchor, additions, 1)
    path.write_text(text, encoding="utf-8")


def refresh_projections() -> None:
    subprocess.run(
        ["python3", "scripts/hepta-module-docs.py", "refresh-derived"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["python3", "scripts/hepta-module-docs.py", "refresh-indexes"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    patch_registries()
    patch_technical()
    patch_json_schema()
    patch_state_generator()
    refresh_projections()
    print("memory.federation canonical wire registration applied")


if __name__ == "__main__":
    main()
