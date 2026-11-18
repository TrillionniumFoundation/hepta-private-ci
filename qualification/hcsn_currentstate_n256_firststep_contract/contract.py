"""Fail-closed metadata contract for a future corrected N256 first step.

This source performs no numerical work and authorizes no execution.
"""

import json


SCHEMA = "hcsn-n256-corrected-firststep-contract-v1"
IDENTITY = "hcsn-n256-corrected-firststep-fullstate-contract-20261117-c06d-001"
BASE_COMMIT = "f75582aad2fb226b5c27b2427f5cf50cc336bed1"
TARGET_CAPSULE_IDENTITY = "af3119de18a4f2f9049fd4f33c2331448237cb1c90810f6cdf2f2bedaa5bf7c1"
STATE_COORDINATES = 2_600
PACKET_COORDINATES = 67_128
COORDINATE_DENOMINATOR = 69_728
PACKETS = 9
PACKET_ALPHA_COORDINATES = 1_320
PACKET_GENERATOR_COORDINATES = 65_544
PACKET_OUTPUT_COORDINATES = 264


class ContractError(ValueError):
    """Raised when a record crosses the source-only boundary."""


def expected_target():
    return {
        "lane": "warm",
        "lane_order": 1,
        "time_fraction": [1, 1000],
        "capsule_identity": TARGET_CAPSULE_IDENTITY,
        "packets": PACKETS,
        "state_coordinates": STATE_COORDINATES,
        "packet_coordinates": PACKET_COORDINATES,
        "coordinate_denominator": COORDINATE_DENOMINATOR,
    }


def expected_envelope():
    return {
        "candidate_dynamic_steps_max": 1,
        "candidate_sparse_exponential_actions_max": 2,
        "oracle_dynamic_steps_max": 1,
        "oracle_dense_exponentials_max": 2,
        "canonical_decode_calls_max": 2,
        "canonical_encode_calls_max": 2,
        "coordinate_comparisons_exact": COORDINATE_DENOMINATOR,
        "capsule_max_bytes": 8 * 1024 * 1024,
        "torch_calls": 0,
        "optimizer_steps": 0,
    }


def expected_serializer_requirements():
    return {
        "state_coordinates": STATE_COORDINATES,
        "packet_alpha_coordinates": PACKET_ALPHA_COORDINATES,
        "packet_generator_coordinates": PACKET_GENERATOR_COORDINATES,
        "packet_output_coordinates": PACKET_OUTPUT_COORDINATES,
        "packet_coordinates": PACKET_COORDINATES,
        "inherited_serializer_fullstate_ready": False,
        "future_serializer_revision_required": True,
    }


def validate_request(request):
    if request.get("schema") != SCHEMA or request.get("identity") != IDENTITY:
        raise ContractError("source identity mismatch")
    if request.get("base_commit") != BASE_COMMIT or request.get("parent_draft") != 6609:
        raise ContractError("parent source mismatch")
    if request.get("target") != expected_target():
        raise ContractError("first-step target mismatch")
    if STATE_COORDINATES + PACKET_COORDINATES != COORDINATE_DENOMINATOR:
        raise ContractError("internal coordinate denominator mismatch")
    if request.get("future_execution_envelope") != expected_envelope():
        raise ContractError("future execution envelope mismatch")
    if request.get("serializer_requirements") != expected_serializer_requirements():
        raise ContractError("full-state serializer requirements mismatch")
    if (
        PACKET_ALPHA_COORDINATES
        + PACKET_GENERATOR_COORDINATES
        + PACKET_OUTPUT_COORDINATES
        != PACKET_COORDINATES
    ):
        raise ContractError("internal packet coordinate denominator mismatch")
    if set(request.get("future_sources", {}).values()) != {None}:
        raise ContractError("future numerical sources are already populated")
    if set(request.get("required_future_admission", {}).values()) != {None}:
        raise ContractError("future execution admission is already populated")
    if request.get("numerical_execution_allowed") is not False:
        raise ContractError("numerical execution unexpectedly enabled")
    if request.get("authentic_firststep_capsules") != 0:
        raise ContractError("source contract claims an authentic capsule")
    if request.get("authentic_firststep_coordinates") != 0:
        raise ContractError("source contract claims authentic coordinates")
    required_true = (
        "historical_resource_red_6295_unchanged",
        "historical_negative_and_unknown_preserved",
    )
    if any(request.get(field) is not True for field in required_true):
        raise ContractError("historical RED/UNKNOWN is not preserved")
    required_false = (
        "full_roster_qualification",
        "largegrid_qualification",
        "production_adoption",
        "all_closed",
    )
    if any(request.get(field) is not False for field in required_false):
        raise ContractError("source contract grants qualification or adoption")
    return request


