"""Serialize-only adapter for QualificationEvidenceEnvelopeV1.payload.

Inspected native sources: hepta-evidence/src/{qualification,canonical}.rs,
hepta-authbus/src/signed.rs, hepta-agent-protocol/src/evidence.rs, and
hepta-agentd/src/evidence_host.rs. Native schema v1 carries a serde_json::Value.
SignedMessage claims bind canonical envelope bytes; the host enforces issuer
trust, replay, expiry and role checks. This module creates none of those objects.
Supported is an evidence-chain disposition, not a proof of a report's property.

The inner record is a JSON string so its byte digest survives native JSON
serialization without assuming Python and serde encode floats identically.
record_sha256 is NOT the native payload_sha256 or envelope_sha256. The native
signer must canonicalize the complete envelope and enforce its 48 KiB ingress
limit (the storage limit is 256 KiB). Our 32 KiB payload limit leaves headroom
but does not certify the complete envelope's size.

Native query/verify return references. Identity validation below checks supplied
payload data against a separately retained digest, not a native store read or a
signature. Production ingress, signing and recovery remain untested here.
"""

import json

from .contracts import (
    CalibrationReport,
    RiskPrediction,
    VerificationReceipt,
    canonical_json,
    digest,
    parse_record,
)


INTEGRATION_BOUNDARY = {
    "mode": "serialize_only",
    "native_payload_slot": "QualificationEvidenceEnvelopeV1.payload",
    "native_envelope_schema_version": 1,
    "native_authentication": "SignedMessage via KernelEvidenceAppendIngress",
    "native_execution_verified": False,
    "supported_is_property_proof": False,
}
_REPORT_TYPES = (RiskPrediction, CalibrationReport, VerificationReceipt)
_KEYS = {
    "schema_version",
    "payload_type",
    "record_type",
    "record_encoding",
    "record_sha256",
    "record_json",
}
_ENCODING = "verify1-python-canonical-json-v1"
_MAX_PAYLOAD_BYTES = 32 * 1024


def encode_kernel_payload(record):
    """Return only a JSON-compatible payload; the caller supplies the native envelope."""
    if type(record) not in _REPORT_TYPES:
        raise ValueError("expected an exact VERIFY-1 report type")
    raw = canonical_json(record)
    parse_record(raw)  # Revalidate before crossing the serialization boundary.
    payload = {
        "schema_version": 1,
        "payload_type": "hepta.verify1.report",
        "record_type": json.loads(raw)["type"],
        "record_encoding": _ENCODING,
        "record_sha256": digest(record),
        "record_json": raw,
    }
    if len(canonical_json(payload).encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("VERIFY-1 payload exceeds 32 KiB")
    return payload


def validate_payload_identity(payload, *, expected_record_sha256, expected_type):
    """Return the claimed report only when its complete identity matches the caller's pin."""
    if type(payload) is not dict or set(payload) != _KEYS:
        raise ValueError("missing or unknown payload fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported payload schema version")
    if (
        payload["payload_type"] != "hepta.verify1.report"
        or payload["record_encoding"] != _ENCODING
    ):
        raise ValueError("unsupported payload type or encoding")
    record = parse_record(payload["record_json"])
    if expected_type not in _REPORT_TYPES or type(record) is not expected_type:
        raise ValueError("record type mismatch")
    expected_payload = encode_kernel_payload(record)
    if payload != expected_payload:
        raise ValueError("payload encoding, tag or digest mismatch")
    if (
        type(expected_record_sha256) is not str
        or payload["record_sha256"] != expected_record_sha256
    ):
        raise ValueError("record differs from the independently retained identity")
    return record
