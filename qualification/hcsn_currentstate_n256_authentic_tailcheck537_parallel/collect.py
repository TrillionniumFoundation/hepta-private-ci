"""Collect ten complete index537 first-tail-check lane originals."""

import hashlib
import json
import os
from pathlib import Path
import shutil

from .lane import EXECUTION_KEY, IDENTITY


HERE = Path(__file__).resolve().parent
INPUT = HERE / "COLLECTED_LANES"
OUTPUT = HERE / "FINAL_OUTPUT"
MAX_CURSOR_BYTES = 8_388_608
MAX_RAW_BYTES = 33_554_432
MAX_AGGREGATE_BYTES = 67_108_864


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before lane artifact read")
    if OUTPUT.exists():
        raise SystemExit("final output already exists")
    OUTPUT.mkdir()
    results = []
    failures = []
    for ordinal in range(10):
        candidates = list(INPUT.rglob(f"lane-{ordinal:02d}/RESULT.json"))
        if len(candidates) != 1:
            failures.append(f"lane {ordinal}: result count {len(candidates)}")
            continue
        result_path = candidates[0]
        result = json.loads(result_path.read_text())
        checkpoint = result_path.parent / result["checkpoint_file"]
        tail = result_path.parent / result["tail_file"]
        if (
            result["identity"] != IDENTITY
            or result["execution_key"] != EXECUTION_KEY
            or result["lane_ordinal"] != ordinal
            or not checkpoint.is_file()
            or not tail.is_file()
        ):
            failures.append(f"lane {ordinal}: identity or file mismatch")
            continue
        checkpoint_raw = checkpoint.read_bytes()
        tail_raw = tail.read_bytes()
        if (
            len(checkpoint_raw) != result["checkpoint_compact_bytes"]
            or len(checkpoint_raw) > MAX_CURSOR_BYTES
            or result["checkpoint_raw_bytes"] > MAX_RAW_BYTES
            or _sha256(checkpoint_raw) != result["checkpoint_compact_sha256"]
            or _sha256(tail_raw) != result["tail_sha256"]
            or result["work"]["recurrence_row_actions"] != 281
            or result["work"]["tail_checks"] != 1
        ):
            failures.append(f"lane {ordinal}: checkpoint, tail, cap, or work mismatch")
            continue
        shutil.copyfile(checkpoint, OUTPUT / result["checkpoint_file"])
        shutil.copyfile(tail, OUTPUT / f"lane-{ordinal:02d}.TAIL.json")
        shutil.copyfile(result_path, OUTPUT / f"lane-{ordinal:02d}.RESULT.json")
        progress = result_path.parent / "PROGRESS.jsonl"
        if progress.is_file():
            shutil.copyfile(progress, OUTPUT / f"lane-{ordinal:02d}.PROGRESS.jsonl")
        results.append(result)
    aggregate = sum(item["checkpoint_compact_bytes"] for item in results)
    if aggregate > MAX_AGGREGATE_BYTES:
        failures.append("64 MiB aggregate compact checkpoint cap exceeded")
    complete = not failures and len(results) == 10
    unique_lanes = sum(item["tail"]["all_coordinates_unique"] for item in results)
    final = {
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "status": (
            "AUTHENTIC_INDEX537_FIRST_TAIL_CHECK_COMPLETE_HOLD"
            if complete
            else "RED_INCOMPLETE_OR_CAP_EXCEEDED"
        ),
        "completed_lanes": len(results),
        "failures": failures,
        "compact_checkpoint_bytes": aggregate,
        "aggregate_cap_bytes": MAX_AGGREGATE_BYTES,
        "aggregate_headroom_bytes": MAX_AGGREGATE_BYTES - aggregate,
        "all_coordinates_unique_lanes": unique_lanes,
        "nonunique_lanes": len(results) - unique_lanes,
        "total_unique_coordinates": sum(
            item["tail"]["unique_coordinate_count"] for item in results
        ),
        "total_coordinates": sum(item["tail"]["coordinate_count"] for item in results),
        "work": {
            "index256_compact_decodes": sum(
                item["work"]["index256_compact_decodes"] for item in results
            ),
            "recurrence_row_actions": sum(
                item["work"]["recurrence_row_actions"] for item in results
            ),
            "tail_checks": sum(item["work"]["tail_checks"] for item in results),
            "rounding_calls": sum(
                item["work"]["rounding_calls"] for item in results
            ),
            "index537_compact_encodes": sum(
                item["work"]["index537_compact_encodes"] for item in results
            ),
            "index537_compact_decodes": sum(
                item["work"]["index537_compact_decodes"] for item in results
            ),
            "provider_outputs": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "cost": {
            "summed_wall_seconds": sum(
                item["cost"]["wall_seconds"] for item in results
            ),
            "summed_cpu_seconds": sum(
                item["cost"]["cpu_seconds"] for item in results
            ),
            "maximum_rss_kib": max(
                (item["cost"]["max_rss_kib"] for item in results), default=0
            ),
        },
        "scope": {
            "first_tail_check_complete": complete,
            "tail_termination_closed": complete and unique_lanes == 10,
            "provider_completion": False,
            "arbitrary_history_resume": False,
            "n256_qualified": False,
            "production_adoption": False,
            "all_closed": False,
            "cause_of_6901_red": "UNKNOWN",
            "predecessor_6939": "RED_DECIMAL_INTEGER_DIGIT_LIMIT",
            "predecessor_6942": "RED_TIMEOUT",
            "c2_full_replay_completed_fits": 0,
            "hpca_status": "NoUpdate",
        },
    }
    (OUTPUT / "RESULT.json").write_text(
        json.dumps(final, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(final, sort_keys=True))
    if not complete:
        raise SystemExit("parallel index537 first-tail stage is incomplete")


if __name__ == "__main__":
    main()
