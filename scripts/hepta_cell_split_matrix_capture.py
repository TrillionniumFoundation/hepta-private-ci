#!/usr/bin/env python3
"""Execute an exact 4x4 CellSplit measurement matrix on a real supplied host.

This runner never generates model measurements, independent signatures or
production authorization. Each external workload must write its own measured
JSON. The resulting packet is diagnostic until independently attested.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from hepta_cell_split_perf_gate import (
    FIELDS,
    MODES,
    SCOPES,
    TRACE_FIELD,
    InvalidEvidence,
    analyze,
    validate_run_numbers,
)

SCHEMA = "hepta.cell-split.execution-matrix.v1"
MEASUREMENT_SCHEMA = "hepta.cell-split.host-measurement.v1"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_HOST_RESULT_BYTES = 256 * 1024


def read_bounded_json(path: Path, limit: int, label: str) -> Any:
    """Read an external JSON packet without unbounded memory or FIFO waits."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        with os.fdopen(os.open(path, flags), "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise InvalidEvidence(f"{label}: regular file required")
            if metadata.st_size > limit:
                raise InvalidEvidence(f"{label}: exceeds {limit} byte limit")
            raw = source.read(limit + 1)
    except OSError as error:
        raise InvalidEvidence(f"{label}: file unavailable: {error}") from error
    if len(raw) > limit:
        raise InvalidEvidence(f"{label}: exceeds {limit} byte limit")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise InvalidEvidence(f"{label}: invalid JSON: {error}") from error



