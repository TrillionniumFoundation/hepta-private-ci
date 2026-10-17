#!/usr/bin/env python3
"""Read-only independent-process custody of raw CellSplit matrix bytes.

A detached observer must pin source/host/model/workload/trace identities out of
band. This copies the exact 16 raw host packets and sixteenth-pair logs into a
create-only local evidence directory, and recomputes the producer's diagnostic
comparison. Its local hashes are UNSIGNED: neither this tool nor its outputs
attest hardware, independent signatures, target-host origin, NDU, or Final-use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from hepta_cell_split_matrix_capture import (
    MAX_HOST_RESULT_BYTES,
    MAX_MANIFEST_BYTES,
    validate_manifest,
    validate_measurement,
)
from hepta_cell_split_perf_gate import (
    MODES,
    SCOPES,
    TRACE_FIELD,
    InvalidEvidence,
    analyze,
)

SCHEMA = "hepta.cell-split.observer-local-custody.v1"
MAX_COMPARISON_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024


def _directory_identity(directory_fd: int, path: Path) -> None:
    """Fail closed if a pinned directory is renamed, removed or substituted."""
    try:
        opened = os.fstat(directory_fd)
        named = path.lstat()
    except OSError as error:
        raise InvalidEvidence(
            f"{path.name}: pinned directory unavailable: {error}"
        ) from error
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
    ):
        raise InvalidEvidence(f"{path.name}: pinned directory identity changed")


def _read_regular(
    directory_fd: int, name: str, limit: int
) -> tuple[bytes, tuple[int, int]]:
    """Read stable bytes and the actual inode from the same pinned directory."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise InvalidEvidence("invalid evidence filename")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise InvalidEvidence("observer requires O_NOFOLLOW host support")
    flags |= os.O_NOFOLLOW
    try:
        with os.fdopen(os.open(name, flags, dir_fd=directory_fd), "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > limit
            ):
                raise InvalidEvidence(
                    f"{name}: nonregular, hardlinked or oversized evidence"
                )
            raw = source.read(limit + 1)
            after = os.fstat(source.fileno())
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as error:
        raise InvalidEvidence(f"{name}: unavailable evidence: {error}") from error

    def identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    if (
        len(raw) > limit
        or len(raw) != before.st_size
        or identity(before) != identity(after)
        or identity(before) != identity(named)
        or not stat.S_ISREG(named.st_mode)
    ):
        raise InvalidEvidence(f"{name}: evidence changed while observed")
    return raw, (before.st_dev, before.st_ino)


