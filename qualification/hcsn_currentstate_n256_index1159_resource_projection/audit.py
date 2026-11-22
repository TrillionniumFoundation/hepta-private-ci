"""Read-only byte projection from exact N256 index256 and index537 originals."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
READBACK_256 = REPO / "qualification" / "hcsn_ci_readbacks" / "6948"
READBACK_537 = REPO / "qualification" / "hcsn_ci_readbacks" / "6957"
ORIGINALS_537 = READBACK_537 / "originals"

INDEX_256 = 256
INDEX_537 = 537
INDEX_1159 = 1159
SOURCE_SPAN = INDEX_537 - INDEX_256
TARGET_SPAN = INDEX_1159 - INDEX_537
AGGREGATE_CAP_BYTES = 67_108_864
COMPACT_CURSOR_CAP_BYTES = 8_388_608
RAW_CURSOR_CAP_BYTES = 33_554_432

EXPECTED_256_IDENTITY = "hcsn-n256-authentic-compact-checkpoint-20261122-c6bc-v1"
EXPECTED_256_KEY = "hcsn-n256-authentic-compact-checkpoint-20261122-c6bc-001"
EXPECTED_256_INPUT = "452060c65949e9c1d8ffe74e4303d707e6fe4fe7c2e75e29caacfa3137c37a91"
EXPECTED_537_IDENTITY = "hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-v1"
EXPECTED_537_KEY = "hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-001"
EXPECTED_537_SOURCE = "23980910e03fc62da839b11271a80241eaa21d9b"
EXPECTED_537_RUN = 45005537845
EXPECTED_537_COLLECTOR = "452e22f354928f88742d840d3287c160153b8e86d4ed5346b0d0628d0ddacbf4"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _ceil_div(numerator, denominator):
    if numerator < 0 or denominator <= 0:
        raise SystemExit("projection domain differs")
    return -(-numerator // denominator)


def _restore_537_collector():
    manifest = json.loads((READBACK_537 / "MANIFEST.json").read_text())
    parts = json.loads((READBACK_537 / "PARTS.json").read_text())
    if (
        manifest["source_commit"] != EXPECTED_537_SOURCE
        or manifest["run_id"] != EXPECTED_537_RUN
        or manifest["identity"] != EXPECTED_537_IDENTITY
        or manifest["execution_key"] != EXPECTED_537_KEY
        or manifest["collector"]["sha256"] != EXPECTED_537_COLLECTOR
    ):
        raise SystemExit("#6957 manifest identity differs")
    chunks = []
    for record in parts:
        raw = (ORIGINALS_537 / record["file"]).read_bytes()
        if len(raw) != record["size"] or _sha256(raw) != record["sha256"]:
            raise SystemExit(f"#6957 original part differs: {record['file']}")
        chunks.append(raw)
    bundle = b"".join(chunks)
    if (
        len(bundle) != manifest["bundle"]["size"]
        or _sha256(bundle) != manifest["bundle"]["sha256"]
    ):
        raise SystemExit("#6957 restored bundle differs")
    collector_record = manifest["collector"]
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:") as archive:
        member = archive.extractfile(collector_record["file"])
        if member is None:
            raise SystemExit("#6957 collector is absent")
        collector = member.read()
    if (
        len(collector) != collector_record["size"]
        or _sha256(collector) != collector_record["sha256"]
    ):
        raise SystemExit("#6957 collector bytes differ")
    return collector


def _load_256():
    result = json.loads((READBACK_256 / "RESULT.json").read_text())
    if (
        result["identity"] != EXPECTED_256_IDENTITY
        or result["execution_key"] != EXPECTED_256_KEY
        or result["input_zip_sha256"] != EXPECTED_256_INPUT
        or result["status"] != "AUTHENTIC_INDEX256_COMPACT_FULLSTATE_ONLY_HOLD"
        or len(result["checkpoints"]) != 10
        or result["compact_total_bytes"] != 17_078_476
        or result["raw_total_bytes"] != 62_877_713
        or result["aggregate_cap_bytes"] != AGGREGATE_CAP_BYTES
        or result["n256_qualified"]
        or result["all_closed"]
    ):
        raise SystemExit("#6948 result identity or scope differs")
    records = []
    for ordinal, record in enumerate(result["checkpoints"]):
        if record["ordinal"] != ordinal or not record["byte_exact"]:
            raise SystemExit(f"#6948 checkpoint {ordinal} identity differs")
        records.append(
            {
                "ordinal": ordinal,
                "stem": record["file"].split(".index256.", 1)[0],
                "compact_bytes": record["compact_bytes"],
                "raw_bytes": record["raw_bytes"],
            }
        )
    return result, records


def _load_537():
    collector = _restore_537_collector()
    with zipfile.ZipFile(io.BytesIO(collector)) as combined:
        if combined.testzip() is not None:
            raise SystemExit("#6957 collector CRC differs")
        final = json.loads(combined.read("RESULT.json"))
        if (
            final["identity"] != EXPECTED_537_IDENTITY
            or final["execution_key"] != EXPECTED_537_KEY
            or final["status"] != "AUTHENTIC_INDEX537_FIRST_TAIL_CHECK_COMPLETE_HOLD"
            or final["completed_lanes"] != 10
            or final["failures"]
            or final["compact_checkpoint_bytes"] != 36_293_868
            or final["aggregate_cap_bytes"] != AGGREGATE_CAP_BYTES
            or final["scope"]["n256_qualified"]
            or final["scope"]["tail_termination_closed"]
            or final["scope"]["all_closed"]
        ):
            raise SystemExit("#6957 collector identity or scope differs")
        records = []
        for ordinal in range(10):
            result = json.loads(combined.read(f"lane-{ordinal:02d}.RESULT.json"))
            if (
                result["identity"] != EXPECTED_537_IDENTITY
                or result["execution_key"] != EXPECTED_537_KEY
                or result["lane_ordinal"] != ordinal
                or result["status"]
                != "AUTHENTIC_INDEX537_FIRST_TAIL_CHECK_COMPLETE_HOLD"
            ):
                raise SystemExit(f"#6957 lane {ordinal} identity differs")
            records.append(
                {
                    "ordinal": ordinal,
                    "stem": result["stem"],
                    "compact_bytes": result["checkpoint_compact_bytes"],
                    "raw_bytes": result["checkpoint_raw_bytes"],
                }
            )
    return final, records


def _project(source, current):
    if current < source:
        raise SystemExit("checkpoint byte trend is negative")
    increment = _ceil_div((current - source) * TARGET_SPAN, SOURCE_SPAN)
    return current + increment


def audit():
    result_256, records_256 = _load_256()
    result_537, records_537 = _load_537()
    lanes = []
    for first, second in zip(records_256, records_537, strict=True):
        if first["ordinal"] != second["ordinal"] or first["stem"] != second["stem"]:
            raise SystemExit("index256/index537 lane ordering differs")
        projected_compact = _project(first["compact_bytes"], second["compact_bytes"])
        projected_raw = _project(first["raw_bytes"], second["raw_bytes"])
        lanes.append(
            {
                "ordinal": first["ordinal"],
                "stem": first["stem"],
                "index256_compact_bytes": first["compact_bytes"],
                "index537_compact_bytes": second["compact_bytes"],
                "index1159_projected_compact_bytes": projected_compact,
                "index1159_projected_compact_cursor_headroom_bytes": (
                    COMPACT_CURSOR_CAP_BYTES - projected_compact
                ),
                "index256_raw_bytes": first["raw_bytes"],
                "index537_raw_bytes": second["raw_bytes"],
                "index1159_projected_raw_bytes": projected_raw,
                "index1159_projected_raw_cursor_headroom_bytes": (
                    RAW_CURSOR_CAP_BYTES - projected_raw
                ),
            }
        )
    projected_compact_total = sum(
        record["index1159_projected_compact_bytes"] for record in lanes
    )
    projected_raw_total = sum(
        record["index1159_projected_raw_bytes"] for record in lanes
    )
    return {
        "identity": "hcsn-n256-index1159-resource-projection-20261122-c6bc-v1",
        "status": "INDEX1159_RESOURCE_PROJECTION_HOLD",
        "inputs": {
            "index256_pr": 6948,
            "index256_result_identity": result_256["identity"],
            "index256_compact_total_bytes": result_256["compact_total_bytes"],
            "index256_raw_total_bytes": result_256["raw_total_bytes"],
            "index537_pr": 6957,
            "index537_source_sha": EXPECTED_537_SOURCE,
            "index537_run": EXPECTED_537_RUN,
            "index537_collector_sha256": EXPECTED_537_COLLECTOR,
            "index537_compact_total_bytes": result_537["compact_checkpoint_bytes"],
            "index537_summed_wall_seconds": result_537["cost"]["summed_wall_seconds"],
            "index537_summed_cpu_seconds": result_537["cost"]["summed_cpu_seconds"],
        },
        "projection": {
            "kind": "two_point_integer_ceil_secant_diagnostic",
            "source_indices": [INDEX_256, INDEX_537],
            "target_index": INDEX_1159,
            "source_span": SOURCE_SPAN,
            "target_span": TARGET_SPAN,
            "formula": "b537 + ceil((b537 - b256) * 622 / 281)",
            "aggregate_cap_bytes": AGGREGATE_CAP_BYTES,
            "compact_cursor_cap_bytes": COMPACT_CURSOR_CAP_BYTES,
            "raw_cursor_cap_bytes": RAW_CURSOR_CAP_BYTES,
            "index1159_projected_compact_total_bytes": projected_compact_total,
            "index1159_projected_compact_aggregate_headroom_bytes": (
                AGGREGATE_CAP_BYTES - projected_compact_total
            ),
            "index1159_projected_compact_aggregate_over_cap_bytes": max(
                0, projected_compact_total - AGGREGATE_CAP_BYTES
            ),
            "index1159_projected_maximum_compact_cursor_bytes": max(
                record["index1159_projected_compact_bytes"] for record in lanes
            ),
            "index1159_projected_raw_total_bytes": projected_raw_total,
            "index1159_projected_maximum_raw_cursor_bytes": max(
                record["index1159_projected_raw_bytes"] for record in lanes
            ),
        },
        "lanes": lanes,
        "work": {
            "archive_restores": 1,
            "source_result_reads": 20,
            "integer_byte_projections": 20,
            "checkpoint_decodes": 0,
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
            "projection_complete": True,
            "projection_is_resource_admission": False,
            "actual_index1159_checkpoint_profile_complete": False,
            "actual_index1159_recurrence_cost_profile_complete": False,
            "actual_index1159_allocation_frozen": False,
            "tail_termination_closed": False,
            "n256_qualified": False,
            "all_closed": False,
        },
        "interpretation": (
            "The exact two-point secant diagnostic projects aggregate compact bytes "
            "above the existing 64 MiB cap while each projected cursor remains below "
            "its current individual cap. Compression and cancellation are nonlinear, "
            "so the projection is neither a lower bound, an upper bound, a monotonicity "
            "proof, a resource allocation, nor authorization to execute index1159."
        ),
        "historical_state": {
            "pr6901": "UNKNOWN",
            "pr6939": "RED",
            "pr6942": "RED_TIMEOUT_COMPLETED_ACTIONS_UNKNOWN",
            "pr6950": "RED",
            "hpca": "NoUpdate_EXTERNAL_CUSTODY_OPEN",
            "c2_full_replay_completed_fits": 0,
            "global": "HOLD_NOUPDATE",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-expected", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(audit(), indent=2, sort_keys=True) + "\n"
    if args.verify_expected is not None and args.verify_expected.read_text() != encoded:
        raise SystemExit("committed audit result differs")
    print(encoded, end="")


if __name__ == "__main__":
    main()
