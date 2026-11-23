"""Fail-closed validation for one completed index1159 lane."""

import json
import math
import re

from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    CompactCheckpointError,
    decode_compact_checkpoint,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
)

from .admission import MAX_JSON_BYTES, _bounded_regular_bytes, _sha256, _strict_json
from .continuation import (
    TARGET_INDEX,
    TARGET_SCHEMA,
    encode_raw_index1159,
    parse_index1159,
)


MAX_TAIL_BYTES = 4 * 1024 * 1024
STEM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}")
RESULT_KEYS = {
    "identity",
    "execution_key",
    "lane_ordinal",
    "stem",
    "checkpoint_file",
    "checkpoint_raw_bytes",
    "checkpoint_raw_sha256",
    "checkpoint_compact_bytes",
    "checkpoint_compact_sha256",
    "tail_file",
    "tail_sha256",
    "tail",
    "work",
    "cost",
}
TAIL_KEYS = {
    "included_index",
    "ratio_denominator",
    "argument",
    "tail_argument",
    "growth_tail",
    "remainder_bound",
    "maximum_interval_width",
    "coordinate_count",
    "unique_coordinate_count",
    "all_coordinates_unique",
    "rounding",
    "rounding_sha256",
    "tail_vector_fp64_conversions",
    "rounding_calls",
}
WORK_KEYS = {
    "index537_compact_decodes",
    "recurrence_row_actions",
    "tail_checks",
    "rounding_calls",
    "index1159_compact_encodes",
    "index1159_compact_decodes",
}
COST_KEYS = {"wall_seconds", "cpu_seconds", "max_rss_kib"}


def _require_int(value, label, *, minimum=0):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SystemExit(f"{label} is not a bounded integer")
    return value


def _require_digest(value, label):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SystemExit(f"{label} is not a lowercase SHA-256 digest")
    return value


def _require_exact_keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise SystemExit(f"{label} fields differ from the frozen schema")


def _validate_rounding(tail):
    rounding = tail["rounding"]
    if not isinstance(rounding, list):
        raise SystemExit("tail rounding is not a list")
    unique = 0
    for ordinal, record in enumerate(rounding):
        _require_exact_keys(
            record, {"ordinal", "lower_hex", "upper_hex", "unique"}, "rounding record"
        )
        if record["ordinal"] != ordinal:
            raise SystemExit("rounding ordinals are not canonical")
        if not isinstance(record["lower_hex"], str) or not isinstance(
            record["upper_hex"], str
        ):
            raise SystemExit("rounding endpoints are not strings")
        expected_unique = record["lower_hex"] == record["upper_hex"]
        if record["unique"] is not expected_unique:
            raise SystemExit("rounding uniqueness differs from its endpoints")
        unique += expected_unique
    canonical = json.dumps(rounding, sort_keys=True, separators=(",", ":")).encode()
    if _sha256(canonical) != _require_digest(
        tail["rounding_sha256"], "tail rounding digest"
    ):
        raise SystemExit("tail rounding digest mismatch")
    if tail["coordinate_count"] != len(rounding):
        raise SystemExit("tail coordinate denominator mismatch")
    if tail["unique_coordinate_count"] != unique:
        raise SystemExit("tail unique-coordinate count mismatch")
    if tail["all_coordinates_unique"] is not (unique == len(rounding)):
        raise SystemExit("tail all-unique flag mismatch")
    if tail["rounding_calls"] != 2 * len(rounding):
        raise SystemExit("tail rounding-call count mismatch")


