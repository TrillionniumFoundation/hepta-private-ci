"""Compose externally proved provider errors without executing N256 numerics."""

import hashlib
import json
import math
from dataclasses import dataclass


POLICY_SCHEMA = "hcsn-n256-uniformization-precision-policy-v1"
CERTIFICATE_SCHEMA = "hcsn-n256-uniformization-precision-certificate-v1"
ORIGINAL_SCALED_ERROR_LIMIT = 0.01
COMPONENT_FIELDS = (
    "poisson_tail_upper_fp64_hex",
    "sparse_row_action_rounding_upper_fp64_hex",
    "poisson_recurrence_rounding_upper_fp64_hex",
    "accumulation_rounding_upper_fp64_hex",
    "serialization_rounding_upper_fp64_hex",
)
REQUIRED_SCIENTIFIC_CERTIFICATIONS = (
    "permanent_nonreturning_upper_escape",
    "deterministic_delay_and_reset",
    "signed_l1_tail",
    "discounted_hit_and_occupation",
    "fp64_rounding",
    "every_emitted_roster_operator",
)


class PrecisionPolicyError(ValueError):
    """Raised before accepting an incomplete or understated precision record."""


@dataclass(frozen=True)
class PrecisionPolicyResult:
    component_count: int
    recomputed_total_upper_fp64_hex: str
    declared_total_upper_fp64_hex: str
    original_scaled_error_limit_fp64_hex: str
    within_original_limit: bool
    certificate_identity_valid: bool
    provider_admitted: bool = False
    n256_provider_calls: int = 0
    tail_certificates_admitted: int = 0
    largegrid_qualification: bool = False


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _bound(record, field):
    raw = record.get(field)
    if not isinstance(raw, str):
        raise PrecisionPolicyError(f"missing binary64 bound: {field}")
    try:
        value = float.fromhex(raw)
    except ValueError as error:
        raise PrecisionPolicyError(f"invalid binary64 bound: {field}") from error
    if not math.isfinite(value) or value < 0.0 or value.hex() != raw:
        raise PrecisionPolicyError(f"noncanonical binary64 bound: {field}")
    return value


def outward_nonnegative_sum(values):
    """Add nonnegative binary64 bounds with one outward ULP per operation."""

    total = 0.0
    for value in values:
        if not math.isfinite(value) or value < 0.0:
            raise PrecisionPolicyError("precision component is invalid")
        total = math.nextafter(total + value, math.inf)
    return total


def validate_precision_certificate(record, provider_source_sha256, provider_admission_sha256):
    """Validate a future immutable record; never create or admit one here."""

    required = {
        "schema",
        "policy_sha256",
        "provider_source_sha256",
        "provider_admission_sha256",
        "operator_identity",
        "roster_identity",
        "lane",
        "left_fraction",
        "right_fraction",
        "input_l1_fp64_hex",
        "truncation_index",
        "recurrence_terms",
        *COMPONENT_FIELDS,
        "total_provider_error_upper_fp64_hex",
        "original_scaled_error_limit_fp64_hex",
        "scientific_certifications",
        "certificate_sha256",
    }
    if set(record) != required:
        raise PrecisionPolicyError("precision certificate field set mismatch")
    if (
        record["schema"] != CERTIFICATE_SCHEMA
        or record["provider_source_sha256"] != provider_source_sha256
        or record["provider_admission_sha256"] != provider_admission_sha256
        or not all(
            isinstance(record[name], str) and len(record[name]) == 64
            for name in (
                "policy_sha256",
                "provider_source_sha256",
                "provider_admission_sha256",
                "operator_identity",
                "roster_identity",
            )
        )
    ):
        raise PrecisionPolicyError("precision certificate identity mismatch")
    if record["lane"] not in {"warm", "coarse", "cold"}:
        raise PrecisionPolicyError("precision certificate lane mismatch")
    for name in ("left_fraction", "right_fraction"):
        pair = record[name]
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, int) for item in pair)
            or pair[1] <= 0
        ):
            raise PrecisionPolicyError("precision certificate fraction mismatch")
    if record["right_fraction"][0] * record["left_fraction"][1] <= record[
        "left_fraction"
    ][0] * record["right_fraction"][1]:
        raise PrecisionPolicyError("precision certificate interval is not positive")
    if (
        not isinstance(record["truncation_index"], int)
        or record["truncation_index"] < 0
        or record["recurrence_terms"] != record["truncation_index"] + 1
    ):
        raise PrecisionPolicyError("precision recurrence identity mismatch")
    _bound(record, "input_l1_fp64_hex")
    components = tuple(_bound(record, name) for name in COMPONENT_FIELDS)
    recomputed = outward_nonnegative_sum(components)
    declared = _bound(record, "total_provider_error_upper_fp64_hex")
    original_limit = _bound(record, "original_scaled_error_limit_fp64_hex")
    if original_limit.hex() != ORIGINAL_SCALED_ERROR_LIMIT.hex():
        raise PrecisionPolicyError("original scaled error limit changed")
    if declared < recomputed:
        raise PrecisionPolicyError("declared provider error understates components")
    if declared > original_limit:
        raise PrecisionPolicyError("provider error exceeds original scaled limit")
    certifications = record["scientific_certifications"]
    if set(certifications) != set(REQUIRED_SCIENTIFIC_CERTIFICATIONS) or not all(
        value is True for value in certifications.values()
    ):
        raise PrecisionPolicyError("scientific certification set is incomplete")
    payload = dict(record)
    digest = payload.pop("certificate_sha256")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        raise PrecisionPolicyError("precision certificate digest mismatch")
    return PrecisionPolicyResult(
        component_count=len(components),
        recomputed_total_upper_fp64_hex=recomputed.hex(),
        declared_total_upper_fp64_hex=declared.hex(),
        original_scaled_error_limit_fp64_hex=original_limit.hex(),
        within_original_limit=True,
        certificate_identity_valid=True,
    )
