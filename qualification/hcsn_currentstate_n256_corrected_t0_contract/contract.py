"""Fail-closed contract for a future corrected-lineage authentic N256 t=0 capsule.

This module validates metadata only.  It does not read authentic inputs, import
the candidate, call the serializer, or perform numerical work.
"""

import hashlib
import json


SCHEMA = "hcsn-n256-corrected-t0-capsule-contract-v1"
IDENTITY = "hcsn-n256-corrected-t0-capsule-contract-20261117-c06d-001"
BASE_COMMIT = "d40c166e4d8a1f051473afe9ef78981b2a7c3183"

INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
STATE_ORIGINAL_SHA256 = "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c"
PHASE_ORIGINAL_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"
NPZ_B64_ORIGINAL_SHA256 = "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb"
DECODED_NPZ_SHA256 = "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8"

CORRECTED_CANDIDATE_SHA256 = "49616d4fcff9685a6cfcbee00ff45a2fd9ab4eb9c6ce04e62c02f927752d50db"
CORRECTED_CANDIDATE_ADMISSION_SHA256 = "d3ec236043f1563a6c05d0843a1b431ec1288da70047a3dc451031c25f67f61b"
CORRECTED_CANDIDATE_REQUEST_SHA256 = "9db32bf0c81051a8ba719a0fd54ece202e312ae84ab5ede43d181e3d86f410fe"
CORRECTED_ORACLE_ADAPTER_SHA256 = "311eeeb69ba5002171d3aa765610bc9caea1cb2942309ba6e67543297cb74084"
CORRECTED_ORACLE_ADMISSION_SHA256 = "7f3c24118a3504d393d59b31576e8a140c206a154dfaecf4c5ec0aa327feb90c"
CORRECTED_ORACLE_REQUEST_SHA256 = "b99b8621b4ea6c4083815d736d07de96ef056251104224044d780c2135f7cdcc"
CANONICAL_SERIALIZER_SHA256 = "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a"

HISTORICAL_CAPSULE_SHA256 = "1ebdf4750ccbb56b4ef00d6764b1af266359d648e5449db371ffe631bb32c67d"
HISTORICAL_CANDIDATE_SHA256 = "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9"
HISTORICAL_ORACLE_SHA256 = "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73"

STATE_COORDINATES = 2_600
PACKET_COORDINATES = 56
COORDINATE_DENOMINATOR = 2_656
PACKETS = 8
MAX_CAPSULE_BYTES = 8 * 1024 * 1024
RLIMIT_AS_BYTES = 256 * 1024 * 1024

BLOCKS = {
    "active": [5, 2, 255],
    "discounted_hit": [5, 2],
    "lower_hit": [5, 2],
    "occupation": [5, 3],
    "upper": [5, 3],
}


class ContractError(ValueError):
    """Raised when a record tries to cross the source-only boundary."""


def _sha256(value, name):
    if not isinstance(value, str) or len(value) != 64:
        raise ContractError(f"{name} must be lowercase SHA-256")
    if any(character not in "0123456789abcdef" for character in value):
        raise ContractError(f"{name} must be lowercase SHA-256")


def expected_bindings():
    return {
        "candidate_admission_sha256": CORRECTED_CANDIDATE_ADMISSION_SHA256,
        "candidate_request_sha256": CORRECTED_CANDIDATE_REQUEST_SHA256,
        "candidate_source_sha256": CORRECTED_CANDIDATE_SHA256,
        "canonical_serializer_sha256": CANONICAL_SERIALIZER_SHA256,
        "decoded_npz_sha256": DECODED_NPZ_SHA256,
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "npz_b64_original_sha256": NPZ_B64_ORIGINAL_SHA256,
        "oracle_adapter_sha256": CORRECTED_ORACLE_ADAPTER_SHA256,
        "oracle_admission_sha256": CORRECTED_ORACLE_ADMISSION_SHA256,
        "oracle_request_sha256": CORRECTED_ORACLE_REQUEST_SHA256,
        "phase_original_sha256": PHASE_ORIGINAL_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "state_original_sha256": STATE_ORIGINAL_SHA256,
    }


