"""Run and collect the admitted ten-lane continuation under one owner."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
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


def _process_group_alive(process_group):
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_owned_process_group(process, grace_seconds):
    """Terminate the POSIX session created for exactly one owned child."""

    process_group = process.pid
    proof = {"sigterm_sent": False, "sigkill_sent": False}
    if _process_group_alive(process_group):
        try:
            os.killpg(process_group, signal.SIGTERM)
            proof["sigterm_sent"] = True
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    if _process_group_alive(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
            proof["sigkill_sent"] = True
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + grace_seconds
    while _process_group_alive(process_group) and time.monotonic() < deadline:
        time.sleep(0.01)
    proof["process_group_alive_after_cleanup"] = _process_group_alive(process_group)
    return proof


def _run_command(
    ordinal,
    argv,
    environment,
    root,
    log_caps,
    timeout_seconds,
    termination_grace_seconds,
):
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise SystemExit("lane timeout is invalid")
    if (
        not isinstance(termination_grace_seconds, (int, float))
        or isinstance(termination_grace_seconds, bool)
        or not math.isfinite(termination_grace_seconds)
        or termination_grace_seconds <= 0
    ):
        raise SystemExit("lane termination grace is invalid")
    environment = dict(environment)
    process = subprocess.Popen(
        argv,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_seconds
    overflow = threading.Event()
    timed_out = False
    residual_descendants = False
    termination = {
        "sigterm_sent": False,
        "sigkill_sent": False,
        "process_group_alive_after_cleanup": False,
    }
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
                termination = _terminate_owned_process_group(
                    process, termination_grace_seconds
                )
                break
            if time.monotonic() >= deadline:
                timed_out = True
                termination = _terminate_owned_process_group(
                    process, termination_grace_seconds
                )
                break
        returncode = process.wait()
        if _process_group_alive(process.pid):
            residual_descendants = True
            termination = _terminate_owned_process_group(
                process, termination_grace_seconds
            )
        stdout_bytes = stdout.result()
        stderr_bytes = stderr.result()
    process.stdout.close()
    process.stderr.close()
    return {
        "lane_ordinal": ordinal,
        "returncode": returncode,
        "log_overflow": overflow.is_set(),
        "timed_out": timed_out,
        "residual_descendants_detected": residual_descendants,
        **termination,
        "stdout_produced_bytes": stdout_bytes,
        "stderr_produced_bytes": stderr_bytes,
    }


def _run_lane(ordinal, root, log_caps, timeout_seconds, termination_grace_seconds):
    environment = dict(os.environ)
    environment["HCSN_LANE_ORDINAL"] = str(ordinal)
    environment["HCSN_OUTPUT_ROOT"] = str(root)
    return _run_command(
        ordinal,
        [
            sys.executable,
            "-m",
            "qualification.hcsn_currentstate_n256_tail1159_intent.lane",
        ],
        environment,
        root,
        log_caps,
        timeout_seconds,
        termination_grace_seconds,
    )


def _lane_completed_cleanly(status):
    return (
        status["returncode"] == 0
        and not status["log_overflow"]
        and not status["timed_out"]
        and not status["residual_descendants_detected"]
        and not status["process_group_alive_after_cleanup"]
    )


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
    process_statuses = []
    for status in sorted(statuses, key=lambda item: item["lane_ordinal"]):
        record = dict(status)
        record["stdout_retained_bytes"] = min(
            status["stdout_produced_bytes"], log_caps["stdout_bytes"]
        )
        record["stderr_retained_bytes"] = min(
            status["stderr_produced_bytes"], log_caps["stderr_bytes"]
        )
        process_statuses.append(record)
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
    timeout_seconds = request["lane_command_timeout_seconds"]
    termination_grace_seconds = request["termination_grace_seconds"]
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        statuses = list(
            executor.map(
                lambda ordinal: _run_lane(
                    ordinal,
                    output,
                    log_caps,
                    timeout_seconds,
                    termination_grace_seconds,
                ),
                range(10),
            )
        )
    failures = [
        status["lane_ordinal"]
        for status in statuses
        if not _lane_completed_cleanly(status)
    ]
    status_by_ordinal = {item["lane_ordinal"]: item for item in statuses}
    results = []
    for ordinal in range(10):
        path = output / f"lane-{ordinal:02d}" / "RESULT.json"
        if not _lane_completed_cleanly(status_by_ordinal[ordinal]):
            continue
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
            "stdout_produced_bytes": sum(
                item["stdout_produced_bytes"] for item in statuses
            ),
            "stdout_retained_bytes": sum(
                min(item["stdout_produced_bytes"], log_caps["stdout_bytes"])
                for item in statuses
            ),
            "stderr_produced_bytes": sum(
                item["stderr_produced_bytes"] for item in statuses
            ),
            "stderr_retained_bytes": sum(
                min(item["stderr_produced_bytes"], log_caps["stderr_bytes"])
                for item in statuses
            ),
            "per_stream_caps": log_caps,
            "overflow_lanes": [
                item["lane_ordinal"] for item in statuses if item["log_overflow"]
            ],
            "timed_out_lanes": [
                item["lane_ordinal"] for item in statuses if item["timed_out"]
            ],
            "residual_descendant_lanes": [
                item["lane_ordinal"]
                for item in statuses
                if item["residual_descendants_detected"]
            ],
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
            "semantic_checkpoint_parses": len(results),
            "canonical_raw_reencodes": len(results),
            "provider_calls": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "candidate_tail_output_all_unique": complete
            and all(item["tail"]["all_coordinates_unique"] for item in results),
            "tail_termination_closed": False,
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
