"""Zero-numerical readback for the immutable #6944 parallel artifact."""

from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile


HERE = Path(__file__).resolve().parent
READBACK = HERE / "READBACK.json"
PARTS = HERE / "PARTS.sha256"
SCHEMA = "hcsn-n256-authentic-index256-checkpoint-profile-v1"
LANE_WORK = {
    "cold_extension_row_actions": 128,
    "dynamic_steps": 0,
    "exponential_actions": 0,
    "index128_source_replay_row_actions": 192,
    "index32_source_replay_row_actions": 60,
    "index_two_relation_recomputations": 2,
    "optimizer_steps": 0,
    "provider_outputs": 0,
    "tail_checks": 0,
    "torch_calls": 0,
    "total_row_actions": 508,
    "warm_extension_row_actions": 128,
}
PROGRESS_COUNTS = Counter(
    {
        "admitted": 1,
        "inputs_verified": 1,
        "warm_index128_verified": 1,
        "warm_index256_encoded": 1,
        "cold_index128_verified": 1,
        "extension_progress": 32,
        "lane_complete": 1,
    }
)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _read_original(expected):
    records = []
    raw_parts = []
    for line in PARTS.read_text().splitlines():
        digest, byte_count, name = line.split()
        raw = (HERE / name).read_bytes()
        if len(raw) != int(byte_count) or _sha256(raw) != digest:
            raise SystemExit(f"original part mismatch: {name}")
        records.append((name, int(byte_count), digest))
        raw_parts.append(raw)
    if len(records) != expected["part_count"]:
        raise SystemExit("original part count mismatch")
    if [name for name, _, _ in records] != [
        f"ORIGINAL.zip.part{index:03d}" for index in range(len(records))
    ]:
        raise SystemExit("original parts are not contiguous and ordered")
    raw = b"".join(raw_parts)
    if len(raw) != expected["original_zip_bytes"]:
        raise SystemExit("original ZIP byte count mismatch")
    if _sha256(raw) != expected["original_zip_sha256"]:
        raise SystemExit("original ZIP digest mismatch")
    return raw


def _check_progress(archive, ordinal):
    name = f"lane-{ordinal:02d}.PROGRESS.jsonl"
    rows = [json.loads(line) for line in archive.read(name).splitlines()]
    if len(rows) != 38 or Counter(row["event"] for row in rows) != PROGRESS_COUNTS:
        raise SystemExit(f"lane {ordinal} progress ledger mismatch")
    if rows[0]["event"] != "admitted" or rows[-1]["event"] != "lane_complete":
        raise SystemExit(f"lane {ordinal} progress endpoints mismatch")
    if rows[0]["lane_ordinal"] != ordinal:
        raise SystemExit(f"lane {ordinal} admission identity mismatch")
    progress = [row for row in rows if row["event"] == "extension_progress"]
    for phase in ("warm", "cold"):
        indices = [row["index"] for row in progress if row["phase"] == phase]
        if indices != list(range(136, 257, 8)):
            raise SystemExit(f"lane {ordinal} {phase} progress mismatch")
    monotonic = [row["monotonic_seconds"] for row in rows]
    if monotonic != sorted(monotonic):
        raise SystemExit(f"lane {ordinal} progress clock regressed")


def _check_checkpoint(archive, result_item, lane_result, ordinal):
    payload = archive.read(result_item["file"])
    if len(payload) != result_item["bytes"] or _sha256(payload) != result_item["sha256"]:
        raise SystemExit(f"lane {ordinal} checkpoint identity mismatch")
    if lane_result["file"] != result_item["file"]:
        raise SystemExit(f"lane {ordinal} result filename mismatch")
    if lane_result["bytes"] != len(payload) or lane_result["sha256"] != _sha256(payload):
        raise SystemExit(f"lane {ordinal} result checkpoint mismatch")
    envelope = json.loads(payload)
    if _canonical(envelope) != payload:
        raise SystemExit(f"lane {ordinal} checkpoint is not canonical JSON")
    if set(envelope) != {"body", "body_sha256"}:
        raise SystemExit(f"lane {ordinal} checkpoint envelope mismatch")
    body = envelope["body"]
    if _sha256(_canonical(body)) != envelope["body_sha256"]:
        raise SystemExit(f"lane {ordinal} checkpoint body digest mismatch")
    if body["schema"] != SCHEMA or body["included_index"] != 256:
        raise SystemExit(f"lane {ordinal} checkpoint schema/index mismatch")
    if body["lane"] != result_item["lane"] or lane_result["lane"] != body["lane"]:
        raise SystemExit(f"lane {ordinal} checkpoint lane mismatch")
    if not result_item["file"].endswith(".index256.checkpoint.json"):
        raise SystemExit(f"lane {ordinal} checkpoint filename mismatch")
    for key in ("source_payload_sha256", "parent_payload_sha256"):
        if not HEX64.fullmatch(body[key]):
            raise SystemExit(f"lane {ordinal} {key} malformed")