def validate_future_receipt(receipt):
    """Validate shape only after a separately frozen future admission."""

    if receipt.get("schema") != "hcsn-n256-corrected-firststep-receipt-v1":
        raise ContractError("future receipt schema mismatch")
    if receipt.get("identity") != IDENTITY or receipt.get("target") != expected_target():
        raise ContractError("future receipt target mismatch")
    counts = receipt.get("coordinate_counts")
    if counts != {
        "state": STATE_COORDINATES,
        "packet": PACKET_COORDINATES,
        "total": COORDINATE_DENOMINATOR,
        "compared": COORDINATE_DENOMINATOR,
        "equal": COORDINATE_DENOMINATOR,
        "mismatches": 0,
    }:
        raise ContractError("future coordinate denominator mismatch")
    if receipt.get("packet_count") != PACKETS:
        raise ContractError("future packet denominator mismatch")
    calls = receipt.get("calls", {})
    envelope = expected_envelope()
    exact_calls = {
        "candidate_dynamic_steps": "candidate_dynamic_steps_max",
        "candidate_sparse_exponential_actions": "candidate_sparse_exponential_actions_max",
        "oracle_dynamic_steps": "oracle_dynamic_steps_max",
        "oracle_dense_exponentials": "oracle_dense_exponentials_max",
        "canonical_decode_calls": "canonical_decode_calls_max",
        "canonical_encode_calls": "canonical_encode_calls_max",
    }
    for actual_name, expected_name in exact_calls.items():
        actual = calls.get(actual_name)
        if type(actual) is not int or actual != envelope[expected_name]:
            raise ContractError(f"future exact call count mismatch: {actual_name}")
    if calls.get("torch_calls") != 0 or calls.get("optimizer_steps") != 0:
        raise ContractError("future receipt contains Torch or optimizer work")
    if receipt.get("candidate_oracle_bitwise_equal") is not True:
        raise ContractError("future candidate/oracle comparison is not exact")
    if receipt.get("canonical_roundtrip_bytes_equal") is not True:
        raise ContractError("future canonical roundtrip is not exact")
    if receipt.get("canonical_roundtrip_coordinate_rows_equal") is not True:
        raise ContractError("future canonical full-state rows are not exact")
    if receipt.get("serialized_packet_output_coordinates") != PACKET_OUTPUT_COORDINATES:
        raise ContractError("future serializer omits packet output coordinates")
    size = receipt.get("capsule_bytes")
    if type(size) is not int or not 0 < size <= envelope["capsule_max_bytes"]:
        raise ContractError("future capsule size exceeds the frozen bound")
    if receipt.get("historical_negative_and_unknown_preserved") is not True:
        raise ContractError("future receipt erases historical RED/UNKNOWN")
    for field in (
        "full_roster_qualification",
        "largegrid_qualification",
        "production_adoption",
        "all_closed",
    ):
        if receipt.get(field) is not False:
            raise ContractError(f"future receipt grants {field}")
    return receipt


def canonical_json(value):
    validate_future_receipt(value)
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
