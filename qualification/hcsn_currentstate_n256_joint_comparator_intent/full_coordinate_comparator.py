"""Independent streaming comparator for future N256 coordinate frames.

The comparator consumes already-produced records.  It imports neither the
candidate nor the oracle implementation and cannot initiate numerical work.
"""

import math
from dataclasses import dataclass
from fractions import Fraction


LANES = ("warm", "coarse", "cold")


@dataclass(frozen=True, order=True)
class CoordinateIdentity:
    sequence: int
    capsule_order: int
    lane: str
    lane_order: int
    time_numerator: int
    time_denominator: int
    surface: str
    packet_identity: str
    generation: int
    origin: int
    target: int
    support_start_numerator: int
    support_start_denominator: int
    support_end_numerator: int
    support_end_denominator: int
    coordinate_index: int


def _canonical_hex(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a hexadecimal FP64 string")
    number = float.fromhex(value)
    if not math.isfinite(number) or number == 0.0 and value.startswith("-"):
        raise ValueError(f"{name} must be finite canonical non-negative-zero FP64")
    if number.hex() != value:
        raise ValueError(f"{name} must be canonical FP64 hex")
    return number


def _identity(row):
    return CoordinateIdentity(
        sequence=row["sequence"],
        capsule_order=row["capsule_order"],
        lane=row["lane"],
        lane_order=row["lane_order"],
        time_numerator=row["time_numerator"],
        time_denominator=row["time_denominator"],
        surface=row["surface"],
        packet_identity=row["packet_identity"],
        generation=row["generation"],
        origin=row["origin"],
        target=row["target"],
        support_start_numerator=row["support_start_numerator"],
        support_start_denominator=row["support_start_denominator"],
        support_end_numerator=row["support_end_numerator"],
        support_end_denominator=row["support_end_denominator"],
        coordinate_index=row["coordinate_index"],
    )


def _validate_identity(identity, expected_sequence):
    if identity.sequence != expected_sequence:
        raise ValueError("coordinate sequence is not contiguous canonical order")
    if identity.lane not in LANES:
        raise ValueError("unknown lane")
    for numerator, denominator, label in (
        (identity.time_numerator, identity.time_denominator, "time"),
        (
            identity.support_start_numerator,
            identity.support_start_denominator,
            "support start",
        ),
        (
            identity.support_end_numerator,
            identity.support_end_denominator,
            "support end",
        ),
    ):
        if denominator <= 0 or Fraction(numerator, denominator).denominator != denominator:
            raise ValueError(f"{label} must be a reduced fraction")
    if identity.coordinate_index < 0 or identity.capsule_order < 0:
        raise ValueError("coordinate and capsule order must be non-negative")


def _absolute_error(value, reference):
    return abs(Fraction.from_float(value) - Fraction.from_float(reference))


def _error_hex(error):
    return float(error).hex()


def compare_coordinate_streams(candidate_rows, oracle_rows, reference_rows, expected_records):
    """Compare three identity-locked streams without signed-error cancellation.

    Candidate and oracle absolute errors are accumulated and gated separately
    against the same independently supplied reference stream.  A future N256
    runner must provide that third stream; the frozen #6298 and #6300 sources do
    not yet expose this interface, so this source alone cannot execute N256.
    """

    candidate = iter(candidate_rows)
    oracle = iter(oracle_rows)
    reference = iter(reference_rows)
    candidate_max = Fraction(0)
    oracle_max = Fraction(0)
    candidate_sum = Fraction(0)
    oracle_sum = Fraction(0)
    records = 0
    capsules = set()
    lanes = {name: set() for name in LANES}
    while True:
        items = []
        ended = []
        for stream in (candidate, oracle, reference):
            try:
                items.append(next(stream))
                ended.append(False)
            except StopIteration:
                items.append(None)
                ended.append(True)
        if all(ended):
            break
        if any(ended):
            raise ValueError("candidate/oracle/reference stream lengths differ")
        identities = tuple(_identity(item) for item in items)
        if identities[0] != identities[1] or identities[0] != identities[2]:
            raise ValueError("full coordinate identity mismatch")
        identity = identities[0]
        _validate_identity(identity, records)
        candidate_value = _canonical_hex(items[0]["value_hex"], "candidate value")
        oracle_value = _canonical_hex(items[1]["value_hex"], "oracle value")
        reference_value = _canonical_hex(items[2]["value_hex"], "reference value")
        candidate_error = _absolute_error(candidate_value, reference_value)
        oracle_error = _absolute_error(oracle_value, reference_value)
        candidate_max = max(candidate_max, candidate_error)
        oracle_max = max(oracle_max, oracle_error)
        candidate_sum += candidate_error
        oracle_sum += oracle_error
        capsules.add(identity.capsule_order)
        lanes[identity.lane].add(identity.lane_order)
        records += 1
    if records != expected_records:
        raise ValueError("full coordinate denominator mismatch")
    return {
        "records": records,
        "capsules": len(capsules),
        "lane_capsules": {name: len(orders) for name, orders in lanes.items()},
        "candidate_max_abs_error_hex": _error_hex(candidate_max),
        "oracle_max_abs_error_hex": _error_hex(oracle_max),
        "candidate_sum_abs_error_hex": _error_hex(candidate_sum),
        "oracle_sum_abs_error_hex": _error_hex(oracle_sum),
        "signed_error_cancellation_used": False,
    }