def expected_future_counts():
    return {
        "candidate_phase_parser_calls": 8,
        "canonical_decode_calls": 1,
        "canonical_encode_invocations": 2,
        "dynamic_runs": 0,
        "independent_parser_calls": 1,
        "matrix_exponential_actions": 0,
        "optimizer_steps": 0,
        "oracle_adapter_calls": 1,
        "provider_calls": 0,
        "publish_atomic_calls": 1,
        "torch_calls": 0,
    }


def validate_source_request(request):
    expected = {
        "schema": SCHEMA,
        "identity": IDENTITY,
        "base_commit": BASE_COMMIT,
        "parent_draft": 6387,
        "bindings": expected_bindings(),
        "future_execution_allowed": False,
        "execution_key": None,
        "admission_sha256": None,
        "future_capsule_sha256": None,
        "future_receipt_sha256": None,
        "coordinate_denominator": COORDINATE_DENOMINATOR,
        "future_execution_budget": {
            **expected_future_counts(),
            "capsule_max_bytes": MAX_CAPSULE_BYTES,
            "cpu_soft_seconds": 5,
            "cpu_hard_seconds": 6,
            "rlimit_as_bytes": RLIMIT_AS_BYTES,
            "wall_hard_seconds": 15,
        },
        "historical_capsule_sha256": HISTORICAL_CAPSULE_SHA256,
        "historical_capsule_transfer_allowed": False,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }
    if request != expected:
        raise ContractError("source request differs from the exact HOLD contract")
    return request


def validate_future_capsule_record(record):
    """Validate a future receipt without performing or authorizing its work."""

    if record.get("schema") != "hcsn-n256-corrected-t0-capsule-receipt-v1":
        raise ContractError("future receipt schema")
    if record.get("identity") != IDENTITY:
        raise ContractError("future receipt identity")
    if record.get("bindings") != expected_bindings():
        raise ContractError("corrected-lineage binding mismatch")
    if record.get("time") != "0" or record.get("lane") != "warm" or record.get("lane_order") != 0:
        raise ContractError("only the warm t=0 capsule is in scope")
    if record.get("semantics") != {
        "channels": 5,
        "interior_nodes": 255,
        "phase_packets": 8,
        "phase_schema": ["end", "identity", "mass", "signed_content", "start"],
        "reset": "0.3131468965881033",
        "upper": "permanently_active_nonreturning",
    }:
        raise ContractError("N256 semantics mismatch")
    blocks = record.get("blocks")
    if blocks != BLOCKS or list(blocks) != list(BLOCKS):
        raise ContractError("canonical full-state block roster mismatch")
    if record.get("coordinate_counts") != {
        "compared": COORDINATE_DENOMINATOR,
        "equal": COORDINATE_DENOMINATOR,
        "mismatches": 0,
        "packet": PACKET_COORDINATES,
        "state": STATE_COORDINATES,
        "total": COORDINATE_DENOMINATOR,
    }:
        raise ContractError("full coordinate denominator mismatch")
    packet_ids = record.get("packet_ids")
    if not isinstance(packet_ids, list) or len(packet_ids) != PACKETS:
        raise ContractError("packet identity denominator")
    if packet_ids != sorted(packet_ids) or len(set(packet_ids)) != PACKETS:
        raise ContractError("packet identities must be unique canonical order")
    for index, packet_id in enumerate(packet_ids):
        _sha256(packet_id, f"packet_ids[{index}]")
    if record.get("counts") != expected_future_counts():
        raise ContractError("future execution cost mismatch")
    if record.get("canonical_decode_roundtrip_exact") is not True:
        raise ContractError("canonical decode roundtrip is not exact")
    if record.get("independent_comparison_exact") is not True:
        raise ContractError("independent comparison is not exact")
    size = record.get("capsule_bytes")
    if type(size) is not int or not 0 < size <= MAX_CAPSULE_BYTES:
        raise ContractError("capsule byte allocation")
    _sha256(record.get("capsule_sha256"), "capsule_sha256")
    if record.get("historical_negative_and_unknown_preserved") is not True:
        raise ContractError("historical RED/UNKNOWN erased")
    for flag in ("cold_load_qualified", "largegrid_qualification", "production_adoption", "all_closed"):
        if record.get(flag) is not False:
            raise ContractError(f"future receipt grants {flag}")
    return record


def record_sha256(record):
    """Return a deterministic digest for synthetic contract controls only."""

    validate_future_capsule_record(record)
    payload = json.dumps(record, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()
