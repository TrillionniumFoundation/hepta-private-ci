"""Fail-closed interface for a future independent N256 reference stream.

This module is stdlib-only. It validates already-produced small fixture rows and
source/admission metadata. It cannot import or invoke the candidate, oracle,
serializer, dynamic operator, matrix exponential, Torch, or optimizer.
"""

import hashlib
import json
import math
import re
from fractions import Fraction
from pathlib import Path


SCHEMA = "hcsn-n256-independent-reference-coordinate-stream/v1"
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
CANDIDATE_SOURCE_SHA256 = "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9"
ORACLE_SOURCE_SHA256 = "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73"
COMPARATOR_SOURCE_SHA256 = "d20bfd4ae57e783d506a571e9a9ecb1deed836a8abbafa6e870f2879595972cf"
EXPECTED_DENOMINATOR = 18_225_028
EXPECTED_CAPSULES = 14
EXPECTED_LANE_CAPSULES = {"warm": 8, "coarse": 3, "cold": 3}
LANE_OFFSETS = {"warm": 0, "coarse": 8, "cold": 11}
ROW_FIELDS = {
    "sequence",
    "capsule_order",
    "lane",
    "lane_order",
    "time_numerator",
    "time_denominator",
    "surface",
    "packet_identity",
    "generation",
    "origin",
    "target",
    "support_start_numerator",
    "support_start_denominator",
    "support_end_numerator",
    "support_end_denominator",
    "coordinate_index",
    "value_hex",
}
PROVENANCE_FIELDS = {
    "schema",
    "input_bundle_sha256",
    "roster_identity",
    "candidate_source_sha256",
    "oracle_source_sha256",
    "comparator_source_sha256",
    "reference_provider_source_sha256",
    "reference_provider_admission_sha256",
    "independence_review_sha256",
    "runtime_profile_sha256",
    "method_id",
    "precommitted_source",
    "imports_candidate_or_oracle",
    "shared_numeric_kernel",
}
_SURFACE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class AdmissionRequired(RuntimeError):
    """Raised before any future reference-provider numerical work."""


