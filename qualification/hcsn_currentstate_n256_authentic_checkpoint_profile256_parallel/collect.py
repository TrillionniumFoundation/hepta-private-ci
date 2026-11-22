"""Collect ten lane artifacts and enforce unchanged cursor and aggregate caps."""

import hashlib
import json
import os
from pathlib import Path
import shutil

from .lane import EXECUTION_KEY, IDENTITY, MAX_CURSOR_BYTES


HERE = Path(__file__).resolve().parent
INPUT = HERE / "COLLECTED_LANES"
OUTPUT = HERE / "FINAL_OUTPUT"
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
        checkpoint = result_path.parent / result["file"]
        if (
            result["identity"] != IDENTITY
            or result["execution_key"] != EXECUTION_KEY
            or result["lane_ordinal"] != ordinal
            or not checkpoint.is_file()
        ):
            failures.append(f"lane {ordinal}: identity or file mismatch")
            continue
        raw = checkpoint.read_bytes()
        if (
            len(raw) != result["bytes"]
            or len(raw) > MAX_CURSOR_BYTES
            or _sha256(raw) != result["sha256"]
        ):
            failures.append(f"lane {ordinal}: checkpoint digest or cap mismatch")
            continue
        shutil.copyfile(checkpoint, OUTPUT / result["file"])
        shutil.copyfile(result_path, OUTPUT / f"lane-{ordinal:02d}.RESULT.json")
        progress = result_path.parent / "PROGRESS.jsonl"
        if progress.is_file():
            shutil.copyfile(progress, OUTPUT / f"lane-{ordinal:02d}.PROGRESS.jsonl")
        results.append(result)
    aggregate = sum(item["bytes"] for item in results)
    final = {
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "status": (
            "AUTHENTIC_INDEX256_PARALLEL_RESOURCE_PROFILE_ONLY_HOLD"
            if not failures and len(results) == 10 and aggregate <= MAX_AGGREGATE_BYTES
            else "RED_INCOMPLETE_OR_CAP_EXCEEDED"
        ),
        "completed_lanes": len(results),
        "failures": failures,
        "cursor_output_bytes": aggregate,
        "checkpoints": [
            {
                "lane_ordinal": item["lane_ordinal"],
                "lane": item["lane"],
                "file": item["file"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in results
        ],
        "consumed_predecessor": {
            "pr": 6942,
            "run": 44990316452,
            "job": 137109720919,
            "conclusion": "cancelled",
            "successful_outputs": 0,
            "completed_row_actions": "UNKNOWN",
            "profile_wall_lower_bound_seconds": 1797.679758,
        },
        "scope": {
            "resource_gate_closed": False,
            "tail_termination_closed": False,
            "provider_completion": False,
            "unique_rounding_closed": False,
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
    if aggregate > MAX_AGGREGATE_BYTES:
        final["failures"].append("64 MiB aggregate cap exceeded")
    (OUTPUT / "RESULT.json").write_text(
        json.dumps(final, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(final, sort_keys=True))
    if final["status"].startswith("RED_"):
        raise SystemExit("parallel resource profile did not close")


if __name__ == "__main__":
    main()