def main():
    expected = json.loads(READBACK.read_text())
    raw = _read_original(expected)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() is not None:
            raise SystemExit("original ZIP CRC failure")
        if len(archive.namelist()) != expected["members"]:
            raise SystemExit("original ZIP member count mismatch")
        if sum(item.file_size for item in archive.infolist()) != expected[
            "uncompressed_bytes"
        ]:
            raise SystemExit("original ZIP uncompressed byte count mismatch")

        result = json.loads(archive.read("RESULT.json"))
        if result["execution_key"] != expected["execution_key"]:
            raise SystemExit("execution key mismatch")
        if result["identity"] != (
            "hcsn-n256-authentic-checkpoint-profile256-parallel-20261122-c6bc-v1"
        ):
            raise SystemExit("source identity mismatch")
        if result["status"] != "AUTHENTIC_INDEX256_PARALLEL_RESOURCE_PROFILE_ONLY_HOLD":
            raise SystemExit("source status mismatch")
        if result["completed_lanes"] != 10 or result["failures"] != []:
            raise SystemExit("lane completion ledger mismatch")
        if result["cursor_output_bytes"] != 62_877_713:
            raise SystemExit("cursor output byte ledger mismatch")
        if result["consumed_predecessor"] != {
            "completed_row_actions": "UNKNOWN",
            "conclusion": "cancelled",
            "job": 137109720919,
            "pr": 6942,
            "profile_wall_lower_bound_seconds": 1797.679758,
            "run": 44990316452,
            "successful_outputs": 0,
        }:
            raise SystemExit("consumed predecessor ledger mismatch")
        if result["scope"] != {
            "all_closed": False,
            "arbitrary_history_resume": False,
            "c2_full_replay_completed_fits": 0,
            "cause_of_6901_red": "UNKNOWN",
            "hpca_status": "NoUpdate",
            "n256_qualified": False,
            "predecessor_6939": "RED_DECIMAL_INTEGER_DIGIT_LIMIT",
            "predecessor_6942": "RED_TIMEOUT",
            "production_adoption": False,
            "provider_completion": False,
            "resource_gate_closed": False,
            "tail_termination_closed": False,
            "unique_rounding_closed": False,
        }:
            raise SystemExit("fail-closed scope mismatch")
        if len(result["checkpoints"]) != 10:
            raise SystemExit("checkpoint count mismatch")

        wall = []
        cpu = []
        rss = []
        total_bytes = 0
        seen_files = set()
        for ordinal, item in enumerate(result["checkpoints"]):
            if item["lane_ordinal"] != ordinal or item["file"] in seen_files:
                raise SystemExit(f"lane {ordinal} order/uniqueness mismatch")
            seen_files.add(item["file"])
            lane_result = json.loads(archive.read(f"lane-{ordinal:02d}.RESULT.json"))
            if lane_result["lane_ordinal"] != ordinal:
                raise SystemExit(f"lane {ordinal} result ordinal mismatch")
            if lane_result["execution_key"] != expected["execution_key"]:
                raise SystemExit(f"lane {ordinal} execution key mismatch")
            if lane_result["status"] != "AUTHENTIC_INDEX256_LANE_RESOURCE_PROFILE_ONLY_HOLD":
                raise SystemExit(f"lane {ordinal} status mismatch")
            if lane_result["work"] != LANE_WORK:
                raise SystemExit(f"lane {ordinal} work ledger mismatch")
            host = lane_result["host"]
            if host["github_run_id"] != str(expected["workflow"]["run_id"]):
                raise SystemExit(f"lane {ordinal} run identity mismatch")
            if host["github_run_attempt"] != "1":
                raise SystemExit(f"lane {ordinal} run attempt mismatch")
            if host["github_sha"] != expected["workflow"]["host_merge_sha"]:
                raise SystemExit(f"lane {ordinal} host merge SHA mismatch")
            _check_checkpoint(archive, item, lane_result, ordinal)
            _check_progress(archive, ordinal)
            total_bytes += item["bytes"]
            wall.append(lane_result["cost"]["wall_seconds"])
            cpu.append(lane_result["cost"]["cpu_seconds"])
            rss.append(lane_result["cost"]["max_rss_kib"])

        if total_bytes != result["cursor_output_bytes"]:
            raise SystemExit("checkpoint aggregate byte mismatch")
        if total_bytes > 64 * 1024 * 1024 or max(
            item["bytes"] for item in result["checkpoints"]
        ) > 8 * 1024 * 1024:
            raise SystemExit("bounded resource cap exceeded")
        observed_cost = {
            "cpu_seconds_max": max(cpu),
            "cpu_seconds_min": min(cpu),
            "cpu_seconds_sum": sum(cpu),
            "max_rss_kib": max(rss),
            "wall_seconds_max": max(wall),
            "wall_seconds_min": min(wall),
            "wall_seconds_sum": sum(wall),
        }
        for key, value in expected["cost"].items():
            if not math.isclose(observed_cost[key], value, rel_tol=0.0, abs_tol=1e-12):
                raise SystemExit(f"aggregate cost mismatch: {key}")
    print("PASS_6944_AUTHENTIC_INDEX256_PARALLEL_ZERO_NUMERICAL_READBACK")


if __name__ == "__main__":
    main()
