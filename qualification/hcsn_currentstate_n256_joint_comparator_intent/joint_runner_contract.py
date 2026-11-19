"""Static manifest validator for a future admitted N256 joint run."""

import math

from .contract import BYTE_PAIR_NAMES, EXPECTED_CAPSULES, EXPECTED_DENOMINATOR, EXPECTED_LANE_CAPSULES


def _sha256(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256")


def _nonnegative_hex(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a canonical FP64 hexadecimal string")
    number = float.fromhex(value)
    if not math.isfinite(number) or number < 0.0 or number == 0.0 and value.startswith("-"):
        raise ValueError(f"{name} must be finite and non-negative")
    if number.hex() != value:
        raise ValueError(f"{name} must be canonical FP64 hexadecimal")
    return number


def validate_future_manifest(manifest):
    """Reject incomplete, reordered, cancellation-based, or non-byte-exact results."""

    if manifest.get("coordinate_denominator") != EXPECTED_DENOMINATOR:
        raise ValueError("full coordinate denominator mismatch")
    if manifest.get("capsules") != EXPECTED_CAPSULES:
        raise ValueError("capsule count mismatch")
    if manifest.get("lane_capsules") != EXPECTED_LANE_CAPSULES:
        raise ValueError("warm/coarse/cold capsule schedule mismatch")
    if manifest.get("frame_order_contiguous") is not True:
        raise ValueError("stream frame order is not contiguous")
    if manifest.get("coordinate_identity_equal") is not True:
        raise ValueError("candidate/oracle/reference coordinate identity mismatch")
    if manifest.get("signed_error_cancellation_used") is not False:
        raise ValueError("signed error cancellation is forbidden")
    errors = manifest.get("separate_error_gates")
    if not isinstance(errors, dict) or set(errors) != {"candidate", "oracle"}:
        raise ValueError("candidate and oracle require separate error gates")
    for lane, result in errors.items():
        fields = (
            "max_abs_error_hex",
            "sum_abs_error_hex",
            "max_abs_threshold_hex",
            "sum_abs_threshold_hex",
        )
        if any(field not in result for field in fields):
            raise ValueError(f"{lane} separate error fields missing")
        maximum = _nonnegative_hex(result["max_abs_error_hex"], f"{lane} maximum error")
        total = _nonnegative_hex(result["sum_abs_error_hex"], f"{lane} summed error")
        maximum_threshold = _nonnegative_hex(
            result["max_abs_threshold_hex"], f"{lane} maximum threshold"
        )
        total_threshold = _nonnegative_hex(
            result["sum_abs_threshold_hex"], f"{lane} summed threshold"
        )
        independently_passed = maximum <= maximum_threshold and total <= total_threshold
        if result.get("passed") is not independently_passed or not independently_passed:
            raise ValueError(f"{lane} error gate did not pass independently")
    pairs = manifest.get("byte_exact_pairs")
    if not isinstance(pairs, list) or [pair.get("name") for pair in pairs] != list(
        BYTE_PAIR_NAMES
    ):
        raise ValueError("warm/coarse/cold byte-pair schedule mismatch")
    for pair in pairs:
        for field in ("producer_sha256", "cold_loader_sha256"):
            _sha256(pair.get(field), field)
        if pair["producer_sha256"] != pair["cold_loader_sha256"]:
            raise ValueError(f"{pair['name']} is not byte exact")
        if pair.get("producer_bytes") != pair.get("cold_loader_bytes"):
            raise ValueError(f"{pair['name']} byte length mismatch")
        if not isinstance(pair.get("producer_bytes"), int) or pair["producer_bytes"] <= 0:
            raise ValueError(f"{pair['name']} byte length invalid")
    if manifest.get("execution_key_reused_from_frozen_lane_contracts") is not True:
        raise ValueError("future run may not allocate a new numerical key")
    return manifest
