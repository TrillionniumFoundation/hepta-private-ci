"""Explicit creation and fail-closed opening of the local receiver store.

This format uses a single authoritative SQLite rollback-journal database. An
incomplete initializer is retained for investigation and never reopened as new.
Old WAL stores and hot-journal recovery require a separate explicit procedure.
"""

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .component_types import CellError, _hex


_VERSION = "hepta.receiver-store.v1"
_SCHEMA = """
CREATE TABLE metadata(
    version TEXT PRIMARY KEY, receiver_id TEXT NOT NULL, schema_sha256 TEXT NOT NULL);
CREATE TABLE authority(
    partition TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch INTEGER NOT NULL,
    key_hash TEXT NOT NULL, component TEXT NOT NULL,
    tool_digest TEXT NOT NULL, phase TEXT NOT NULL);
CREATE TABLE effects(
    partition TEXT NOT NULL, request TEXT NOT NULL, operation TEXT NOT NULL,
    invocation TEXT NOT NULL, record TEXT NOT NULL, receipt TEXT NOT NULL,
    PRIMARY KEY(partition, request), UNIQUE(partition, operation));
CREATE TABLE transfers(
    id TEXT PRIMARY KEY, binding TEXT NOT NULL, manifest TEXT NOT NULL, receipt TEXT);
"""
_SCHEMA_QUERY = "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"


@lru_cache(maxsize=1)
def _expected_schema():
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(_SCHEMA)
        return tuple(db.execute(_SCHEMA_QUERY).fetchall())
    finally:
        db.close()


def _validate(db, receiver_id):
    expected = _expected_schema()
    if tuple(db.execute(_SCHEMA_QUERY).fetchall()) != expected:
        raise CellError("receiver schema or constraints are missing or incompatible")
    schema_hash = hashlib.sha256(json.dumps(expected).encode()).hexdigest()
    if db.execute("SELECT * FROM metadata").fetchall() != [
        (_VERSION, receiver_id, schema_hash)
    ]:
        raise CellError("receiver metadata or identity binding differs")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise CellError("receiver integrity check failed")


def create_receiver(path, receiver_id):
    """Create once. Concurrent initializers lose with FileExistsError; no repair."""
    _hex(receiver_id)
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, isolation_level=None, timeout=10)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        schema_hash = hashlib.sha256(
            json.dumps(_expected_schema()).encode()
        ).hexdigest()
        db.execute(
            "INSERT INTO metadata VALUES(?,?,?)", (_VERSION, receiver_id, schema_hash)
        )
        db.commit()
    finally:
        db.close()


def open_receiver(path, receiver_id):
    """Validate existing bytes before writable access; never create missing tables.

    Read-only rollback-journal validation cannot recover a hot journal. Such an
    interrupted transaction stays blocked. Normal concurrent writers may finish
    while SQLite waits for its lock; journal existence alone is not corruption.
    """
    _hex(receiver_id)
    path = Path(path).absolute()
    try:
        with path.open("rb") as stream:
            header = stream.read(100)
        if (
            len(header) != 100
            or header[:16] != b"SQLite format 3\0"
            or header[18:20] != b"\x01\x01"
        ):
            raise CellError("receiver requires an initialized rollback-journal store")
        readonly = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            _validate(readonly, receiver_id)
        finally:
            readonly.close()
        db = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=10
        )
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            _validate(db, receiver_id)
            db.commit()
            db.row_factory = sqlite3.Row
            return db
        except BaseException:
            db.close()
            raise
    except (OSError, sqlite3.Error) as error:
        raise CellError(
            "receiver cannot be opened without explicit recovery"
        ) from error