def validate_manifest(manifest: dict[str, Any]) -> dict[tuple[int, str], list[str]]:
    if manifest.get("schema") != SCHEMA:
        raise InvalidEvidence("invalid execution-matrix schema")
    sha = manifest.get("source_sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise InvalidEvidence("source_sha must be the exact source commit")
    for field in ("hardware_id", "model_digest", "workload_digest"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise InvalidEvidence(f"missing {field}")
    raw = manifest.get("runs")
    if not isinstance(raw, list) or len(raw) != len(SCOPES) * len(MODES):
        raise InvalidEvidence("exactly sixteen commands are required")
    commands: dict[tuple[int, str], list[str]] = {}
    for run in raw:
        if not isinstance(run, dict):
            raise InvalidEvidence("run must be an object")
        scope = run.get("scopes")
        mode = run.get("mode")
        argv = run.get("argv")
        if type(scope) is not int or scope not in SCOPES or mode not in MODES:
            raise InvalidEvidence("invalid scope/mode")
        if (scope, mode) in commands:
            raise InvalidEvidence("duplicate scope/mode")
        if (
            not isinstance(argv, list)
            or not 1 <= len(argv) <= 128
            or any(not isinstance(a, str) or not a or "\x00" in a for a in argv)
        ):
            raise InvalidEvidence("argv must be a bounded, nonempty argument array")
        commands[(scope, mode)] = argv
    if set(commands) != {(scope, mode) for scope in SCOPES for mode in MODES}:
        raise InvalidEvidence("incomplete measurement matrix")
    return commands


def verify_exact_source(repository: Path, sha: str) -> None:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip()
        changed = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repository,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise InvalidEvidence(f"source identity unavailable: {error}") from error
    if head != sha or changed:
        raise InvalidEvidence("source checkout is stale or tracked files are dirty")


def validate_measurement(
    observed: Any, manifest: dict[str, Any], scope: int, mode: str
) -> dict[str, Any]:
    if not isinstance(observed, dict) or observed.get("schema") != MEASUREMENT_SCHEMA:
        raise InvalidEvidence(
            f"{scope}/{mode}: workload did not return a measured packet"
        )
    for field in ("source_sha", "hardware_id", "model_digest", "workload_digest"):
        if observed.get(field) != manifest[field]:
            raise InvalidEvidence(f"{scope}/{mode}: {field} mismatch")
    if observed.get("scopes") != scope or observed.get("mode") != mode:
        raise InvalidEvidence(f"{scope}/{mode}: incorrect run binding")
    provenance = observed.get("measurement_source")
    if (
        not isinstance(provenance, str)
        or not provenance
        or any(
            label in provenance.lower()
            for label in ("simulation", "fixture", "synthetic")
        )
    ):
        raise InvalidEvidence(f"{scope}/{mode}: real measurement source required")
    # Keep measurements exactly as emitted by the workload. In particular no
    # wall-clock-derived percentiles, synthetic zero failures or CPU estimates.
    missing = [field for field in FIELDS if field not in observed]
    if missing:
        raise InvalidEvidence(f"{scope}/{mode}: missing {missing}")
    trace = observed.get(TRACE_FIELD)
    if not isinstance(trace, str) or re.fullmatch(r"[0-9a-f]{64}", trace) is None:
        raise InvalidEvidence(
            f"{scope}/{mode}: canonical attempted request trace is required"
        )
    # Reject malformed or rounded measurements before spending resources
    # on the remaining runs. The comparison stage uses the same validator.
    validate_run_numbers(observed, scope, mode)
    return {
        "scopes": scope,
        "mode": mode,
        TRACE_FIELD: trace,
        **{field: observed[field] for field in FIELDS},
    }


def execute_matrix(
    manifest: dict[str, Any],
    repository: Path,
    output: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    commands = validate_manifest(manifest)
    if not 1 <= timeout_seconds <= 86_400:
        raise InvalidEvidence("timeout must be 1..86400 seconds")
    verify_exact_source(repository, manifest["source_sha"])
    # Exclusive new directory: never mistake stale evidence for a new run.
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    measurements = []
    for scope in SCOPES:
        for mode in MODES:
            prefix = output / f"{scope}-{mode}"
            result_path = prefix.with_suffix(".json")
            env = os.environ.copy()
            env["HEPTA_CELL_SPLIT_RESULT_PATH"] = str(result_path.resolve())
            env["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"] = str(scope)
            env["HEPTA_CELL_SPLIT_EXPECTED_MODE"] = mode
            argv = commands[(scope, mode)]
            # Freeze source identity for *each* workload: a command may modify
            # tracked source after the initial matrix-level preflight.
            verify_exact_source(repository, manifest["source_sha"])
            with prefix.with_suffix(".stdout.log").open("wb") as stdout:
                with prefix.with_suffix(".stderr.log").open("wb") as stderr:
                    try:
                        result = subprocess.run(
                            argv,
                            cwd=repository,
                            env=env,
                            stdout=stdout,
                            stderr=stderr,
                            timeout=timeout_seconds,
                            check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired) as error:
                        raise InvalidEvidence(
                            f"{scope}/{mode}: workload unavailable or timed out: {error}"
                        ) from error
            if result.returncode != 0:
                raise InvalidEvidence(
                    f"{scope}/{mode}: workload exited {result.returncode}"
                )
            # Reject a result even if it reports the expected SHA when the
            # executed workload changed the checkout. Never start the next run.
            verify_exact_source(repository, manifest["source_sha"])
            observed = read_bounded_json(
                result_path, MAX_HOST_RESULT_BYTES, f"{scope}/{mode} host result"
            )
            measurements.append(validate_measurement(observed, manifest, scope, mode))
    packet = {
        "schema": "hepta.cell-split.performance.v1",
        "source_sha": manifest["source_sha"],
        "hardware_id": manifest["hardware_id"],
        "model_digest": manifest["model_digest"],
        "workload_digest": manifest["workload_digest"],
        "runs": measurements,
    }
    # Validate complete comparable evidence, but never sign/activate it.
    comparison = analyze(packet)
    # Last check before publishing a complete diagnostic packet, including
    # concurrent tracked-file edits made during comparison/serialization.
    verify_exact_source(repository, manifest["source_sha"])
    (output / "measured-matrix.json").write_text(
        json.dumps(packet, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (output / "diagnostic-comparison.json").write_text(
        json.dumps(comparison, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    try:
        manifest = read_bounded_json(
            args.manifest, MAX_MANIFEST_BYTES, "execution manifest"
        )
        comparison = execute_matrix(
            manifest,
            args.repository.resolve(),
            args.output.resolve(),
            args.timeout_seconds,
        )
    except (OSError, ValueError, TypeError, InvalidEvidence) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "comparative_gate_passed": comparison["comparative_gate_passed"],
                "production_evidence_verified": False,
                "production_activation_authorized": False,
                "violations": comparison["violations"],
            },
            sort_keys=True,
        )
    )
    return 0 if comparison["comparative_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