def _sha256(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _fraction(numerator, denominator, name):
    _integer(numerator, f"{name} numerator", minimum=-2**63)
    _integer(denominator, f"{name} denominator", minimum=1)
    value = Fraction(numerator, denominator)
    if value.numerator != numerator or value.denominator != denominator:
        raise ValueError(f"{name} must be a reduced fraction")
    return value


def _canonical_hex(value):
    if not isinstance(value, str):
        raise ValueError("reference value must be canonical FP64 hexadecimal")
    number = float.fromhex(value)
    if not math.isfinite(number) or number == 0.0 and value.startswith("-"):
        raise ValueError("reference value must be finite and not negative zero")
    if number.hex() != value:
        raise ValueError("reference value must be canonical FP64 hexadecimal")
    return number


def validate_request(request):
    """Validate the current source-only request and its unresolved provider."""

    exact = {
        "schema": "hcsn-n256-independent-reference-stream-source-intent-v1",
        "stream_schema": SCHEMA,
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "candidate_source_sha256": CANDIDATE_SOURCE_SHA256,
        "oracle_source_sha256": ORACLE_SOURCE_SHA256,
        "comparator_source_sha256": COMPARATOR_SOURCE_SHA256,
        "coordinate_denominator": EXPECTED_DENOMINATOR,
        "capsules": EXPECTED_CAPSULES,
        "lane_capsules": EXPECTED_LANE_CAPSULES,
    }
    for name, expected in exact.items():
        if request.get(name) != expected:
            raise ValueError(f"{name} mismatch")
    for name in (
        "reference_provider_source_sha256",
        "reference_provider_admission_sha256",
        "numerical_idempotency_key",
    ):
        if request.get(name) is not None:
            raise ValueError(f"source intent must leave {name} unresolved")
    if request.get("numerical_execution_allowed") is not False:
        raise ValueError("reference numerical execution must remain disabled")
    if request.get("preserved_history") != {
        "red_6295": True,
        "red_unknown_6302": True,
        "red_joint_hold_6303": True,
    }:
        raise ValueError("historical RED/UNKNOWN preservation mismatch")
    if request.get("largegrid_qualification") is not False:
        raise ValueError("interface intent cannot qualify N256")
    if request.get("all_closed") is not False:
        raise ValueError("interface intent cannot close the global gate")
    return request


def require_reference_execution_admission(request_path, admission_path):
    """Reject this source head before a provider or stream is opened."""

    request = validate_request(json.loads(Path(request_path).read_text()))
    if (
        admission_path is None
        or request["reference_provider_source_sha256"] is None
        or request["reference_provider_admission_sha256"] is None
    ):
        raise AdmissionRequired("independent N256 reference provider is not frozen or admitted")
    raise AdmissionRequired("this source-only head cannot execute a reference provider")


def validate_provenance(provenance):
    """Validate future provider metadata without trusting a self-declared label."""

    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_FIELDS:
        raise ValueError("reference provenance field set mismatch")
    exact = {
        "schema": SCHEMA,
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "candidate_source_sha256": CANDIDATE_SOURCE_SHA256,
        "oracle_source_sha256": ORACLE_SOURCE_SHA256,
        "comparator_source_sha256": COMPARATOR_SOURCE_SHA256,
        "precommitted_source": True,
        "imports_candidate_or_oracle": False,
        "shared_numeric_kernel": False,
    }
    for name, expected in exact.items():
        if provenance.get(name) != expected:
            raise ValueError(f"{name} mismatch")
    provider = _sha256(
        provenance["reference_provider_source_sha256"], "reference provider source"
    )
    for name in (
        "reference_provider_admission_sha256",
        "independence_review_sha256",
        "runtime_profile_sha256",
    ):
        _sha256(provenance[name], name)
    if provider in {CANDIDATE_SOURCE_SHA256, ORACLE_SOURCE_SHA256, COMPARATOR_SOURCE_SHA256}:
        raise ValueError("reference provider source is not independent")
    method = provenance["method_id"]
    if not isinstance(method, str) or not _SURFACE.fullmatch(method):
        raise ValueError("reference method_id is not canonical")
    return provenance


def validate_reference_rows(rows, expected_records):
    """Validate an identity-complete reference stream and return its byte digest.

    The full future call must use EXPECTED_DENOMINATOR. Tests may use a smaller
    explicit denominator and therefore do not claim N256 execution.
    """

    _integer(expected_records, "expected records", minimum=1)
    digest = hashlib.sha256()
    capsules = set()
    lane_orders = {lane: set() for lane in EXPECTED_LANE_CAPSULES}
    count = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise ValueError("reference row field set mismatch")
        if _integer(row["sequence"], "sequence") != count:
            raise ValueError("reference sequence is not contiguous")
        capsule = _integer(row["capsule_order"], "capsule order")
        if capsule >= EXPECTED_CAPSULES:
            raise ValueError("capsule order is outside the frozen schedule")
        lane = row["lane"]
        if lane not in EXPECTED_LANE_CAPSULES:
            raise ValueError("unknown reference lane")
        lane_order = _integer(row["lane_order"], "lane order")
        if lane_order >= EXPECTED_LANE_CAPSULES[lane]:
            raise ValueError("lane order is outside the frozen schedule")
        if capsule != LANE_OFFSETS[lane] + lane_order:
            raise ValueError("capsule and lane order mismatch")
        _fraction(row["time_numerator"], row["time_denominator"], "time")
        start = _fraction(
            row["support_start_numerator"],
            row["support_start_denominator"],
            "support start",
        )
        end = _fraction(
            row["support_end_numerator"],
            row["support_end_denominator"],
            "support end",
        )
        if start > end:
            raise ValueError("support interval is reversed")
        if not isinstance(row["surface"], str) or not _SURFACE.fullmatch(row["surface"]):
            raise ValueError("surface is not canonical")
        packet = row["packet_identity"]
        if not isinstance(packet, str) or not packet or len(packet.encode("utf-8")) > 256:
            raise ValueError("packet identity is not bounded")
        for name in ("generation", "origin", "target", "coordinate_index"):
            _integer(row[name], name)
        _canonical_hex(row["value_hex"])
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest.update(encoded.encode("ascii") + b"\n")
        capsules.add(capsule)
        lane_orders[lane].add(lane_order)
        count += 1
    if count != expected_records:
        raise ValueError("reference coordinate denominator mismatch")
    return {
        "records": count,
        "capsules_observed": len(capsules),
        "lane_capsules_observed": {lane: len(orders) for lane, orders in lane_orders.items()},
        "canonical_jsonl_sha256": digest.hexdigest(),
        "numerical_execution_performed_by_validator": False,
    }
