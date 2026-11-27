"""Immutable Linux process-owned receipts with a derived JSONL view.

A continuous prefix is not an all-terminal result or permission to retry work.
Private directories and honest storage are assumed. Abrupt-process tests do
not establish power-loss durability. Leftover .tmp files are never receipts.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

from .atomic_io import atomic_publish, canonical_json, identity, sync_directory


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate receipt JSON key")
        result[key] = value
    return result


def _load(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"receipt is not a regular file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict or canonical_json(value) != raw:
        raise ValueError("receipt is not a canonical JSON object")
    return value


def process_identity(pid=None):
    """Read a Linux process identity; disappearance is an error, not completion."""
    if pid is None:
        pid = os.getpid()
    if type(pid) is not int or pid <= 0:
        raise ValueError("process pid must be a positive builtin integer")
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return dict(
        pid=pid,
        boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        start_ticks=int(fields[19]),
    )


def _process():
    return process_identity()


def _paths(view_path):
    view = Path(view_path)
    return (
        view,
        view.with_name(view.name + ".records"),
        view.with_name(view.name + ".receipt-index.json"),
    )


def _expected_index(state):
    return dict(
        schema="hcsn-receipt-index-v1",
        owner_identity=state["owner_identity"],
        record_count=len(state["receipts"]),
        head_sha256=state["head_sha256"],
        view_identity=state["view_identity"],
    )


def read_receipts(view_path):
    """Verify every committed record; an unclosed prefix grants no completion."""
    view, directory, index_path = _paths(view_path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("receipt directory missing or not a regular directory")
    owner_path = directory / "owner.json"
    owner = _load(owner_path)
    if set(owner) != {"schema", "owner_id", "pid", "boot_id", "start_ticks"}:
        raise ValueError("invalid owner fields")
    if (
        owner["schema"] != "hcsn-journal-owner-v1"
        or type(owner["pid"]) is not int
        or owner["pid"] <= 0
        or type(owner["start_ticks"]) is not int
        or owner["start_ticks"] <= 0
    ):
        raise ValueError("invalid process owner")
    for key in ("owner_id", "boot_id"):
        if type(owner[key]) is not str or str(uuid.UUID(owner[key])) != owner[key]:
            raise ValueError("invalid owner UUID")
    owner_identity = identity(owner_path)
    records, pending = [], []
    for path in directory.iterdir():
        if path.name == "owner.json":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("nonregular receipt entry")
        if path.name.endswith(".tmp"):
            pending.append(str(path))
        elif re.fullmatch(r"[0-9]{20}\.json", path.name):
            records.append(path)
        else:
            raise ValueError(f"unexpected receipt entry: {path.name}")
    receipts, chunks, head = [], [], None
    for sequence, path in enumerate(sorted(records)):
        if path.name != f"{sequence:020d}.json":
            raise ValueError("receipt sequence has a gap")
        row = _load(path)
        if set(row) != {
            "schema",
            "sequence",
            "owner_sha256",
            "previous_sha256",
            "payload_sha256",
            "payload",
        }:
            raise ValueError("invalid receipt fields")
        if (
            row["schema"] != "hcsn-journal-receipt-v1"
            or type(row["sequence"]) is not int
            or row["sequence"] != sequence
            or row["owner_sha256"] != owner_identity["sha256"]
            or row["previous_sha256"] != head
            or type(row["payload"]) is not dict
        ):
            raise ValueError("receipt sequence, owner or chain mismatch")
        raw = canonical_json(row["payload"])
        if row["payload_sha256"] != _digest(raw):
            raise ValueError("receipt payload digest mismatch")
        head = identity(path)["sha256"]
        receipts.append(row)
        chunks.append(raw)
    for prefix in (f".{view.name}.", f".{index_path.name}."):
        pending.extend(str(p) for p in view.parent.glob(prefix + "*.tmp"))
    raw_view = b"".join(chunks)
    state = dict(
        owner=owner,
        owner_identity=owner_identity,
        receipts=receipts,
        head_sha256=head,
        view_identity=dict(bytes=len(raw_view), sha256=_digest(raw_view)),
        pending_temporary_files=len(pending),
        temporary_paths=sorted(pending),
        journal_closed=index_path.exists(),
        all_terminal_established=False,
    )
    if os.path.lexists(index_path) and canonical_json(
        _load(index_path)
    ) != canonical_json(_expected_index(state)):
        raise ValueError("receipt index does not match the committed chain")
    return state


def validate_closed_journal(view_path):
    """Require a complete matching index and view; never generate or repair."""
    view, _, index_path = _paths(view_path)
    state = read_receipts(view)
    index = _load(index_path)
    if canonical_json(index) != canonical_json(_expected_index(state)):
        raise ValueError("closed journal index mismatch")
    if (
        view.is_symlink()
        or not view.is_file()
        or identity(view) != index["view_identity"]
    ):
        raise ValueError("derived JSONL view does not match the receipt chain")
    return index


def validate_terminal_journal(view_path, expected_status, expected_process=None):
    """Require one final finished event matching the caller's terminal status."""
    if type(expected_status) is not str:
        raise ValueError("expected terminal status must be a string")
    index = validate_closed_journal(view_path)
    state = read_receipts(view_path)
    if expected_process is not None:
        keys = {"pid", "boot_id", "start_ticks"}
        observed = {key: state["owner"][key] for key in keys}
        if (
            type(expected_process) is not dict
            or set(expected_process) != keys
            or canonical_json(expected_process) != canonical_json(observed)
        ):
            raise ValueError("journal owner does not match the observed child process")
    receipts = state["receipts"]
    finished = [
        i for i, r in enumerate(receipts) if r["payload"].get("kind") == "finished"
    ]
    if (
        not receipts
        or finished != [len(receipts) - 1]
        or type(receipts[-1]["payload"].get("status")) is not str
        or receipts[-1]["payload"]["status"] != expected_status
    ):
        raise ValueError("journal lacks one final matching finished event")
    return index