def validate_lane_result(result_path, ordinal, request, identity):
    """Return one lane result only after its immutable outputs are re-read."""

    label = f"lane {ordinal:02d} result"
    result_raw = _bounded_regular_bytes(result_path, label, max_bytes=MAX_JSON_BYTES)
    result = _strict_json(result_raw, label)
    _require_exact_keys(result, RESULT_KEYS, label)
    if (
        result["identity"] != identity
        or result["execution_key"] != request["execution_key"]
    ):
        raise SystemExit(f"{label} identity differs")
    if result["lane_ordinal"] != ordinal:
        raise SystemExit(f"{label} ordinal differs")
    stem = result["stem"]
    if not isinstance(stem, str) or STEM_PATTERN.fullmatch(stem) is None:
        raise SystemExit(f"{label} stem is not a safe basename")

    checkpoint_name = f"{stem}.index1159.checkpoint.hcsncp"
    if result["checkpoint_file"] != checkpoint_name:
        raise SystemExit(f"{label} checkpoint filename differs")
    compact = _bounded_regular_bytes(
        result_path.parent / checkpoint_name,
        f"lane {ordinal:02d} compact checkpoint",
        max_bytes=request["checkpoint_caps"]["per_cursor_compact_bytes"],
    )
    if len(compact) != _require_int(
        result["checkpoint_compact_bytes"], "compact checkpoint byte count", minimum=1
    ) or _sha256(compact) != _require_digest(
        result["checkpoint_compact_sha256"], "compact checkpoint digest"
    ):
        raise SystemExit(f"{label} compact checkpoint bytes differ")
    try:
        raw = decode_compact_checkpoint(compact, TARGET_SCHEMA, TARGET_INDEX)
    except CompactCheckpointError as error:
        raise SystemExit(f"{label} compact checkpoint is invalid") from error
    if len(raw) != _require_int(
        result["checkpoint_raw_bytes"], "raw checkpoint byte count", minimum=1
    ) or _sha256(raw) != _require_digest(
        result["checkpoint_raw_sha256"], "raw checkpoint digest"
    ):
        raise SystemExit(f"{label} raw checkpoint bytes differ")
    if len(raw) > request["checkpoint_caps"]["per_cursor_raw_bytes"]:
        raise SystemExit(f"{label} raw checkpoint exceeds the frozen cap")
    try:
        checkpoint = parse_index1159(raw)
    except (CompactCheckpointError, NonSubstochasticSignedIntervalError) as error:
        raise SystemExit(f"{label} semantic checkpoint is invalid") from error
    if checkpoint.lane != stem:
        raise SystemExit(f"{label} checkpoint lane differs from result stem")
    if encode_raw_index1159(checkpoint) != raw:
        raise SystemExit(f"{label} semantic checkpoint is not byte canonical")

    if result["tail_file"] != "TAIL.json":
        raise SystemExit(f"{label} tail filename differs")
    tail_raw = _bounded_regular_bytes(
        result_path.parent / "TAIL.json",
        f"lane {ordinal:02d} tail",
        max_bytes=MAX_TAIL_BYTES,
    )
    if _sha256(tail_raw) != _require_digest(result["tail_sha256"], "tail digest"):
        raise SystemExit(f"{label} tail bytes differ")
    tail = _strict_json(tail_raw, f"lane {ordinal:02d} tail")
    _require_exact_keys(tail, TAIL_KEYS, f"lane {ordinal:02d} tail")
    if tail["included_index"] != TARGET_INDEX:
        raise SystemExit(f"{label} tail boundary differs")
    for field in (
        "coordinate_count",
        "unique_coordinate_count",
        "tail_vector_fp64_conversions",
        "rounding_calls",
    ):
        _require_int(tail[field], f"tail {field}")
    if not isinstance(tail["all_coordinates_unique"], bool):
        raise SystemExit("tail all-unique flag is not boolean")
    _validate_rounding(tail)
    expected_summary = {
        field: tail[field]
        for field in (
            "coordinate_count",
            "unique_coordinate_count",
            "all_coordinates_unique",
            "rounding_sha256",
        )
    }
    if result["tail"] != expected_summary:
        raise SystemExit(f"{label} tail summary differs from TAIL.json")

    _require_exact_keys(result["work"], WORK_KEYS, f"{label} work")
    expected_work = {
        "index537_compact_decodes": 1,
        "recurrence_row_actions": TARGET_INDEX - request["source_index"],
        "tail_checks": 1,
        "rounding_calls": tail["rounding_calls"],
        "index1159_compact_encodes": 1,
        "index1159_compact_decodes": 1,
    }
    if result["work"] != expected_work:
        raise SystemExit(f"{label} work ledger differs")
    _require_exact_keys(result["cost"], COST_KEYS, f"{label} cost")
    for field in ("wall_seconds", "cpu_seconds"):
        value = result["cost"][field]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise SystemExit(f"{label} {field} is not finite and nonnegative")
    _require_int(result["cost"]["max_rss_kib"], f"{label} max RSS", minimum=1)
    return result
