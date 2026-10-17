#!/usr/bin/env python3
"""Execute an exact 4x4 CellSplit measurement matrix on a real supplied host.

This runner never generates model measurements, independent signatures or
production authorization. Each external workload must write its own measured
JSON. The resulting packet is diagnostic until independently attested.
"""

from __future__ import annotations

import argparse
import hashlib
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
    strict_json_loads,
)

SCHEMA = "hepta.cell-split.execution-matrix.v1"
MEASUREMENT_SCHEMA = "hepta.cell-split.host-measurement.v1"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_HOST_RESULT_BYTES = 256 * 1024
# Identical to the detached raw-byte observer's log cap.
MAX_LOG_BYTES = 2 * 1024 * 1024


def require_pinned_capture_root(directory_fd: int, output: Path) -> None:
    """Fail closed on a renamed or substituted original capture directory."""
    try:
        opened = os.fstat(directory_fd)
        named = output.lstat()
    except OSError as error:
        raise InvalidEvidence(f"capture directory unavailable: {error}") from error
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
    ):
        raise InvalidEvidence("capture directory identity changed")


def create_capture_file(directory_fd: int, name: str):
    """Create original 0600 output files relative to the pinned directory."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise InvalidEvidence("invalid capture filename")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    return os.fdopen(fd, "wb")


def capture_name_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def read_stable_raw(
    path: Path, limit: int, label: str, *, directory_fd: int | None = None
) -> tuple[bytes, tuple[int, int]]:
    """Read bounded original bytes and return their verified device/inode identity."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        with os.fdopen(
            os.open(
                path if directory_fd is None else path.name,
                flags,
                dir_fd=directory_fd,
            ),
            "rb",
        ) as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise InvalidEvidence(f"{label}: regular single-linked file required")
            if before.st_size > limit:
                raise InvalidEvidence(f"{label}: exceeds {limit} byte limit")
            raw = source.read(limit + 1)
            after = os.fstat(source.fileno())
        named = (
            path.lstat()
            if directory_fd is None
            else os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        )
    except OSError as error:
        raise InvalidEvidence(f"{label}: file unavailable: {error}") from error
    if len(raw) > limit:
        raise InvalidEvidence(f"{label}: exceeds {limit} byte limit")

    def identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    if (
        len(raw) != before.st_size
        or identity(before) != identity(after)
        or identity(before) != identity(named)
        or not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
    ):
        raise InvalidEvidence(f"{label}: original evidence changed during read")
    return raw, (before.st_dev, before.st_ino)


def read_bounded_json(path: Path, limit: int, label: str) -> Any:
    """Read a stable original JSON packet without FIFO waits or duplicate keys."""
    raw, _ = read_stable_raw(path, limit, label)
    try:
        return strict_json_loads(raw)
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
    # An external model command runs inside this directory. Keep raw diagnostic
    # measurements and logs private even with a permissive process umask.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise InvalidEvidence("pinned capture directory support required")
    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_flags |= getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(output, root_flags)
    try:
        require_pinned_capture_root(directory_fd, output)
        with create_capture_file(directory_fd, "manifest.json") as record:
            record.write(
                (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
            )

        # A later workload may rewrite earlier files. Freeze the original bytes
        # and re-open their original inodes before publishing a diagnostic packet.
        # Detached observer custody remains independently mandatory.
        frozen: dict[str, tuple[int, bytes, tuple[int, int]]] = {}

        def freeze(path: Path, limit: int) -> bytes:
            require_pinned_capture_root(directory_fd, output)
            raw, inode = read_stable_raw(
                path, limit, path.name, directory_fd=directory_fd
            )
            frozen[path.name] = (limit, hashlib.sha256(raw).digest(), inode)
            return raw

        freeze(output / "manifest.json", MAX_MANIFEST_BYTES)
        measurements = []
        for scope in SCOPES:
            for mode in MODES:
                prefix = output / f"{scope}-{mode}"
                result_path = prefix.with_suffix(".json")
                require_pinned_capture_root(directory_fd, output)
                env = os.environ.copy()
                env["HEPTA_CELL_SPLIT_RESULT_PATH"] = str(result_path.resolve())
                env["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"] = str(scope)
                env["HEPTA_CELL_SPLIT_EXPECTED_MODE"] = mode
                argv = commands[(scope, mode)]
                stdout_path = prefix.with_suffix(".stdout.log")
                stderr_path = prefix.with_suffix(".stderr.log")
                # A previous workload is untrusted. Never accept a file it planted
                # for a later case, even if its schema, SHA and counters look valid.
                # lexists also catches dangling links. Exclusive log opens protect
                # against a new race between this check and subprocess dispatch.
                if any(
                    capture_name_exists(directory_fd, path.name)
                    for path in (result_path, stdout_path, stderr_path)
                ):
                    raise InvalidEvidence(
                        f"{scope}/{mode}: pre-existing result or log before workload"
                    )
                # Freeze source identity for *each* workload: a command may modify
                # tracked source after the initial matrix-level preflight.
                verify_exact_source(repository, manifest["source_sha"])
                with create_capture_file(directory_fd, stdout_path.name) as stdout:
                    with create_capture_file(directory_fd, stderr_path.name) as stderr:
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
                require_pinned_capture_root(directory_fd, output)
                if result.returncode != 0:
                    raise InvalidEvidence(
                        f"{scope}/{mode}: workload exited {result.returncode}"
                    )
                # Reject a result even if it reports the expected SHA when the
                # executed workload changed the checkout. Never start the next run.
                verify_exact_source(repository, manifest["source_sha"])
                # Validate the very same bytes that are retained for final replay.
                raw_row = freeze(result_path, MAX_HOST_RESULT_BYTES)
                try:
                    observed = strict_json_loads(raw_row)
                except (UnicodeDecodeError, ValueError) as error:
                    raise InvalidEvidence(
                        f"{scope}/{mode}: invalid host JSON: {error}"
                    ) from error
                measurements.append(
                    validate_measurement(observed, manifest, scope, mode)
                )
                freeze(stdout_path, MAX_LOG_BYTES)
                freeze(stderr_path, MAX_LOG_BYTES)

        # Identical parsed metrics are insufficient: any earlier raw result, log
        # or manifest mutation invalidates capture. Do not write a complete packet.
        for name, (limit, original_sha, original_inode) in frozen.items():
            require_pinned_capture_root(directory_fd, output)
            current, current_inode = read_stable_raw(
                output / name, limit, name, directory_fd=directory_fd
            )
            if (
                current_inode != original_inode
                or hashlib.sha256(current).digest() != original_sha
            ):
                raise InvalidEvidence(
                    f"{name}: original host evidence changed after measurement"
                )

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
        # Never follow a result symlink planted by one of the 16 workloads.
        # Complete packets remain diagnostic, not signed activation evidence.
        require_pinned_capture_root(directory_fd, output)
        with create_capture_file(directory_fd, "measured-matrix.json") as record:
            record.write((json.dumps(packet, sort_keys=True, indent=2) + "\n").encode())
        with create_capture_file(directory_fd, "diagnostic-comparison.json") as record:
            record.write(
                (json.dumps(comparison, sort_keys=True, indent=2) + "\n").encode()
            )
        require_pinned_capture_root(directory_fd, output)
        return comparison
    finally:
        os.close(directory_fd)


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
