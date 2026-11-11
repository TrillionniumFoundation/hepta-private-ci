"""Fail-closed, crash-recoverable local receipts for *successor* HCSN C2 runs.

This module is not the original C2 controller or an independent experiment auditor.
It requires a POSIX local filesystem with atomic hard links and directory fsync.
Successful producer receipts alone NEVER authorize scientific admission.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

SCHEMA = "hcsn-c2-durable-receipt-v1"
ZERO = "0" * 64
_MAX_RECORD = 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TERMINALS = frozenset({"completed", "budget_exhausted", "failed", "cancelled", "timeout"})


class EvidenceError(ValueError):
    """Unverifiable, contradictory, or incomplete evidence."""


def _id(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise EvidenceError("identity must be a canonical nonempty builtin string")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise EvidenceError("invalid SHA-256 digest")
    return value


def _encode(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise EvidenceError("noncanonical JSON value") from exc


def _valid_terminal(payload: object) -> None:
    if type(payload) is not dict:
        raise EvidenceError("terminal payload is not a builtin dictionary")
    if type(payload.get("status")) is not str or payload["status"] not in _TERMINALS:
        raise EvidenceError("terminal has no canonical terminal status")
    _id(payload.get("native_job_id"))
    _digest(payload.get("result_sha256"))
    _digest(payload.get("resource_sha256"))


def _load(raw: bytes) -> dict:
    def invalid_constant(value: str) -> None:
        raise EvidenceError("nonfinite JSON constant: " + value)

    try:
        obj = json.loads(raw, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid JSON receipt") from exc
    if type(obj) is not dict or _encode(obj) != raw:
        raise EvidenceError("receipt has noncanonical JSON bytes")
    return obj


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _directory_sync(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def identity(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("not a regular checkpoint or receipt")
    data_hash = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            data_hash.update(block)
            length += len(block)
    if length == 0:
        raise EvidenceError("zero-byte checkpoint or receipt")
    return {"bytes": length, "sha256": data_hash.hexdigest()}


def publish_once(path: Path, writer: Callable, verifier: Callable[[Path], bool],
                 *, max_bytes: int = 1 << 32) -> dict:
    """Write/verify private temp bytes, hard-link once, and fsync the directory.

    A crash before link leaves no published object; a crash after link can leave
    a valid published object AND an orphan temporary. Neither is terminal evidence.
    Existing published objects, including invalid/zero objects, are never clobbered.
    The caller must separately validate semantic checkpoint identity with verifier.
    """
    path = Path(path)
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir() or path.is_symlink():
        raise EvidenceError("target parent must be an existing real directory")
    if type(max_bytes) is not int or not 0 < max_bytes <= (1 << 40):
        raise EvidenceError("invalid file byte budget")
    fd, tmp_name = tempfile.mkstemp(prefix=".c2-pending-", dir=parent)
    temporary = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        observed = identity(temporary)
        if observed["bytes"] > max_bytes:
            raise EvidenceError("checkpoint/receipt byte budget exceeded")
        if verifier(temporary) is not True:
            raise EvidenceError("checkpoint/receipt semantic verification failed")
        if identity(temporary) != observed:
            raise EvidenceError("temporary content mutated during verification")
        # LINK, never rename over an existing original. POSIX O_EXCL semantics.
        os.link(temporary, path)
        _directory_sync(parent)
        return observed
    finally:
        if temporary.exists():
            temporary.unlink()
            _directory_sync(parent)


def publish_checkpoint(path: Path, serialize: Callable,
                       validate: Callable[[Path], bool],
                       *, max_bytes: int = 1 << 32) -> dict:
    """Serialize a *new* checkpoint; caller must validate full frozen semantics.

    Example: serialize=lambda fh: torch.save(snapshot, fh)
    validate must safely load and check source/model/optimizer/RNG/data identities.
    Never call this on the immutable original C2 file path.
    """
    if not callable(serialize) or not callable(validate):
        raise EvidenceError("serialization and semantic verification are required")
    return publish_once(path, serialize, validate, max_bytes=max_bytes)


def verify_checkpoint(path: Path, expected: dict,
                      validate: Callable[[Path], bool]) -> dict:
    if type(expected) is not dict or set(expected) != {"bytes", "sha256"}:
        raise EvidenceError("checkpoint identity missing")
    if type(expected["bytes"]) is not int or expected["bytes"] <= 0:
        raise EvidenceError("invalid checkpoint size")
    _digest(expected["sha256"])
    before = identity(path)
    if before != expected or validate(Path(path)) is not True or identity(path) != before:
        raise EvidenceError("checkpoint content or semantic identity mismatch")
    return before


def read_receipts(root: Path, *, owner_start_id: str) -> list[dict]:
    """Verify canonical bytes, contiguous sequence, checksum and prev-byte hash."""
    _id(owner_start_id)
    root = Path(root)
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError("receipts root must be a real directory")
    files = sorted(root.glob("*.json"))
    events = []
    preceding = ZERO
    for sequence, path in enumerate(files):
        if sequence >= 100000000 or path.name != f"{sequence:08d}.json":
            raise EvidenceError("gap, duplicate, or unexpected receipt name")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_RECORD:
            raise EvidenceError("nonregular or oversized receipt")
        raw = path.read_bytes()
        row = _load(raw)
        if set(row) != {"schema", "seq", "owner_start_id", "attempt_id",
                        "event_type", "payload", "prev_sha256", "sha256"}:
            raise EvidenceError("unexpected/missing receipt fields")
        _id(row["attempt_id"])
        _id(row["event_type"])
        if (row["schema"] != SCHEMA or type(row["seq"]) is not int
                or row["seq"] != sequence or row["owner_start_id"] != owner_start_id
                or row["prev_sha256"] != preceding or type(row["payload"]) is not dict):
            raise EvidenceError("wrong owner, sequence, or previous digest")
        _digest(row["prev_sha256"])
        _digest(row["sha256"])
        if row["event_type"] == "terminal":
            _valid_terminal(row["payload"])
        base = {key: value for key, value in row.items() if key != "sha256"}
        if _sha(_encode(base)) != row["sha256"]:
            raise EvidenceError("receipt checksum mismatch")
        preceding = _sha(raw)
        events.append(row)
    terminals = set()
    for row in events:
        attempt = row["attempt_id"]
        if attempt in terminals:
            raise EvidenceError("event after terminal or duplicate terminal")
        if row["event_type"] == "terminal":
            terminals.add(attempt)
    return events


def append_receipt(root: Path, *, owner_start_id: str, attempt_id: str,
                   event_type: str, payload: dict) -> dict:
    """Serializes concurrent controller-thread writes under a cross-process flock."""
    _id(owner_start_id)
    _id(attempt_id)
    _id(event_type)
    if type(payload) is not dict:
        raise EvidenceError("payload must be a builtin dictionary")
    if event_type == "terminal":
        _valid_terminal(payload)
    root = Path(root)
    if root.is_symlink():
        raise EvidenceError("receipts root may not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            events = read_receipts(root, owner_start_id=owner_start_id)
            if event_type == "terminal" and any(
                row["event_type"] == "terminal" and row["attempt_id"] == attempt_id
                for row in events
            ):
                raise EvidenceError("second terminal for same attempt")
            sequence = len(events)
            previous = (_sha((root / f"{sequence - 1:08d}.json").read_bytes())
                        if sequence else ZERO)
            base = {"schema": SCHEMA, "seq": sequence,
                    "owner_start_id": owner_start_id, "attempt_id": attempt_id,
                    "event_type": event_type, "payload": payload,
                    "prev_sha256": previous}
            raw = _encode({**base, "sha256": _sha(_encode(base))})
            if len(raw) > _MAX_RECORD:
                raise EvidenceError("receipt too large")

            def write(stream):
                stream.write(raw)

            def check(tmp):
                return tmp.read_bytes() == raw

            return publish_once(root / f"{sequence:08d}.json", write, check,
                                max_bytes=_MAX_RECORD)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def producer_roster(root: Path, *, owner_start_id: str,
                    expected_attempts: list[str]) -> dict:
    """Diagnose only producer completeness: NEVER certify independent B or GO."""
    if type(expected_attempts) is not list or not expected_attempts:
        raise EvidenceError("nonempty frozen expected-attempt roster required")
    expected = [_id(name) for name in expected_attempts]
    if len(set(expected)) != len(expected):
        raise EvidenceError("duplicate expected attempt")
    observed = read_receipts(root, owner_start_id=owner_start_id)
    terminals = {}
    for row in observed:
        if row["attempt_id"] not in expected:
            raise EvidenceError("unexpected attempt in receipts")
        if row["event_type"] == "terminal":
            terminals[row["attempt_id"]] = row["payload"]["status"]
    missing = [name for name in expected if name not in terminals]
    return {"schema": "hcsn-c2-producer-roster-v1",
            "expected_count": len(expected), "producer_terminal_count": len(terminals),
            "missing": missing, "terminals": terminals, "producer_complete": not missing,
            "independent_native_verification": False, "scientific_admission": "HOLD"}
