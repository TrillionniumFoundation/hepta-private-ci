#!/usr/bin/env python3
"""Add the canonical JSON codec for registered memory federation wire V1."""

from __future__ import annotations

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


def patch_cargo() -> None:
    path = "codex-rs/hepta-memory-federation/Cargo.toml"
    text = read(path)
    text = replace_once(
        text,
        'ed25519-dalek = { workspace = true }',
        'ed25519-dalek = { workspace = true }\nserde = { workspace = true, features = ["derive"] }\nserde_json = { workspace = true }',
        "wire codec dependencies",
    )
    write(path, text)


def patch_wire() -> None:
    path = "codex-rs/hepta-memory-federation/src/wire.rs"
    text = read(path)
    text = replace_once(
        text,
        "use std::fmt;\n",
        "use std::fmt;\nuse std::str::FromStr;\n",
        "wire FromStr import",
    )
    text = replace_once(
        text,
        "use ed25519_dalek::VerifyingKey;\n",
        "use ed25519_dalek::VerifyingKey;\nuse serde::Deserialize;\nuse serde::Serialize;\n",
        "wire serde imports",
    )
    text = replace_once(
        text,
        "pub const MAX_FEDERATION_REPLAY_NONCES_V1: usize = 4096;\n",
        "pub const MAX_FEDERATION_REPLAY_NONCES_V1: usize = 4096;\n"
        "pub const MAX_FEDERATION_WIRE_ENCODED_BYTES_V1: usize = 8192;\n",
        "wire encoded bound",
    )

    marker = "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct FederationWireRequestV1 {"
    dto = r'''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FederationWireRequestDtoV1 {
    protocol_version: u16,
    request_id: String,
    sender_peer_id: String,
    receiver_peer_id: String,
    credential_key_id: String,
    query_binding_digest: String,
    scope_digest: String,
    purpose_digest: String,
    source_cut_digest: String,
    owner_epoch: u64,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    nonce_digest: String,
    signature: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FederationWireResponseDtoV1 {
    protocol_version: u16,
    response_id: String,
    request_id: String,
    responder_peer_id: String,
    receiver_peer_id: String,
    credential_key_id: String,
    query_binding_digest: String,
    response_digest: String,
    source_cut_digest: String,
    owner_epoch: u64,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    nonce_digest: String,
    signature: String,
}

'''
    text = replace_once(text, marker, dto + marker, "wire DTOs")

    function_marker = "pub fn sign_wire_request_v1(\n"
    codecs = r'''pub fn encode_wire_request_v1(
    request: &FederationWireRequestV1,
) -> Result<Vec<u8>, FederationWireError> {
    validate_unsigned_request(request)?;
    encode_canonical_json(&FederationWireRequestDtoV1 {
        protocol_version: request.protocol_version,
        request_id: request.request_id.as_str().to_string(),
        sender_peer_id: request.sender_peer_id.as_str().to_string(),
        receiver_peer_id: request.receiver_peer_id.as_str().to_string(),
        credential_key_id: request.credential_key_id.as_str().to_string(),
        query_binding_digest: request.query_binding_digest.to_string(),
        scope_digest: request.scope_digest.to_string(),
        purpose_digest: request.purpose_digest.to_string(),
        source_cut_digest: request.source_cut_digest.to_string(),
        owner_epoch: request.owner_epoch,
        issued_unix_ms: request.issued_unix_ms,
        expires_unix_ms: request.expires_unix_ms,
        nonce_digest: request.nonce_digest.to_string(),
        signature: encode_hex(&request.signature),
    })
}

pub fn decode_wire_request_v1(
    encoded: &[u8],
) -> Result<FederationWireRequestV1, FederationWireError> {
    let dto: FederationWireRequestDtoV1 = decode_canonical_json(encoded)?;
    let request = FederationWireRequestV1 {
        protocol_version: dto.protocol_version,
        request_id: parse_id(dto.request_id)?,
        sender_peer_id: parse_id(dto.sender_peer_id)?,
        receiver_peer_id: parse_id(dto.receiver_peer_id)?,
        credential_key_id: parse_id(dto.credential_key_id)?,
        query_binding_digest: parse_digest(&dto.query_binding_digest)?,
        scope_digest: parse_digest(&dto.scope_digest)?,
        purpose_digest: parse_digest(&dto.purpose_digest)?,
        source_cut_digest: parse_digest(&dto.source_cut_digest)?,
        owner_epoch: dto.owner_epoch,
        issued_unix_ms: dto.issued_unix_ms,
        expires_unix_ms: dto.expires_unix_ms,
        nonce_digest: parse_digest(&dto.nonce_digest)?,
        signature: decode_signature(&dto.signature)?,
    };
    validate_unsigned_request(&request)?;
    Ok(request)
}

pub fn encode_wire_response_v1(
    response: &FederationWireResponseV1,
) -> Result<Vec<u8>, FederationWireError> {
    validate_unsigned_response(response)?;
    encode_canonical_json(&FederationWireResponseDtoV1 {
        protocol_version: response.protocol_version,
        response_id: response.response_id.as_str().to_string(),
        request_id: response.request_id.as_str().to_string(),
        responder_peer_id: response.responder_peer_id.as_str().to_string(),
        receiver_peer_id: response.receiver_peer_id.as_str().to_string(),
        credential_key_id: response.credential_key_id.as_str().to_string(),
        query_binding_digest: response.query_binding_digest.to_string(),
        response_digest: response.response_digest.to_string(),
        source_cut_digest: response.source_cut_digest.to_string(),
        owner_epoch: response.owner_epoch,
        issued_unix_ms: response.issued_unix_ms,
        expires_unix_ms: response.expires_unix_ms,
        nonce_digest: response.nonce_digest.to_string(),
        signature: encode_hex(&response.signature),
    })
}

pub fn decode_wire_response_v1(
    encoded: &[u8],
) -> Result<FederationWireResponseV1, FederationWireError> {
    let dto: FederationWireResponseDtoV1 = decode_canonical_json(encoded)?;
    let response = FederationWireResponseV1 {
        protocol_version: dto.protocol_version,
        response_id: parse_id(dto.response_id)?,
        request_id: parse_id(dto.request_id)?,
        responder_peer_id: parse_id(dto.responder_peer_id)?,
        receiver_peer_id: parse_id(dto.receiver_peer_id)?,
        credential_key_id: parse_id(dto.credential_key_id)?,
        query_binding_digest: parse_digest(&dto.query_binding_digest)?,
        response_digest: parse_digest(&dto.response_digest)?,
        source_cut_digest: parse_digest(&dto.source_cut_digest)?,
        owner_epoch: dto.owner_epoch,
        issued_unix_ms: dto.issued_unix_ms,
        expires_unix_ms: dto.expires_unix_ms,
        nonce_digest: parse_digest(&dto.nonce_digest)?,
        signature: decode_signature(&dto.signature)?,
    };
    validate_unsigned_response(&response)?;
    Ok(response)
}

fn encode_canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, FederationWireError> {
    let encoded = serde_json::to_vec(value).map_err(|_| FederationWireError::Json)?;
    if encoded.len() > MAX_FEDERATION_WIRE_ENCODED_BYTES_V1 {
        return Err(FederationWireError::EncodedEnvelopeTooLarge);
    }
    Ok(encoded)
}

fn decode_canonical_json<T>(encoded: &[u8]) -> Result<T, FederationWireError>
where
    T: for<'de> Deserialize<'de> + Serialize,
{
    if encoded.len() > MAX_FEDERATION_WIRE_ENCODED_BYTES_V1 {
        return Err(FederationWireError::EncodedEnvelopeTooLarge);
    }
    let value: T = serde_json::from_slice(encoded)
        .map_err(|_| FederationWireError::InvalidCanonicalEncoding)?;
    let canonical = serde_json::to_vec(&value).map_err(|_| FederationWireError::Json)?;
    if canonical != encoded {
        return Err(FederationWireError::InvalidCanonicalEncoding);
    }
    Ok(value)
}

fn parse_id(value: String) -> Result<StableId, FederationWireError> {
    StableId::new(value).map_err(|_| FederationWireError::InvalidIdentity)
}

fn parse_digest(value: &str) -> Result<Digest32, FederationWireError> {
    Digest32::from_str(value).map_err(|_| FederationWireError::InvalidDigest)
}

fn encode_hex(value: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(value.len() * 2);
    for byte in value {
        encoded.push(char::from(HEX[usize::from(byte >> 4)]));
        encoded.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    encoded
}

fn decode_signature(value: &str) -> Result<[u8; 64], FederationWireError> {
    if value.len() != 128 || !value.as_bytes().iter().all(u8::is_ascii_hexdigit) {
        return Err(FederationWireError::InvalidSignatureEncoding);
    }
    let mut decoded = [0_u8; 64];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        decoded[index] = (decode_nibble(pair[0])? << 4) | decode_nibble(pair[1])?;
    }
    Ok(decoded)
}

fn decode_nibble(value: u8) -> Result<u8, FederationWireError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(FederationWireError::InvalidSignatureEncoding),
    }
}

'''
    text = replace_once(text, function_marker, codecs + function_marker, "wire codecs")
    text = replace_once(
        text,
        "    InvalidVersionRange,\n",
        "    Json,\n    InvalidCanonicalEncoding,\n    EncodedEnvelopeTooLarge,\n"
        "    InvalidIdentity,\n    InvalidDigest,\n    InvalidSignatureEncoding,\n"
        "    InvalidVersionRange,\n",
        "wire codec errors",
    )

    test_marker = "    #[test]\n    fn version_negotiation_is_explicit_and_fail_closed() {"
    tests = r'''    #[test]
    fn canonical_json_codec_round_trips_and_rejects_noncanonical_bytes() {
        let key = SigningKey::from_bytes(&[7; 32]);
        let request = request(&key);
        let encoded = encode_wire_request_v1(&request).expect("encode request");
        assert_eq!(
            decode_wire_request_v1(&encoded).expect("decode request"),
            request
        );

        let mut trailing = encoded.clone();
        trailing.push(b' ');
        assert_eq!(
            decode_wire_request_v1(&trailing),
            Err(FederationWireError::InvalidCanonicalEncoding)
        );

        let text = String::from_utf8(encoded).expect("utf8 request");
        let unknown = text.replacen(
            "\"signature\":",
            "\"unknownCritical\":true,\"signature\":",
            1,
        );
        assert_eq!(
            decode_wire_request_v1(unknown.as_bytes()),
            Err(FederationWireError::InvalidCanonicalEncoding)
        );
    }

'''
    text = replace_once(text, test_marker, tests + test_marker, "wire codec tests")
    write(path, text)


