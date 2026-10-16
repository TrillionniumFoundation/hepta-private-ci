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


def _read_regular(path: Path, limit: int) -> bytes:
    """Read one exact inode without following a symlink, FIFO, or device."""
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise InvalidEvidence("observer requires O_NOFOLLOW host support")
    flags |= os.O_NOFOLLOW
    try:
        with os.fdopen(os.open(path, flags), "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise InvalidEvidence(f"{path.name}: nonregular or oversized evidence")
            raw = source.read(limit + 1)
            after = os.fstat(source.fileno())
        named = path.lstat()
    except OSError as error:
        raise InvalidEvidence(f"{path.name}: unavailable evidence: {error}") from error
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (
        len(raw) > limit
        or len(raw) != before.st_size
        or identity(before) != identity(after)
        or identity(before) != identity(named)
        or not stat.S_ISREG(named.st_mode)
    ):
        raise InvalidEvidence(f"{path.name}: evidence changed while observed")
    return raw


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


def _write_exclusive(directory: Path, name: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory / name, flags, 0o600)
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

    artifacts: dict[str, bytes] = {}

    def take(name: str, limit: int) -> bytes:
        raw = _read_regular(root / name, limit)
        artifacts[name] = raw
        return raw

    manifest = _strict_json(take("manifest.json", MAX_MANIFEST_BYTES), "manifest")
    packet = _strict_json(take("measured-matrix.json", MAX_COMPARISON_BYTES), "matrix")
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
            raise InvalidEvidence(f"observer's independently frozen {field} differs")
    recalculated = analyze(packet)
    if not isinstance(reported, dict) or reported != recalculated:
        raise InvalidEvidence("producer comparison differs from independent replay")
    if recalculated[TRACE_FIELD] != trace_sha256:
        raise InvalidEvidence("independent frozen request trace differs")
    if reported.get("production_evidence_verified") or reported.get(
        "production_activation_authorized"
    ):
        raise InvalidEvidence("producer packet asserted forbidden production authority")

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

    # The observer stores source bytes, not merely producer-asserted digests.
    # An incomplete/crashed export has no COMPLETE marker and is inadmissible.
    output.mkdir(mode=0o700)
    digests = {}
    for name, content in sorted(artifacts.items()):
        _write_exclusive(output, name, content)
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
    _write_exclusive(output, "custody-ledger.json", ledger_bytes)
    _write_exclusive(
        output, "COMPLETE", (hashlib.sha256(ledger_bytes).hexdigest() + "\n").encode()
    )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    with os.fdopen(os.open(output, flags), "rb") as directory:
        os.fsync(directory.fileno())
    return ledger


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
