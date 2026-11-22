"""Run and collect the admitted ten-lane continuation under one owner."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .admission import admit_runtime
from .lane import IDENTITY
from .output_validation import validate_lane_result


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _run_lane(ordinal, root):
    environment = dict(os.environ)
    environment["HCSN_LANE_ORDINAL"] = str(ordinal)
    environment["HCSN_OUTPUT_ROOT"] = str(root)
    completed = subprocess.run(
        [sys.executable, "-m", "qualification.hcsn_currentstate_n256_tail1159_intent.lane"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    (root / f"lane-{ordinal:02d}.stdout.log").write_text(completed.stdout)
    (root / f"lane-{ordinal:02d}.stderr.log").write_text(completed.stderr)
    return ordinal, completed.returncode


def main():
    request = admit_runtime()
    output = Path(os.environ["HCSN_OUTPUT_ROOT"])
    if output.exists():
        raise SystemExit("output root already exists")
    output.mkdir(parents=True)
    concurrency = request["runtime_admission"]["concurrency"]
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        statuses = list(executor.map(lambda ordinal: _run_lane(ordinal, output), range(10)))
    failures = [ordinal for ordinal, returncode in statuses if returncode != 0]
    results = []
    for ordinal in range(10):
        path = output / f"lane-{ordinal:02d}" / "RESULT.json"
        try:
            results.append(validate_lane_result(path, ordinal, request, IDENTITY))
        except SystemExit as error:
            print(f"lane {ordinal:02d} output rejected: {error}", file=sys.stderr)
            failures.append(ordinal)
        if not path.exists() and ordinal not in failures:
            failures.append(ordinal)
    stems = [item["stem"] for item in results]
    if len(stems) != len(set(stems)):
        failures.append("duplicate_lane_stem")
    compact_total = sum(item["checkpoint_compact_bytes"] for item in results)
    caps = request["checkpoint_caps"]
    for item in results:
        if (
            item["checkpoint_compact_bytes"] > caps["per_cursor_compact_bytes"]
            or item["checkpoint_raw_bytes"] > caps["per_cursor_raw_bytes"]
        ):
            failures.append(item["lane_ordinal"])
    if compact_total > caps["aggregate_compact_bytes"]:
        failures.append("aggregate_compact_cap")
    failures = sorted(set(failures), key=str)
    complete = not failures and len(results) == 10
    final = {
        "identity": IDENTITY,
        "execution_key": request["execution_key"],
        "status": "COMPLETE_HOLD" if complete else "RED_INCOMPLETE_OR_CAP_EXCEEDED",
        "completed_lanes": len(results),
        "failures": failures,
        "compact_checkpoint_bytes": compact_total,
        "all_coordinates_unique_lanes": sum(
            item["tail"]["all_coordinates_unique"] for item in results
        ),
        "total_unique_coordinates": sum(
            item["tail"]["unique_coordinate_count"] for item in results
        ),
        "total_coordinates": sum(item["tail"]["coordinate_count"] for item in results),
        "work": {
            "recurrence_row_actions": sum(
                item["work"]["recurrence_row_actions"] for item in results
            ),
            "tail_checks": sum(item["work"]["tail_checks"] for item in results),
            "rounding_calls": sum(item["work"]["rounding_calls"] for item in results),
            "collector_checkpoint_decodes": len(results),
            "provider_calls": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "tail_termination_closed": complete
            and all(item["tail"]["all_coordinates_unique"] for item in results),
            "n256_qualified": False,
            "production_adoption": False,
            "all_closed": False,
        },
    }
    encoded = json.dumps(final, indent=2, sort_keys=True) + "\n"
    (output / "FINAL_RESULT.json").write_text(encoded)
    (output / "FINAL_RESULT.sha256").write_text(_sha256(encoded.encode()) + "\n")
    print(encoded, end="")
    if not complete:
        raise SystemExit("index1159 continuation is incomplete")


if __name__ == "__main__":
    main()
