"""Read-only margin audit of the immutable PR #6957 index537 originals."""

import argparse
from fractions import Fraction
import hashlib
import io
import json
import lzma
import math
from pathlib import Path
import struct
import tarfile
import zipfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EVIDENCE = REPO / "qualification" / "hcsn_ci_readbacks" / "6957"
ORIGINALS = EVIDENCE / "originals"
EXPECTED_SOURCE = "23980910e03fc62da839b11271a80241eaa21d9b"
EXPECTED_RUN = 45005537845
EXPECTED_COLLECTOR_SHA256 = (
    "452e22f354928f88742d840d3287c160153b8e86d4ed5346b0d0628d0ddacbf4"
)
EXPECTED_IDENTITY = "hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-v1"
EXPECTED_KEY = "hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-001"
CHECKPOINT_MAGIC = b"HCSNCPT1"
CHECKPOINT_HEADER = struct.Struct(">8sQQ32s32s")
TARGET_DIVISOR = 4
SEARCH_LIMIT = 2048


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _pair(value, label):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(part, str) and part for part in value)
    ):
        raise SystemExit(f"{label} is not a two-hex-string fraction")
    numerator = int(value[0], 16)
    denominator = int(value[1], 16)
    if numerator < 0 or denominator <= 0:
        raise SystemExit(f"{label} fraction domain differs")
    return numerator, denominator


def _signed_pair(value, label):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(part, str) and part for part in value)
    ):
        raise SystemExit(f"{label} is not a two-hex-string fraction")
    numerator = int(value[0], 16)
    denominator = int(value[1], 16)
    if denominator <= 0:
        raise SystemExit(f"{label} fraction domain differs")
    return numerator, denominator


def _log2_ratio(numerator, denominator):
    """Return a stable diagnostic approximation without decimal big-int conversion."""

    if numerator <= 0 or denominator <= 0:
        raise SystemExit("log2 ratio is outside the positive domain")
    n_shift = max(0, numerator.bit_length() - 53)
    d_shift = max(0, denominator.bit_length() - 53)
    n_top = numerator >> n_shift
    d_top = denominator >> d_shift
    return (n_shift - d_shift) + math.log2(n_top / d_top)


def _binary64(raw_hex):
    if not isinstance(raw_hex, str) or len(raw_hex) != 16:
        raise SystemExit("binary64 hex width differs")
    return struct.unpack(">d", bytes.fromhex(raw_hex))[0]


def _restore_collector():
    manifest = json.loads((EVIDENCE / "MANIFEST.json").read_text())
    parts = json.loads((EVIDENCE / "PARTS.json").read_text())
    if (
        manifest["source_commit"] != EXPECTED_SOURCE
        or manifest["run_id"] != EXPECTED_RUN
        or manifest["collector"]["sha256"] != EXPECTED_COLLECTOR_SHA256
    ):
        raise SystemExit("#6957 evidence identity differs")
    chunks = []
    for record in parts:
        raw = (ORIGINALS / record["file"]).read_bytes()
        if len(raw) != record["size"] or _sha256(raw) != record["sha256"]:
            raise SystemExit(f"original part differs: {record['file']}")
        chunks.append(raw)
    bundle = b"".join(chunks)
    if (
        len(bundle) != manifest["bundle"]["size"]
        or _sha256(bundle) != manifest["bundle"]["sha256"]
    ):
        raise SystemExit("restored #6957 bundle differs")
    collector_record = manifest["collector"]
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:") as archive:
        member = archive.extractfile(collector_record["file"])
        if member is None:
            raise SystemExit("collector member is absent")
        collector = member.read()
    if (
        len(collector) != collector_record["size"]
        or _sha256(collector) != collector_record["sha256"]
    ):
        raise SystemExit("collector bytes differ")
    return collector


