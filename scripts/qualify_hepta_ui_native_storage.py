#!/usr/bin/env python3
"""Validate exact-SHA ui.native storage evidence and Linux durability syscalls."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

RETURN_VALUE = re.compile(r"\)\s+=\s+(-?\d+)(?:\s|$)")
ROOTED_CALL = re.compile(
    r"^(write|writev|pwrite64|pwritev|pwritev2|fsync|fdatasync)\(\d+<([^>]*)>"
)
RESUMED_CALL = re.compile(r"^<\.\.\. (\w+) resumed>(.*)$")
MINIMUM_PROCESS_SAMPLE_COUNT = 20
OPEN_MEASUREMENT_SCOPE = "fresh-process-os-page-cache-uncontrolled"
HISTORY_BYTES_MEASUREMENT_SCOPE = (
    "serialized-retained-receipts-not-allocator-accounting"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_object(path: Path) -> dict[str, Any]:
    require(
        path.is_file() and not path.is_symlink(),
        f"{path} must be a regular non-symlink file",
    )
    require(
        path.stat().st_size <= 8 * 1024 * 1024, f"{path} JSON exceeds its byte ceiling"
    )
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
    )
    require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, observed in pairs:
        require(key not in value, f"duplicate JSON key: {key}")
        value[key] = observed
    return value


def integer(value: dict[str, Any], key: str) -> int:
    observed = value.get(key)
    require(
        isinstance(observed, int) and not isinstance(observed, bool),
        f"{key} is not an integer",
    )
    return observed


def finite_nonnegative_number(observed: Any, label: str) -> float:
    require(
        isinstance(observed, (int, float)) and not isinstance(observed, bool),
        f"{label} is not numeric",
    )
    try:
        result = float(observed)
    except OverflowError as error:
        raise RuntimeError(f"{label} is not a finite non-negative number") from error
    require(
        math.isfinite(result) and result >= 0.0,
        f"{label} is not a finite non-negative number",
    )
    return result


def number(value: dict[str, Any], key: str) -> float:
    return finite_nonnegative_number(value.get(key), key)


def sampled_percentile(
    value: dict[str, Any], sample_key: str, percentile_key: str, sample_count: int,
    percentile_rank: int = 95,
) -> float:
    samples = value.get(sample_key)
    require(
        isinstance(samples, list) and len(samples) == sample_count,
        f"{sample_key} must contain exactly {sample_count} samples",
    )
    ordered = sorted(
        finite_nonnegative_number(sample, f"{sample_key}[{index}]")
        for index, sample in enumerate(samples)
    )
    nearest_rank = (len(ordered) * percentile_rank + 99) // 100 - 1
    percentile = number(value, percentile_key)
    require(
        percentile == ordered[nearest_rank],
        f"{percentile_key} does not match the nearest-rank p{percentile_rank} of {sample_key}",
    )
    return percentile


def validate_process_observations(
    evidence: dict[str, Any],
    observation_key: str,
    sample_key: str,
    kind: str,
    source_sha: str,
    sample_count: int,
) -> None:
    observations = evidence.get(observation_key)
    require(
        isinstance(observations, list) and len(observations) == sample_count,
        f"{observation_key} must contain exactly {sample_count} process observations",
    )
    pids = set()
    retained_bytes = []
    for index, observation in enumerate(observations):
        require(
            isinstance(observation, dict),
            f"{observation_key}[{index}] is not an object",
        )
        require(
            observation.get("schema") == "hepta.ui-native-storage-process-sample.v1",
            f"{observation_key}[{index}] process schema mismatch",
        )
        require(
            observation.get("kind") == kind,
            f"{observation_key}[{index}] process kind mismatch",
        )
        require(
            observation.get("sourceSha") == source_sha,
            f"{observation_key}[{index}] process source SHA mismatch",
        )
        pid = integer(observation, "pid")
        require(
            pid > 0 and pid not in pids,
            f"{observation_key} lacks unique positive process IDs",
        )
        pids.add(pid)
        require(
            number(observation, "elapsedMilliseconds") == evidence[sample_key][index],
            f"{observation_key}[{index}] elapsed time does not match its summary sample",
        )
        rss_mib = integer(observation, "peakRssMiB")
        require(
            0 <= rss_mib <= integer(evidence, "peakRssMiB"),
            f"{observation_key}[{index}] peak RSS is negative or exceeds the summary peak",
        )
        if kind == "active-open":
            require(
                integer(observation, "historyPageSize") == 64,
                f"{observation_key}[{index}] history page size mismatch",
            )
            require(
                number(observation, "historyPageMilliseconds")
                == evidence["historyPageSamplesMilliseconds"][index],
                f"{observation_key}[{index}] history latency does not match its summary sample",
            )
            history_bytes = integer(observation, "historyPageRetainedJsonBytes")
            require(
                history_bytes > 0,
                f"{observation_key}[{index}] history retained bytes are not positive",
            )
            retained_bytes.append(history_bytes)
    if retained_bytes:
        require(
            max(retained_bytes) == integer(evidence, "historyPageMaxRetainedJsonBytes"),
            "history page retained-byte summary does not match process observations",
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_traces(
    prefix: Path, storage_root: str
) -> tuple[int, int, list[dict[str, Any]]]:
    traces = sorted(prefix.parent.glob(f"{prefix.name}*"))
    require(traces, f"no strace files matched {prefix}*")
    write_bytes = 0
    sync_calls = 0
    inventory: list[dict[str, Any]] = []
    for trace in traces:
        require(
            trace.is_file() and not trace.is_symlink(),
            f"{trace} must be a regular non-symlink trace",
        )
        inventory.append(
            {
                "path": trace.name,
                "bytes": trace.stat().st_size,
                "sha256": sha256_file(trace),
            }
        )
        pending = None
        for line in trace.read_text(encoding="utf-8", errors="strict").splitlines():
            if "<unfinished ...>" in line:
                require(
                    pending is None, "strace contains overlapping unfinished syscalls"
                )
                pending = line.removesuffix("<unfinished ...>")
                continue
            resumed = RESUMED_CALL.match(line)
            if resumed:
                require(
                    pending is not None,
                    "strace contains a resumed syscall without its entry",
                )
                require(
                    pending.startswith(resumed.group(1) + "("),
                    "strace resumed syscall differs from its entry",
                )
                line = pending + resumed.group(2)
                pending = None
            call = ROOTED_CALL.match(line)
            if call is None:
                continue
            descriptor_path = call.group(2).removesuffix(" (deleted)")
            if descriptor_path != storage_root and not descriptor_path.startswith(
                storage_root.rstrip("/") + "/"
            ):
                continue
            result = RETURN_VALUE.search(line)
            if result is None:
                continue
            returned = int(result.group(1))
            if returned < 0:
                continue
            if call.group(1) in {"write", "writev", "pwrite64", "pwritev", "pwritev2"}:
                write_bytes += returned
            if returned == 0 and call.group(1) in {"fsync", "fdatasync"}:
                sync_calls += 1
        require(
            pending is None or ROOTED_CALL.match(pending) is None,
            "strace ends with an unfinished durable-state syscall",
        )
    require(write_bytes > 0, "strace observed no successful durable-state writes")
    require(sync_calls > 0, "strace observed no successful fsync/fdatasync calls")
    return write_bytes, sync_calls, inventory


def validate_storage(
    budgets_path: Path,
    active_path: Path,
    retired_path: Path,
    trace_prefix: Path,
    source_sha: str,
) -> dict[str, Any]:
    """Revalidate raw storage measurements and return their bound qualification."""
    require(
        len(source_sha) == 40
        and all(character in "0123456789abcdef" for character in source_sha),
        "--source-sha must be a lowercase 40-character Git SHA",
    )
    budgets = load_object(budgets_path)
    active = load_object(active_path)
    retired = load_object(retired_path)
    structural = budgets.get("structural")
    performance = budgets.get("performance")
    require(isinstance(structural, dict), "storage structural budgets are missing")
    require(isinstance(performance, dict), "storage performance budgets are missing")
    require(
        budgets.get("status") == "provisional-unqualified",
        "input budgets falsely claim qualification",
    )
    require(
        budgets.get("measurements") is None,
        "input budgets contain mutable embedded measurements",
    )
    for flag in ("productionQualified", "deploymentQualified", "releaseAuthorized"):
        require(budgets.get(flag) is False, f"input budgets falsely claim {flag}")
    sample_count = integer(performance, "freshProcessSamples")
    require(
        sample_count >= MINIMUM_PROCESS_SAMPLE_COUNT,
        f"storage qualification requires at least {MINIMUM_PROCESS_SAMPLE_COUNT} fresh processes",
    )

    require(
        active.get("sourceSha") == source_sha, "active evidence source SHA mismatch"
    )
    require(
        retired.get("sourceSha") == source_sha,
        "retirement evidence source SHA mismatch",
    )
    require(
        integer(active, "activeRecords") == int(performance["activeRecordsSubject"]),
        "active-record qualification subject mismatch",
    )
    require(
        integer(active, "activeRecords") == int(structural["maxActiveRecords"]),
        "active-record qualification did not reach the structural ceiling",
    )
    require(
        integer(retired, "retiredIdentities")
        == int(performance["retiredIdentitiesSubject"]),
        "retired-identity qualification subject mismatch",
    )
    transitions = integer(active, "transitions")
    require(
        transitions == integer(active, "activeRecords") * 3 and transitions > 0,
        "active transitions must equal three transitions per active record",
    )
    require(
        active.get("schema") == "hepta.ui-native-storage-active-evidence.v1",
        "active evidence schema mismatch",
    )
    require(
        retired.get("schema") == "hepta.ui-native-storage-retirement-evidence.v1",
        "retirement evidence schema mismatch",
    )
    for label, evidence in (("active", active), ("retirement", retired)):
        require(
            integer(evidence, "processSampleCount") == sample_count,
            f"{label} evidence did not measure {sample_count} fresh processes",
        )
        scope = evidence.get("measurementScope")
        require(isinstance(scope, dict), f"{label} measurement scope is missing")
        require(
            scope.get("open") == OPEN_MEASUREMENT_SCOPE,
            f"{label} open measurement scope does not describe uncontrolled OS page cache",
        )
        require(
            sampled_percentile(
                evidence,
                "freshProcessOpenSamplesMilliseconds",
                "freshProcessOpenP95Milliseconds",
                sample_count,
            )
            <= number(performance, "coldStartP95Milliseconds"),
            f"{label} fresh-process open p95 exceeded coldStartP95Milliseconds",
        )
        rss_mib = integer(evidence, "peakRssMiB")
        require(rss_mib >= 0, f"{label} peak RSS is negative")
        require(
            rss_mib
            <= integer(
                performance,
                "activePeakRssMiB" if label == "active" else "millionRetiredPeakRssMiB",
            ),
            f"{label} peak RSS exceeded its hard ceiling",
        )
    require(
        sampled_percentile(
            retired,
            "freshProcessIndexRebuildSamplesMilliseconds",
            "freshProcessIndexRebuildP95Milliseconds",
            sample_count,
        )
        <= number(performance, "millionRetiredIndexRebuildP95Milliseconds"),
        "million-retired fresh-process index rebuild p95 exceeded its hard ceiling",
    )
    require(
        integer(active, "historyPageSize") == 64,
        "history evidence did not measure a 64-record page",
    )
    require(
        active["measurementScope"].get("historyPageBytes")
        == HISTORY_BYTES_MEASUREMENT_SCOPE,
        "history page retained bytes must identify serialized receipts rather than allocator accounting",
    )
    require(
        sampled_percentile(
            active,
            "historyPageSamplesMilliseconds",
            "historyPageP95Milliseconds",
            sample_count,
        )
        <= number(performance, "historyPageP95Milliseconds"),
        "history page p95 exceeded its hard ceiling",
    )
    history_bytes = integer(active, "historyPageMaxRetainedJsonBytes")
    require(history_bytes > 0, "history page retained bytes are not positive")
    require(
        history_bytes <= integer(performance, "historyPageRetainedSerializedBytes"),
        "history page retained bytes exceeded their hard ceiling",
    )
    validate_process_observations(
        active,
        "openProcessSamples",
        "freshProcessOpenSamplesMilliseconds",
        "active-open",
        source_sha,
        sample_count,
    )
    validate_process_observations(
        retired,
        "openProcessSamples",
        "freshProcessOpenSamplesMilliseconds",
        "retired-open",
        source_sha,
        sample_count,
    )
    validate_process_observations(
        retired,
        "indexRebuildProcessSamples",
        "freshProcessIndexRebuildSamplesMilliseconds",
        "retired-rebuild",
        source_sha,
        sample_count,
    )

    for percentile_rank in (50, 95, 99):
        metric = f"mutationP{percentile_rank}Milliseconds"
        require(
            sampled_percentile(
                active, "mutationSamplesMilliseconds", metric, transitions, percentile_rank
            ) <= number(performance, metric),
            f"{metric} exceeded its hard ceiling",
        )
    require(
        retired.get("deterministicRebuild") is True,
        "retirement index rebuild was not deterministic",
    )
    require(
        integer(active, "snapshotBytes") >= 0, "active snapshot byte count is negative"
    )
    require(integer(active, "walBytes") >= 0, "active WAL byte count is negative")
    require(
        integer(active, "snapshotBytes") <= int(structural["maxSnapshotBytes"]),
        "active snapshot exceeded its structural byte ceiling",
    )
    require(
        integer(active, "walBytes") <= int(structural["maxWalBytes"]),
        "active WAL exceeded its structural byte ceiling",
    )

    storage_root = active.get("root")
    require(
        isinstance(storage_root, str) and storage_root,
        "active evidence lacks its storage root",
    )
    write_bytes, sync_calls, trace_inventory = parse_traces(trace_prefix, storage_root)
    require(
        sync_calls >= transitions,
        "durability trace has fewer successful fsync/fdatasync calls than state transitions",
    )
    write_bytes_per_transition = (write_bytes + transitions - 1) // transitions
    require(
        write_bytes_per_transition
        <= int(performance["maximumWriteAmplificationBytesPerStateTransition"]),
        "durable write amplification exceeded its hard ceiling",
    )

    return {
        "schema": "hepta.ui-native-storage-qualification.v1",
        "sourceSha": source_sha,
        "status": "pass",
        "storageQualified": True,
        "productionQualified": False,
        "deploymentQualified": False,
        "releaseAuthorized": False,
        "activeEvidence": {
            "path": active_path.name,
            "sha256": sha256_file(active_path),
            "measurements": active,
        },
        "retirementEvidence": {
            "path": retired_path.name,
            "sha256": sha256_file(retired_path),
            "measurements": retired,
        },
        "durabilitySyscalls": {
            "writeBytes": write_bytes,
            "stateTransitions": transitions,
            "writeBytesPerTransition": write_bytes_per_transition,
            "fsyncOrFdatasyncCalls": sync_calls,
            "traceFiles": trace_inventory,
        },
        "budgets": {
            "path": budgets_path.name,
            "sha256": sha256_file(budgets_path),
            "structural": structural,
            "performance": performance,
        },
        "limitations": [
            "Linux hosted-runner evidence is not physical desktop acceptance",
            "Fresh processes do not control or evict the operating-system page cache",
            "History retained JSON bytes measure receipt payload, not total allocator activity",
            "storage qualification alone does not authorize production, deployment or release",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budgets", type=Path, required=True)
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--retired", type=Path, required=True)
    parser.add_argument("--trace-prefix", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--emit", type=Path, required=True)
    args = parser.parse_args()
    combined = validate_storage(
        args.budgets, args.active, args.retired, args.trace_prefix, args.source_sha
    )
    args.emit.parent.mkdir(parents=True, exist_ok=True)
    args.emit.write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(combined, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
