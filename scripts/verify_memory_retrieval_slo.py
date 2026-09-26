#!/usr/bin/env python3
"""Fail-closed qualification of retrieval measurements; never grant release authority.

Raw logs, thresholds, exact source identity and runner metadata are content-bound.
The historical target-host schema qualifies microbenchmarks only. End-to-end
qualification requires observed pipeline counters, not a sum of phase p95s.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any

SCHEMA = "hepta.memory-retrieval.target-host.v1"
E2E_SCHEMA = "hepta.memory-retrieval.agentd-e2e.v1"
RECEIPT_SCHEMA = "hepta.memory-retrieval.qualification-receipt.v2"
RSS_RE = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_LOG_BYTES = 32 * 1024 * 1024
STAGES = (
    "owner_observation", "snapshot_binding", "candidate_adaptation", "hnmf_settling",
    "downstream_ranker", "final_revalidation", "text_materialization",
    "context_plan", "learning_assignment_append",
)
E2E_METRICS = (
    "p50_us", "p95_us", "p99_us", "max_us", "cpu_time_us", "peak_rss_bytes",
    "allocation_count", "sqlite_read_count", "candidate_count", "node_count",
    "synapse_count", "owner_write_contention_count", "provider_rotation_count",
    "abstention_count", "stale_rejection_count", "failure_count", "delivered_count",
    "attempts", "concurrency",
)


def strict_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=strict_pairs, parse_constant=reject_constant)


def natural(value: Any, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(f"{name}: expected {'positive' if positive else 'non-negative'} integer")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_percentiles(row: dict[str, Any]) -> None:
    # Handles both HNMF and the owner probe's retrieval_/revalidation_ metrics.
    for prefix in ("", "retrieval_", "revalidation_"):
        keys = [f"{prefix}{name}_us" for name in ("p50", "p95", "p99", "max")]
        present = [natural(row[key], key) for key in keys if key in row]
        if present != sorted(present):
            raise ValueError(f"non-monotone latency percentiles for {prefix or 'total'}")


def validate_e2e(row: dict[str, Any]) -> None:
    if row.get("phase") != "agentd-e2e":
        raise ValueError("E2E schema must name the agentd-e2e phase")
    for key in E2E_METRICS:
        natural(row.get(key), key, positive=key in ("attempts", "concurrency"))
    attempts = row["attempts"]
    outcomes = sum(row[key] for key in (
        "abstention_count", "stale_rejection_count", "failure_count", "delivered_count"
    ))
    if outcomes != attempts:
        raise ValueError("E2E mutually exclusive outcomes do not sum to attempts")
    if row.get("cache_state") not in ("cold", "warm"):
        raise ValueError("E2E cache_state must be cold or warm")
    if row.get("resource_scope") != "request_pipeline":
        raise ValueError("E2E resources must exclude build and fixture setup")
    observed = row.get("stage_observations")
    if not isinstance(observed, dict) or set(observed) != set(STAGES):
        raise ValueError("E2E requires observations for every pipeline stage")
    for stage, count in observed.items():
        if natural(count, stage) != attempts:
            raise ValueError(f"{stage}: stage disposition must be observed on every attempt")
    executed = row.get("stage_executions")
    if not isinstance(executed, dict) or set(executed) != set(STAGES):
        raise ValueError("E2E requires execution counts distinct from observations")
    for stage, count in executed.items():
        if natural(count, stage) > attempts:
            raise ValueError(f"{stage}: executions exceed attempts")
    # A fully bypassed ranker/ledger is not evidence for the full requested path.
    if any(executed[stage] == 0 for stage in STAGES):
        raise ValueError("E2E scenario never executed one or more required stages")
    if natural(row.get("pending_learning_assignments"), "pending_learning_assignments") != 0:
        raise ValueError("E2E measurement ended before learning assignment completion")
    for metric, counter in (("abstention_rate_ppm", "abstention_count"),
                            ("stale_rejection_rate_ppm", "stale_rejection_count")):
        expected = row[counter] * 1_000_000 // attempts
        if natural(row.get(metric), metric) != expected:
            raise ValueError(f"{metric}: inconsistent numerator/denominator")


def load_measurement(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError(f"{path}: log exceeds bounded reader limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_LOG_BYTES + 1)
    if len(raw) > MAX_LOG_BYTES:
        raise ValueError(f"{path}: log grew beyond bounded reader limit")
    text = raw.decode("utf-8", errors="strict")
    rows = []
    for line in text.splitlines():
        if SCHEMA not in line and E2E_SCHEMA not in line:
            continue
        start = line.find("{")
        if start < 0:
            raise ValueError(f"{path}: schema marker without JSON measurement")
        value = loads(line[start:])
        if not isinstance(value, dict) or value.get("schema") not in (SCHEMA, E2E_SCHEMA):
            raise ValueError(f"{path}: unsupported measurement row")
        rows.append(value)
    if len(rows) != 1:
        raise ValueError(f"{path}: expected exactly one measurement, found {len(rows)}")
    row = rows[0]
    if not isinstance(row.get("phase"), str) or not row["phase"]:
        raise ValueError("missing measurement phase")
    validate_percentiles(row)
    if row["schema"] == E2E_SCHEMA:
        validate_e2e(row)
    else:
        rss = RSS_RE.findall(text)
        if len(rss) != 1:
            raise ValueError(f"{path}: expected one GNU-time RSS field, found {len(rss)}")
        row["maximum_rss_kb"] = natural(int(rss[0]), "maximum_rss_kb", positive=True)
        row["rss_scope"] = "whole_command_including_build_if_any"
        if "iterations" in row:
            natural(row["iterations"], "iterations", positive=True)
    row["log_sha256"] = sha256(raw)
    return row


def verify_phase(measurement: dict[str, Any], limits: dict[str, Any]) -> list[str]:
    if not isinstance(limits, dict) or not limits:
        raise ValueError("empty or invalid phase thresholds")
    failures = []
    for metric, maximum in sorted(limits.items()):
        natural(maximum, f"threshold.{metric}")
        actual = natural(measurement.get(metric), metric)
        if actual > maximum:
            failures.append(f"{metric}={actual} exceeds {maximum}")
    return failures


def verify_measurements(rows: list[dict[str, Any]], profile: dict[str, Any],
                        require_e2e: bool = False) -> list[str]:
    if profile.get("schema") != "hepta.memory-retrieval.slo-thresholds.v1":
        raise ValueError("unsupported threshold schema")
    if not isinstance(profile.get("profile"), str) or not profile["profile"]:
        raise ValueError("missing profile identity")
    phases = profile.get("phases")
    if not isinstance(phases, dict) or not phases:
        raise ValueError("empty threshold profile cannot qualify anything")
    by_phase: dict[str, dict[str, Any]] = {}
    for row in rows:
        phase = row["phase"]
        if phase in by_phase:
            raise ValueError(f"duplicate measurement phase: {phase}")
        by_phase[phase] = row
    if set(by_phase) != set(phases):
        raise ValueError("observed phases differ from the exact threshold phase set")
    if require_e2e:
        if set(by_phase) != {"agentd-e2e"} or rows[0].get("schema") != E2E_SCHEMA:
            raise ValueError("microbenchmark evidence cannot qualify Agentd E2E SLO")
        validate_e2e(rows[0])
        if not set(E2E_METRICS[:6]).issubset(phases["agentd-e2e"]):
            raise ValueError("E2E profile must bound latency, CPU and RSS")
    return [f"{phase}: {failure}" for phase, row in sorted(by_phase.items())
            for failure in verify_phase(row, phases[phase])]


def source_identity(root: Path, expected_sha: str, expected_tree: str) -> dict[str, str]:
    if not SHA_RE.fullmatch(expected_sha) or not SHA_RE.fullmatch(expected_tree):
        raise ValueError("source identity requires lowercase exact Git SHA-1 objects")
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    if git("rev-parse", "HEAD") != expected_sha or git("rev-parse", "HEAD^{tree}") != expected_tree:
        raise ValueError("measurement source differs from checked-out exact head/tree")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked source changed during qualification")
    return {"commit": expected_sha, "tree": expected_tree, "parents": git("show", "-s", "--format=%P", "HEAD")}


def write_immutable(path: Path, value: dict[str, Any]) -> None:
    payload = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # No overwrite path: a failed or repeated run must use a new evidence key.
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thresholds", required=True, type=Path)
    parser.add_argument("--log", action="append", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--require-e2e", action="store_true")
    args = parser.parse_args()
    try:
        source = source_identity(args.repository_root, args.source_sha, args.source_tree)
        raw_profile = args.thresholds.read_bytes()
        profile = loads(raw_profile.decode("utf-8"))
        rows = [load_measurement(path) for path in args.log]
        failures = verify_measurements(rows, profile, args.require_e2e)
        receipt = {
            "schema": RECEIPT_SCHEMA, "source": source,
            "threshold_profile": profile["profile"], "threshold_sha256": sha256(raw_profile),
            "measurements": sorted(rows, key=lambda row: row["phase"]),
            "qualification_scope": "agentd-e2e" if args.require_e2e else "microbenchmark",
            "runner": {"os": platform.system(), "arch": platform.machine(),
                       "run_id": os.environ.get("GITHUB_RUN_ID"),
                       "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")},
            "passed": not failures, "failures": failures,
            "independentAcceptance": False, "activation": False, "release": False,
            "integrity_is_not_authentication": True,
        }
        receipt["receipt_sha256"] = sha256(canonical(receipt))
        # Check again before publishing; a source change must not receive a receipt.
        source_identity(args.repository_root, args.source_sha, args.source_tree)
        write_immutable(args.output, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 1 if failures else 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