def _decode_checkpoint(payload, result):
    if (
        len(payload) != result["checkpoint_compact_bytes"]
        or _sha256(payload) != result["checkpoint_compact_sha256"]
    ):
        raise SystemExit("checkpoint compact binding differs")
    magic, raw_size, compressed_size, raw_sha, compressed_sha = (
        CHECKPOINT_HEADER.unpack(payload[: CHECKPOINT_HEADER.size])
    )
    compressed = payload[CHECKPOINT_HEADER.size :]
    if (
        magic != CHECKPOINT_MAGIC
        or compressed_size != len(compressed)
        or hashlib.sha256(compressed).digest() != compressed_sha
    ):
        raise SystemExit("checkpoint envelope differs")
    raw = lzma.decompress(compressed, format=lzma.FORMAT_XZ)
    if (
        len(raw) != raw_size
        or len(raw) != result["checkpoint_raw_bytes"]
        or hashlib.sha256(raw).digest() != raw_sha
        or _sha256(raw) != result["checkpoint_raw_sha256"]
    ):
        raise SystemExit("checkpoint raw binding differs")
    envelope = json.loads(raw.decode("ascii"))
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != raw:
        raise SystemExit("checkpoint JSON is not canonical")
    body = envelope["body"]
    if (
        body["schema"] != "hcsn-n256-authentic-index537-tail-checkpoint-v1"
        or body["included_index"] != 537
        or body["lane"] != result["lane"]
    ):
        raise SystemExit("checkpoint body identity differs")
    return body


def _first_tail_only_index(growth, tail_argument, total_variation, target):
    """Find an exact bound-only threshold without executing the recurrence."""

    growth_n, growth_d = growth
    tail_n, tail_d = tail_argument
    variation_n, variation_d = total_variation
    target_n, target_d = target
    for included_index in range(537, SEARCH_LIMIT + 1):
        next_growth_n = growth_n * tail_n
        next_growth_d = growth_d * tail_d * (included_index + 1)
        ratio_gap = tail_d * (included_index + 2) - tail_n
        if ratio_gap <= 0:
            raise SystemExit("future ratio-bound precondition differs")
        remainder_n = (
            variation_n
            * next_growth_n
            * tail_d
            * (included_index + 2)
        )
        remainder_d = variation_d * next_growth_d * ratio_gap
        if (
            TARGET_DIVISOR * remainder_n * target_d
            < target_n * remainder_d
        ):
            return included_index, remainder_n, remainder_d
        growth_n, growth_d = next_growth_n, next_growth_d
    raise SystemExit("tail-only search limit is insufficient")


def _inspect_lane(combined, ordinal):
    result = json.loads(combined.read(f"lane-{ordinal:02d}.RESULT.json"))
    tail = json.loads(combined.read(f"lane-{ordinal:02d}.TAIL.json"))
    if (
        result["identity"] != EXPECTED_IDENTITY
        or result["execution_key"] != EXPECTED_KEY
        or result["lane_ordinal"] != ordinal
        or tail["included_index"] != 537
        or tail["unique_coordinate_count"] != 0
        or tail["all_coordinates_unique"]
    ):
        raise SystemExit(f"lane {ordinal} result identity differs")
    body = _decode_checkpoint(combined.read(result["checkpoint_file"]), result)
    partial = [_signed_pair(value, "partial") for value in body["partial"]]
    iterate = [_signed_pair(value, "iterate") for value in body["iterate"]]
    if len(partial) != tail["coordinate_count"] or len(iterate) != len(partial):
        raise SystemExit(f"lane {ordinal} coordinate denominator differs")
    partial_zeros = sum(numerator == 0 for numerator, _ in partial)
    iterate_zeros = sum(numerator == 0 for numerator, _ in iterate)
    minimum_partial = min(
        ((abs(numerator), denominator) for numerator, denominator in partial),
        key=lambda item: Fraction(*item),
    )
    rows = tail["rounding"]
    straddling = sum(
        _binary64(row["lower_hex"]) < 0.0 < _binary64(row["upper_hex"])
        for row in rows
    )
    if straddling != len(rows):
        raise SystemExit(f"lane {ordinal} zero-straddling record differs")
    threshold_index, remainder_n, remainder_d = _first_tail_only_index(
        _pair(body["growth_coefficient"], "growth coefficient"),
        _pair(tail["tail_argument"], "tail argument"),
        _pair(tail["total_variation"], "total variation"),
        minimum_partial,
    )
    tail_n, tail_d = _pair(tail["tail_argument"], "tail argument")
    ratio_d = tail_d * tail["ratio_denominator"]
    ratio_gap = ratio_d - tail_n
    maximum_width = _pair(tail["maximum_interval_width"], "maximum width")
    current_remainder = _pair(tail["remainder_bound"], "remainder")
    return {
        "lane": ordinal,
        "stem": result["stem"],
        "coordinate_count": len(rows),
        "zero_straddling_coordinates": straddling,
        "partial_exact_zero_count": partial_zeros,
        "iterate_exact_zero_count": iterate_zeros,
        "index537_tail_ratio_complement_log2": _log2_ratio(ratio_gap, ratio_d),
        "index537_remainder_log2": _log2_ratio(*current_remainder),
        "index537_maximum_interval_width_log2": _log2_ratio(*maximum_width),
        "index537_minimum_abs_partial_log2": _log2_ratio(*minimum_partial),
        "first_tail_only_quarter_current_partial_index": threshold_index,
        "additional_bound_updates_from_index537": threshold_index - 537,
        "projected_remainder_log2_at_threshold": _log2_ratio(
            remainder_n, remainder_d
        ),
    }