def _strict_json(raw: bytes, name: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidEvidence(f"{name}: duplicate JSON field {key}")
            result[key] = value
        return result

    def reject_constant(constant: str) -> None:
        raise InvalidEvidence(f"{name}: invalid numeric constant {constant}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise InvalidEvidence(f"{name}: malformed JSON: {error}") from error


def _write_exclusive(directory_fd: int, name: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "wb") as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())


def observe(
    capture: Path,
    destination: Path,
    *,
    source_sha: str,
    hardware_id: str,
    model_digest: str,
    workload_digest: str,
    trace_sha256: str,
) -> dict[str, Any]:
    """Retain raw evidence only after externally pinned, full 16-way checks."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not re.fullmatch(
        r"[0-9a-f]{64}", trace_sha256
    ):
        raise InvalidEvidence("observer requires exact source and trace pins")
    if any(
        not isinstance(v, str) or not v
        for v in (hardware_id, model_digest, workload_digest)
    ):
        raise InvalidEvidence("observer requires nonempty external identity pins")
    if capture.is_symlink() or not capture.is_dir():
        raise InvalidEvidence("capture must be an actual directory")
    root = capture.resolve(strict=True)
    output = destination.resolve(strict=False)
    if output == root or root in output.parents or output.exists():
        raise InvalidEvidence("custody output must be a new directory outside capture")

    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise InvalidEvidence("observer requires pinned directory FD support")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    root_fd = os.open(root, directory_flags)
    try:
        _directory_identity(root_fd, root)
        artifacts: dict[str, bytes] = {}
        limits: dict[str, int] = {}
        original_inodes: dict[str, tuple[int, int]] = {}

        def take(name: str, limit: int) -> bytes:
            raw, inode = _read_regular(root_fd, name, limit)
            artifacts[name] = raw
            limits[name] = limit
            original_inodes[name] = inode
            return raw

        def recheck_captured_bytes() -> None:
            _directory_identity(root_fd, root)
            for name, original in artifacts.items():
                current, inode = _read_regular(root_fd, name, limits[name])
                if inode != original_inodes[name]:
                    raise InvalidEvidence(
                        f"{name}: original evidence inode replaced during custody"
                    )
                if current != original:
                    raise InvalidEvidence(
                        f"{name}: original evidence changed during custody"
                    )
            _directory_identity(root_fd, root)

        manifest = _strict_json(take("manifest.json", MAX_MANIFEST_BYTES), "manifest")
        packet = _strict_json(
            take("measured-matrix.json", MAX_COMPARISON_BYTES), "matrix"
        )
        reported = _strict_json(
            take("diagnostic-comparison.json", MAX_COMPARISON_BYTES), "comparison"
        )
        if not isinstance(manifest, dict) or not isinstance(packet, dict):
            raise InvalidEvidence("capture manifest and matrix must be objects")
        validate_manifest(manifest)
        frozen = {
            "source_sha": source_sha,
            "hardware_id": hardware_id,
            "model_digest": model_digest,
            "workload_digest": workload_digest,
        }
        for field, pin in frozen.items():
            if manifest.get(field) != pin or packet.get(field) != pin:
                raise InvalidEvidence(
                    f"observer's independently frozen {field} differs"
                )
        recalculated = analyze(packet)
        if not isinstance(reported, dict) or reported != recalculated:
            raise InvalidEvidence("producer comparison differs from independent replay")
        if recalculated[TRACE_FIELD] != trace_sha256:
            raise InvalidEvidence("independent frozen request trace differs")
        if reported.get("production_evidence_verified") or reported.get(
            "production_activation_authorized"
        ):
            raise InvalidEvidence(
                "producer packet asserted forbidden production authority"
            )

        rows = {(row["scopes"], row["mode"]): row for row in packet["runs"]}
        for scope in SCOPES:
            for mode in MODES:
                prefix = f"{scope}-{mode}"
                original = _strict_json(
                    take(f"{prefix}.json", MAX_HOST_RESULT_BYTES), f"{prefix} host row"
                )
                row = validate_measurement(original, manifest, scope, mode)
                if row != rows[(scope, mode)] or row[TRACE_FIELD] != trace_sha256:
                    raise InvalidEvidence(
                        f"{prefix}: host row differs from published matrix"
                    )
                take(f"{prefix}.stdout.log", MAX_LOG_BYTES)
                take(f"{prefix}.stderr.log", MAX_LOG_BYTES)

        # Catch capture mutations between early manifest/measurement reads and
        # final sealing. This is a local byte-stability check, not a signed host
        # snapshot or remote anti-rollback witness.
        recheck_captured_bytes()
        # The observer stores source bytes, not merely producer-asserted digests.
        # An incomplete/crashed export has no COMPLETE marker and is inadmissible.
        output.mkdir(mode=0o700)
        output_fd = os.open(output, directory_flags)
        try:
            _directory_identity(output_fd, output)
            digests = {}
            for name, content in sorted(artifacts.items()):
                _write_exclusive(output_fd, name, content)
                digests[name] = {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                }
            ledger = {
                "schema": SCHEMA,
                "external_pins": {**frozen, TRACE_FIELD: trace_sha256},
                "artifacts": digests,
                "comparative_gate_passed": recalculated["comparative_gate_passed"],
                "production_evidence_verified": False,
                "production_activation_authorized": False,
                "independent_signature_verified": False,
                "target_host_attested": False,
            }
            ledger_bytes = (
                json.dumps(ledger, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
            _write_exclusive(output_fd, "custody-ledger.json", ledger_bytes)
            # Do not publish COMPLETE if any earlier source file changed while the
            # read-only observer was copying its evidence.
            recheck_captured_bytes()
            _directory_identity(output_fd, output)
            _write_exclusive(
                output_fd,
                "COMPLETE",
                (hashlib.sha256(ledger_bytes).hexdigest() + "\n").encode(),
            )
            _directory_identity(output_fd, output)
            os.fsync(output_fd)
            return ledger
        finally:
            os.close(output_fd)
    finally:
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--hardware-id", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--workload-digest", required=True)
    parser.add_argument("--trace-sha256", required=True)
    args = parser.parse_args()
    try:
        ledger = observe(
            args.capture,
            args.output,
            source_sha=args.source_sha,
            hardware_id=args.hardware_id,
            model_digest=args.model_digest,
            workload_digest=args.workload_digest,
            trace_sha256=args.trace_sha256,
        )
    except (InvalidEvidence, OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "comparative_gate_passed": ledger["comparative_gate_passed"],
                "production_activation_authorized": False,
            },
            sort_keys=True,
        )
    )
    # Preserve negative raw evidence, but never give an orchestration gate a
    # successful process status when the frozen comparison itself failed.
    return 0 if ledger["comparative_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
