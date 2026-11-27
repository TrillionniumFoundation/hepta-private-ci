"""Review the exact N256 stiffness envelope without numerical propagation.

This module binds the authentic generator review and symbolic event roster.  It
does not evaluate a matrix exponential, a Poisson series, or any model.  The
tail-certificate definition is an envelope only: no tail certificate is
admitted by this stage.
"""

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_exact_generator_review.generator_review import (
    review_exact_generator,
)


GENERATOR_SOURCE_SHA256 = "0beb616f348826e26591e60a4029b37b34091e257fbc5dd4c002409657c0e266"
GENERATOR_REQUEST_SHA256 = "e6af46b63a700a794997e7a620bb972bb2accd5ea032ffd8ba6c4c74ffb41908"
EVENTS_SHA256 = "e84d6ca273236341f6bd138bff9c199758fb8cf4ed43a0550ca3e77ff8076d0a"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
RATE_FRACTION_SHA256 = "77d8d711ddedb887a9ab9a4c92325b596afaaa28a2ab7793784c04461ab2739e"
MAXIMUM_EXIT = Fraction(
    1302657701562440336123138601548306288,
    2419309059512856168431144710275,
)
EXPECTED_LANE_SEGMENTS = {"warm": 21, "coarse": 15, "cold": 9}

TAIL_CERTIFICATE_ENVELOPE = {
    "schema": "hcsn-n256-uniformization-tail-certificate-v1",
    "required": [
        "provider_source_sha256",
        "provider_admission_sha256",
        "operator_identity",
        "lane",
        "left_fraction",
        "right_fraction",
        "uniformization_rate_fraction",
        "poisson_intensity_fraction",
        "truncation_index",
        "input_l1_fp64_hex",
        "poisson_tail_upper_fp64_hex",
        "rounding_upper_fp64_hex",
        "signed_l1_output_upper_fp64_hex",
        "recurrence_terms",
        "certificate_sha256",
    ],
    "required_certifications": [
        "permanent_nonreturning_upper_escape",
        "deterministic_delay_and_reset",
        "signed_l1_tail",
        "discounted_hit_and_occupation",
        "fp64_rounding",
        "every_emitted_roster_operator",
    ],
    "forbidden_null_fields": [
        "provider_source_sha256",
        "provider_admission_sha256",
        "operator_identity",
        "certificate_sha256",
    ],
}


class StiffnessReviewError(ValueError):
    """Raised before accepting a changed or incomplete stiffness input."""


@dataclass(frozen=True)
class StiffnessCertificate:
    generator_source_sha256: str
    generator_request_sha256: str
    generator_rate_fraction_sha256: str
    roster_events_sha256: str
    roster_identity: str
    generator_rows: int
    transition_segments: int
    warm_segments: int
    coarse_segments: int
    cold_segments: int
    maximum_exit_rate_fraction: str
    uniformization_rate_integer: int
    uniformization_slack_fraction: str
    maximum_segment_duration_fraction: str
    maximum_poisson_intensity_fraction: str
    ratio_tail_precondition_minimum_truncation_index: int
    ratio_tail_precondition_minimum_recurrence_terms: int
    tail_certificate_envelope_sha256: str
    tail_certificates_admitted: int = 0
    numerical_execution_allowed: bool = False
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    poisson_recurrence_calls: int = 0
    candidate_calls: int = 0
    oracle_calls: int = 0
    model_calls: int = 0
    optimizer_calls: int = 0
    provider_admitted: bool = False
    largegrid_qualification: bool = False


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _fraction_pair(value, label):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, int) for item in value)
        or value[1] <= 0
    ):
        raise StiffnessReviewError(f"invalid {label} fraction")
    return Fraction(value[0], value[1])


def review_event_records(records):
    """Validate the 45-transition schedule and return exact durations."""

    transitions = [record for record in records if record.get("kind") == "transition"]
    restores = [record for record in records if record.get("kind") == "cold_restore"]
    if len(transitions) != 45 or len(restores) != 1:
        raise StiffnessReviewError("N256 event-kind count mismatch")
    if restores[0].get("lane") != "cold" or _fraction_pair(
        restores[0].get("time", {}).get("fraction"), "cold restore"
    ) != Fraction(201, 1000):
        raise StiffnessReviewError("N256 cold-restore identity mismatch")

    counts = {lane: 0 for lane in EXPECTED_LANE_SEGMENTS}
    endpoints = {lane: [] for lane in EXPECTED_LANE_SEGMENTS}
    durations = []
    for record in transitions:
        lane = record.get("lane")
        if lane not in counts:
            raise StiffnessReviewError("N256 transition lane mismatch")
        left = _fraction_pair(record.get("left", {}).get("fraction"), "left")
        right = _fraction_pair(record.get("right", {}).get("fraction"), "right")
        if right <= left or record.get("releasing") != 1:
            raise StiffnessReviewError("N256 transition interval mismatch")
        counts[lane] += 1
        endpoints[lane].append((left, right))
        durations.append(right - left)
    if counts != EXPECTED_LANE_SEGMENTS:
        raise StiffnessReviewError("N256 per-lane transition count mismatch")
    expected_bounds = {
        "warm": (Fraction(0), Fraction(9, 25)),
        "coarse": (Fraction(0), Fraction(9, 25)),
        "cold": (Fraction(201, 1000), Fraction(9, 25)),
    }
    for lane, intervals in endpoints.items():
        if intervals[0][0] != expected_bounds[lane][0] or intervals[-1][1] != expected_bounds[lane][1]:
            raise StiffnessReviewError("N256 lane endpoint mismatch")
        if any(left[1] != right[0] for left, right in zip(intervals, intervals[1:])):
            raise StiffnessReviewError("N256 lane intervals are not contiguous")
    return tuple(durations), counts