def patch_lib() -> None:
    path = "codex-rs/hepta-memory-federation/src/lib.rs"
    text = read(path)
    text = replace_once(
        text,
        "pub use wire::MAX_FEDERATION_REPLAY_NONCES_V1;\n",
        "pub use wire::MAX_FEDERATION_REPLAY_NONCES_V1;\n"
        "pub use wire::MAX_FEDERATION_WIRE_ENCODED_BYTES_V1;\n"
        "pub use wire::decode_wire_request_v1;\n"
        "pub use wire::decode_wire_response_v1;\n"
        "pub use wire::encode_wire_request_v1;\n"
        "pub use wire::encode_wire_response_v1;\n",
        "wire codec exports",
    )
    write(path, text)


def patch_state_generator() -> None:
    path = "scripts/hepta-memory-federation-state.py"
    text = read(path)
    anchor = '    "scripts/memory_federation_registry_closure.py",\n'
    addition = anchor + '    "scripts/memory_federation_codec_closure.py",\n'
    if addition not in text:
        text = replace_once(text, anchor, addition, "codec source path")

    operation_anchor = '''        {
            "operation": "negotiate_wire_protocol_v1",'''
    codec_operations = '''        {
            "operation": "encode_wire_request_v1",
            "designOperation": "encode_wire_request_v1",
            "nativeSymbol": "encode_wire_request_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "decode_wire_request_v1",
            "designOperation": "decode_wire_request_v1",
            "nativeSymbol": "decode_wire_request_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "encode_wire_response_v1",
            "designOperation": "encode_wire_response_v1",
            "nativeSymbol": "encode_wire_response_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "decode_wire_response_v1",
            "designOperation": "decode_wire_response_v1",
            "nativeSymbol": "decode_wire_response_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
'''
    if codec_operations not in text:
        text = replace_once(text, operation_anchor, codec_operations + operation_anchor, "codec operations")
    write(path, text)


def patch_docs() -> None:
    path = "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md"
    text = read(path)
    text += r'''

## Canonical transport encoding

`encode_wire_request_v1` / `decode_wire_request_v1` and the corresponding
response functions implement the registered `canonical_json_utf8` surface.
Field names are camelCase, unknown fields are denied, signatures are lowercase
hex, payloads are capped at 8192 bytes, and decoding requires byte-for-byte
identity with deterministic re-encoding. The signed semantic bytes remain
independent of JSON parser behavior.
'''
    write(path, text)


def main() -> None:
    patch_cargo()
    patch_wire()
    patch_lib()
    patch_state_generator()
    patch_docs()
    print("memory.federation canonical JSON wire codec applied")


if __name__ == "__main__":
    main()