class ReceiptJournal:
    """Create a new owner; never resume or overwrite an existing attempt."""

    def __init__(self, view_path):
        self.view, self.directory, self.index_path = _paths(view_path)
        if os.path.lexists(self.view) or os.path.lexists(self.index_path):
            raise FileExistsError("journal view or index already exists")
        self.view.parent.mkdir(parents=True, exist_ok=True)
        self.directory.mkdir()
        sync_directory(self.directory.parent)
        self.owner = dict(
            schema="hcsn-journal-owner-v1", owner_id=str(uuid.uuid4()), **_process()
        )
        raw = canonical_json(self.owner)
        self.owner_identity = atomic_publish(
            self.directory / "owner.json", lambda stream: stream.write(raw), _load
        )
        self._lock = threading.Lock()
        self._closed = False
        self._write_failed = False
        self._sequence, self._head, self._pending = 0, None, None

    def _check_owner(self):
        if any(self.owner[key] != value for key, value in _process().items()):
            raise ValueError("journal cannot be written by another process")
        if _load(self.directory / "owner.json") != self.owner:
            raise ValueError("journal owner was changed")

    def _append_view(self, raw):
        with self.view.open("ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def append(self, row):
        with self._lock:
            if self._closed or self._write_failed:
                raise ValueError("journal closed or prior write outcome uncertain")
            try:
                self._check_owner()
                if type(row) is not dict:
                    raise ValueError("journal payload must be a JSON object")
                payload = canonical_json(row)
                if os.path.lexists(self.index_path):
                    raise ValueError("journal already has a closing index")
                receipt = dict(
                    schema="hcsn-journal-receipt-v1",
                    sequence=self._sequence,
                    owner_sha256=self.owner_identity["sha256"],
                    previous_sha256=self._head,
                    payload_sha256=_digest(payload),
                    payload=json.loads(payload),
                )
                raw = canonical_json(receipt)
                self._pending = _digest(raw)
                committed = atomic_publish(
                    self.directory / f"{self._sequence:020d}.json",
                    lambda stream: stream.write(raw),
                    _load,
                )
                self._sequence += 1
                self._head, self._pending = committed["sha256"], None
                self._append_view(payload)
            except BaseException:
                self._write_failed = True
                raise
            return receipt

    def close(self):
        with self._lock:
            self._check_owner()
            if self._closed:
                return validate_closed_journal(self.view)
            state = read_receipts(self.view)
            if state["journal_closed"]:
                raise ValueError("unexpected prior closing index")
            actual = (len(state["receipts"]), state["head_sha256"])
            known = (self._sequence, self._head)
            pending = (self._sequence + 1, self._pending)
            if actual != known and not (
                self._write_failed and self._pending and actual == pending
            ):
                raise ValueError(
                    "receipt chain differs from the owner's committed history"
                )
            raw = b"".join(canonical_json(r["payload"]) for r in state["receipts"])

            def validate_view(path):
                if identity(path) != state["view_identity"]:
                    raise ValueError("rebuilt view differs from receipts")

            atomic_publish(
                self.view, lambda stream: stream.write(raw), validate_view, replace=True
            )
            index = _expected_index(state)
            encoded = canonical_json(index)
            atomic_publish(self.index_path, lambda stream: stream.write(encoded), _load)
            self._closed = True
            return validate_closed_journal(self.view)