def validate_tail_certificate_envelope(record):
    """Validate only the future certificate envelope, never its numerics."""

    if record.get("schema") != TAIL_CERTIFICATE_ENVELOPE["schema"]:
        raise StiffnessReviewError("tail certificate schema mismatch")
    missing = [name for name in TAIL_CERTIFICATE_ENVELOPE["required"] if name not in record]
    if missing:
        raise StiffnessReviewError("tail certificate field missing")
    if any(record.get(name) in (None, "") for name in TAIL_CERTIFICATE_ENVELOPE["forbidden_null_fields"]):
        raise StiffnessReviewError("tail certificate identity is null")
    certifications = record.get("certifications")
    if not isinstance(certifications, dict) or set(certifications) != set(
        TAIL_CERTIFICATE_ENVELOPE["required_certifications"]
    ) or not all(value is True for value in certifications.values()):
        raise StiffnessReviewError("tail certificate certification set mismatch")
    if not isinstance(record.get("truncation_index"), int) or record["truncation_index"] < 0:
        raise StiffnessReviewError("tail certificate truncation index mismatch")
    if not isinstance(record.get("recurrence_terms"), int) or record["recurrence_terms"] <= 0:
        raise StiffnessReviewError("tail certificate recurrence count mismatch")
    return True


def review_frozen_stiffness(
    generator_source_path,
    generator_request_path,
    events_path,
    metadata_path,
    state_path,
    phase_path,
    base64_path,
):
    """Bind exact originals and compute the exact spatial stiffness envelope."""

    if _digest(Path(generator_source_path).read_bytes()) != GENERATOR_SOURCE_SHA256:
        raise StiffnessReviewError("generator source SHA-256 mismatch")
    if _digest(Path(generator_request_path).read_bytes()) != GENERATOR_REQUEST_SHA256:
        raise StiffnessReviewError("generator request SHA-256 mismatch")
    events_raw = Path(events_path).read_bytes()
    if _digest(events_raw) != EVENTS_SHA256:
        raise StiffnessReviewError("roster events SHA-256 mismatch")
    try:
        records = [json.loads(line) for line in events_raw.splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StiffnessReviewError("roster events JSONL is invalid") from error
    durations, counts = review_event_records(records)

    generator = review_exact_generator(metadata_path, state_path, phase_path, base64_path)
    if (
        generator.rate_fraction_sha256 != RATE_FRACTION_SHA256
        or Fraction(generator.maximum_exit_rate_fraction) != MAXIMUM_EXIT
        or generator.interior_rows != 255
        or generator.dynamic_calls != 0
        or generator.matrix_exponential_calls != 0
    ):
        raise StiffnessReviewError("exact generator certificate mismatch")

    uniformization_rate = (MAXIMUM_EXIT.numerator + MAXIMUM_EXIT.denominator - 1) // MAXIMUM_EXIT.denominator
    maximum_duration = max(durations)
    maximum_intensity = uniformization_rate * maximum_duration
    minimum_index = max(0, maximum_intensity.numerator // maximum_intensity.denominator - 1)
    return StiffnessCertificate(
        generator_source_sha256=GENERATOR_SOURCE_SHA256,
        generator_request_sha256=GENERATOR_REQUEST_SHA256,
        generator_rate_fraction_sha256=RATE_FRACTION_SHA256,
        roster_events_sha256=EVENTS_SHA256,
        roster_identity=ROSTER_IDENTITY,
        generator_rows=255,
        transition_segments=len(durations),
        warm_segments=counts["warm"],
        coarse_segments=counts["coarse"],
        cold_segments=counts["cold"],
        maximum_exit_rate_fraction=str(MAXIMUM_EXIT),
        uniformization_rate_integer=uniformization_rate,
        uniformization_slack_fraction=str(uniformization_rate - MAXIMUM_EXIT),
        maximum_segment_duration_fraction=str(maximum_duration),
        maximum_poisson_intensity_fraction=str(maximum_intensity),
        ratio_tail_precondition_minimum_truncation_index=minimum_index,
        ratio_tail_precondition_minimum_recurrence_terms=minimum_index + 1,
        tail_certificate_envelope_sha256=_digest(_canonical(TAIL_CERTIFICATE_ENVELOPE)),
    )
