"""Run and collect the admitted ten-lane continuation under one owner."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time

from .admission import admit_runtime
from .lane import IDENTITY
from .output_validation import validate_lane_result


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _drain_bounded(stream, path, byte_cap, overflow):
    if not isinstance(byte_cap, int) or isinstance(byte_cap, bool) or byte_cap < 1:
        raise SystemExit("lane log byte cap is invalid")
    total = 0
    written = 0
    with path.open("xb") as sink:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            total += len(chunk)
            room = byte_cap - written
            if room > 0:
                accepted = chunk[:room]
                sink.write(accepted)
                written += len(accepted)
            if total > byte_cap:
                overflow.set()
    return total


def _run_lane(ordinal, root, log_caps):
    environment = dict(os.environ)
    environment["HCSN_LANE_ORDINAL"] = str(ordinal)
    environment["HCSN_OUTPUT_ROOT"] = str(root)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "qualification.hcsn_currentstate_n256_tail1159_intent.lane",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    overflow = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as drains:
        stdout = drains.submit(
            _drain_bounded,
            process.stdout,
            root / f"lane-{ordinal:02d}.stdout.log",
            log_caps["stdout_bytes"],
            overflow,
        )
        stderr = drains.submit(
            _drain_bounded,
            process.stderr,
            root / f"lane-{ordinal:02d}.stderr.log",
            log_caps["stderr_bytes"],
            overflow,
        )
        while process.poll() is None:
            if overflow.wait(0.05):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
        returncode = process.wait()
        stdout_bytes = stdout.result()
        stderr_bytes = stderr.result()
    return ordinal, returncode, overflow.is_set(), stdout_bytes, stderr_bytes


def _finite_nonnegative(value, label):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise SystemExit(f"{label} is not finite and nonnegative")
    return value


def _cost_ledger(results, statuses, log_caps, collector_cost):
    """Preserve per-process costs without treating concurrent peaks as additive."""

    lane_costs = []
    for result in sorted(results, key=lambda item: item["lane_ordinal"]):
        cost = result["cost"]
        lane_costs.append(
            {
                "lane_ordinal": result["lane_ordinal"],
                "wall_seconds": _finite_nonnegative(
                    cost["wall_seconds"], "lane wall seconds"
                ),
                "cpu_seconds": _finite_nonnegative(
                    cost["cpu_seconds"], "lane CPU seconds"
                ),
                "max_rss_kib": cost["max_rss_kib"],
            }
        )
    process_statuses = [
        {
            "lane_ordinal": ordinal,
            "returncode": returncode,
            "log_overflow": overflow,
            "stdout_produced_bytes": stdout_bytes,
            "stdout_retained_bytes": min(stdout_bytes, log_caps["stdout_bytes"]),
            "stderr_produced_bytes": stderr_bytes,
            "stderr_retained_bytes": min(stderr_bytes, log_caps["stderr_bytes"]),
        }
        for ordinal, returncode, overflow, stdout_bytes, stderr_bytes in sorted(statuses)
    ]
    for field in ("wall_seconds", "cpu_seconds"):
        _finite_nonnegative(collector_cost[field], f"collector {field}")
    if (
        not isinstance(collector_cost["max_rss_kib"], int)
        or isinstance(collector_cost["max_rss_kib"], bool)
        or collector_cost["max_rss_kib"] < 1
    ):
        raise SystemExit("collector max RSS is not a positive integer")
    return {
        "collector": collector_cost,
        "validated_lane_costs": lane_costs,
        "validated_lane_wall_seconds_sum": sum(
            item["wall_seconds"] for item in lane_costs
        ),
        "validated_lane_cpu_seconds_sum": sum(
            item["cpu_seconds"] for item in lane_costs
        ),
        "validated_lane_max_rss_kib_max": max(
            (item["max_rss_kib"] for item in lane_costs), default=0
        ),
        "process_statuses": process_statuses,
    }


def main():
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    request = admit_runtime()
    output = Path(os.environ["HCSN_OUTPUT_ROOT"])
    if output.exists():
        raise SystemExit("output root already exists")
    output.mkdir(parents=True)
    concurrency = request["runtime_admission"]["concurrency"]
    log_caps = request["lane_log_caps"]
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        statuses = list(
            executor.map(
                lambda ordinal: _run_lane(ordinal, output, log_caps), range(10)
            )
        )
    failures = [
        ordinal
        for ordinal, returncode, overflow, _, _ in statuses
        if returncode != 0 or overflow
    ]
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
    collector_usage = resource.getrusage(resource.RUSAGE_SELF)
    cost = _cost_ledger(
        results,
        statuses,
        log_caps,
        {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": collector_usage.ru_maxrss,
        },
    )
    final = {
        "identity": IDENTITY,
        "execution_key": request["execution_key"],
        "status": "COMPLETE_HOLD" if complete else "RED_INCOMPLETE_OR_CAP_EXCEEDED",
        "completed_lanes": len(results),
        "failures": failures,
        "compact_checkpoint_bytes": compact_total,
        "logs": {
            "stdout_produced_bytes": sum(item[3] for item in statuses),
            "stdout_retained_bytes": sum(
                min(item[3], log_caps["stdout_bytes"]) for item in statuses
            ),
            "stderr_produced_bytes": sum(item[4] for item in statuses),
            "stderr_retained_bytes": sum(
                min(item[4], log_caps["stderr_bytes"]) for item in statuses
            ),
            "per_stream_caps": log_caps,
            "overflow_lanes": [item[0] for item in statuses if item[2]],
        },
        "cost": cost,
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
