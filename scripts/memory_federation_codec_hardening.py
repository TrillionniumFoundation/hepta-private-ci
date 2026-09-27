#!/usr/bin/env python3
"""Harden generated memory federation canonical JSON codec bounds."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_wire() -> None:
    path = "codex-rs/hepta-memory-federation/src/wire.rs"
    text = read(path)
    text = replace_once(
        text,
        "pub const MAX_FEDERATION_WIRE_ENCODED_BYTES_V1: usize = 8192;\n",
        "pub const MAX_FEDERATION_WIRE_ENCODED_BYTES_V1: usize = 8192;\n"
        "pub const MAX_FEDERATION_WIRE_ID_BYTES_V1: usize = 128;\n",
        "wire identity bound",
    )
    text = replace_once(
        text,
        "fn validate_unsigned_request(request: &FederationWireRequestV1) -> Result<(), FederationWireError> {\n",
        "fn validate_unsigned_request(request: &FederationWireRequestV1) -> Result<(), FederationWireError> {\n"
        "    for value in [\n"
        "        &request.request_id,\n"
        "        &request.sender_peer_id,\n"
        "        &request.receiver_peer_id,\n"
        "        &request.credential_key_id,\n"
        "    ] {\n"
        "        ensure_wire_id(value)?;\n"
        "    }\n",
        "request identity validation",
    )
    text = replace_once(
        text,
        "fn validate_unsigned_response(\n    response: &FederationWireResponseV1,\n) -> Result<(), FederationWireError> {\n",
        "fn validate_unsigned_response(\n    response: &FederationWireResponseV1,\n) -> Result<(), FederationWireError> {\n"
        "    for value in [\n"
        "        &response.response_id,\n"
        "        &response.request_id,\n"
        "        &response.responder_peer_id,\n"
        "        &response.receiver_peer_id,\n"
        "        &response.credential_key_id,\n"
        "    ] {\n"
        "        ensure_wire_id(value)?;\n"
        "    }\n",
        "response identity validation",
    )
    text = replace_once(
        text,
        "fn parse_id(value: String) -> Result<StableId, FederationWireError> {\n    StableId::new(value).map_err(|_| FederationWireError::InvalidIdentity)\n}\n",
        "fn parse_id(value: String) -> Result<StableId, FederationWireError> {\n"
        "    if value.is_empty() || value.len() > MAX_FEDERATION_WIRE_ID_BYTES_V1 {\n"
        "        return Err(FederationWireError::InvalidIdentity);\n"
        "    }\n"
        "    StableId::new(value).map_err(|_| FederationWireError::InvalidIdentity)\n"
        "}\n\n"
        "fn ensure_wire_id(value: &StableId) -> Result<(), FederationWireError> {\n"
        "    let raw = value.as_str().as_bytes();\n"
        "    if raw.is_empty() || raw.len() > MAX_FEDERATION_WIRE_ID_BYTES_V1 {\n"
        "        return Err(FederationWireError::InvalidIdentity);\n"
        "    }\n"
        "    Ok(())\n"
        "}\n",
        "wire identity helper",
    )
    write(path, text)


def patch_lib() -> None:
    path = "codex-rs/hepta-memory-federation/src/lib.rs"
    text = read(path)
    text = replace_once(
        text,
        "pub use wire::MAX_FEDERATION_WIRE_ENCODED_BYTES_V1;\n",
        "pub use wire::MAX_FEDERATION_WIRE_ENCODED_BYTES_V1;\n"
        "pub use wire::MAX_FEDERATION_WIRE_ID_BYTES_V1;\n",
        "wire id bound export",
    )
    write(path, text)


def patch_state_generator() -> None:
    path = "scripts/hepta-memory-federation-state.py"
    text = read(path)
    anchor = '    "scripts/memory_federation_codec_closure.py",\n'
    addition = anchor + '    "scripts/memory_federation_codec_hardening.py",\n'
    if addition not in text:
        text = replace_once(text, anchor, addition, "codec hardening source path")

    operation_anchor = '''        {
            "operation": "encode_wire_request_v1",'''
    sign_operations = '''        {
            "operation": "sign_wire_request_v1",
            "designOperation": "sign_wire_request_v1",
            "nativeSymbol": "sign_wire_request_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "sign_wire_response_v1",
            "designOperation": "sign_wire_response_v1",
            "nativeSymbol": "sign_wire_response_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
'''
    if sign_operations not in text:
        text = replace_once(text, operation_anchor, sign_operations + operation_anchor, "wire signing operations")
    write(path, text)


def main() -> None:
    patch_wire()
    patch_lib()
    patch_state_generator()
    print("memory.federation wire codec identity bounds applied")


if __name__ == "__main__":
    main()