def audit():
    collector = _restore_collector()
    with zipfile.ZipFile(io.BytesIO(collector)) as combined:
        if combined.testzip() is not None:
            raise SystemExit("collector ZIP CRC differs")
        final = json.loads(combined.read("RESULT.json"))
        if (
            final["completed_lanes"] != 10
            or final["failures"]
            or final["scope"]["tail_termination_closed"]
        ):
            raise SystemExit("collector terminal state differs")
        lanes = [_inspect_lane(combined, ordinal) for ordinal in range(10)]
    total_coordinates = sum(item["coordinate_count"] for item in lanes)
    return {
        "identity": "hcsn-n256-tail537-margin-readonly-audit-20261122-c6bc-v1",
        "source_pr": 6957,
        "source_sha": EXPECTED_SOURCE,
        "source_run": EXPECTED_RUN,
        "collector_sha256": EXPECTED_COLLECTOR_SHA256,
        "status": "TAIL_MARGIN_CHARACTERIZED_RESOURCE_HOLD",
        "lanes": lanes,
        "totals": {
            "lanes": len(lanes),
            "coordinates": total_coordinates,
            "zero_straddling_coordinates": sum(
                item["zero_straddling_coordinates"] for item in lanes
            ),
            "partial_exact_zero_count": sum(
                item["partial_exact_zero_count"] for item in lanes
            ),
            "iterate_exact_zero_count": sum(
                item["iterate_exact_zero_count"] for item in lanes
            ),
            "maximum_tail_only_threshold_index": max(
                item["first_tail_only_quarter_current_partial_index"]
                for item in lanes
            ),
            "maximum_additional_bound_updates": max(
                item["additional_bound_updates_from_index537"] for item in lanes
            ),
        },
        "work": {
            "archive_restores": 1,
            "checkpoint_decodes": 10,
            "tail_only_integer_bound_updates": sum(
                item["additional_bound_updates_from_index537"] + 1
                for item in lanes
            ),
            "recurrence_row_actions": 0,
            "candidate_tail_checks": 0,
            "provider_calls": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
            "model_calls": 0,
            "training_calls": 0,
        },
        "gates": {
            "first_tail_observation_complete": True,
            "tail_margin_characterized": True,
            "tail_termination_closed": False,
            "threshold_is_qualification": False,
            "index1159_checkpoint_size_profile_complete": False,
            "index1159_recurrence_cost_profile_complete": False,
            "index1159_updated_partial_evaluated": False,
            "index1159_rounding_evaluated": False,
            "n256_qualified": False,
            "all_closed": False,
        },
        "interpretation": (
            "The threshold advances only the already-recorded positive tail-bound scalar. "
            "It does not update the signed recurrence, partial vector, exponential sum, "
            "checkpoint size, cost, or binary64 rounding intervals and is not a tail-"
            "termination or N256 qualification result."
        ),
        "historical_state": {
            "pr6939": "RED",
            "pr6950": "RED",
            "pr6942": "RED_TIMEOUT_COMPLETED_ACTIONS_UNKNOWN",
            "pr6901": "UNKNOWN",
            "global": "HOLD_NOUPDATE",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-expected", type=Path)
    args = parser.parse_args()
    result = audit()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.verify_expected is not None:
        expected = args.verify_expected.read_text()
        if encoded != expected:
            raise SystemExit("committed audit result differs")
    print(encoded, end="")


if __name__ == "__main__":
    main()
