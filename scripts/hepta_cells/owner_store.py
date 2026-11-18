"""Create new owner stores exclusively; validate complete stores before opening.

The unchanged schema accepts complete existing WAL or checkpointed stores. A
stable byte copy is checked before writable access, then checked again under the
owner transaction. Damaged stores and rollback journals require explicit repair.
There is no authority transfer, backup adoption, or automatic history repair here.
"""

from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile

from .component_types import CellError, OwnerLimits
from .owner_history import validate_owner_history


_SCHEMA = """
CREATE TABLE cells(
                partition TEXT PRIMARY KEY, identity TEXT NOT NULL, generation INTEGER NOT NULL,
                sequence INTEGER NOT NULL, state TEXT NOT NULL, view TEXT NOT NULL,
                budget TEXT NOT NULL, remaining INTEGER NOT NULL);
            CREATE TABLE intents(
                partition TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL, generation INTEGER NOT NULL, status TEXT NOT NULL,
                reserved INTEGER NOT NULL, identity TEXT NOT NULL, view TEXT NOT NULL,
                budget TEXT NOT NULL, receipt TEXT,
                PRIMARY KEY(partition,request));
            CREATE TABLE attempts(
                partition TEXT NOT NULL, request TEXT NOT NULL, phase TEXT NOT NULL,
                elapsed_ns INTEGER, work_units INTEGER, outcome TEXT NOT NULL, readback_elapsed_ns INTEGER);
            CREATE TABLE history(
                partition TEXT NOT NULL, generation INTEGER NOT NULL, identity TEXT NOT NULL,
                PRIMARY KEY(partition,generation));
            CREATE TABLE checkpoints(
                digest TEXT PRIMARY KEY, partition TEXT NOT NULL, snapshot TEXT NOT NULL);
            CREATE TABLE owner_settings(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), limits TEXT NOT NULL);
            CREATE TABLE cancellations(
                partition TEXT NOT NULL, request TEXT NOT NULL, identity TEXT NOT NULL,
                PRIMARY KEY(partition,request));
            CREATE TABLE migrations(
                partition TEXT NOT NULL, operation TEXT NOT NULL, fingerprint TEXT NOT NULL,
                receipt TEXT NOT NULL, PRIMARY KEY(partition,operation));
CREATE TABLE population_plan(singleton INTEGER PRIMARY KEY CHECK(singleton=1), digest TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE population_current(cell_id TEXT PRIMARY KEY, identity TEXT NOT NULL, bundle TEXT, epoch INTEGER NOT NULL);
CREATE TABLE population_partitions(partition TEXT PRIMARY KEY, cell_id TEXT NOT NULL, epoch INTEGER NOT NULL);
CREATE TABLE population_consumed(partition TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(partition,request));
"""

_SCHEMA_QUERY = "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"


def _schema(db):
    return tuple(
        (kind, name, table, re.sub(r"\s+", " ", sql).strip() if sql else None)
        for kind, name, table, sql in db.execute(_SCHEMA_QUERY)
    )


@lru_cache(maxsize=1)
def _expected_schema():
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(_SCHEMA)
        return _schema(db)
    finally:
        db.close()


def _validate(db, limits):
    schema = _schema(db)
    if schema != _expected_schema():
        if not {row[1] for row in _expected_schema()} <= {row[1] for row in schema}:
            raise CellError(
                "owner schema is incomplete; retained tables lost their original policy"
            )
        raise CellError("owner schema or constraints are incompatible")
    settings = db.execute("SELECT singleton,limits FROM owner_settings").fetchall()
    if len(settings) != 1 or settings[0][0] != 1:
        raise CellError("retained database policy is missing")
    try:
        policy = json.loads(settings[0][1])
        retained = OwnerLimits(**policy)
        if policy != asdict(retained):
            raise CellError("retained database policy has missing fields")
    except (ValueError, TypeError) as error:
        raise CellError("retained database policy is invalid") from error
    if limits is not None and limits != retained:
        raise CellError("owner limits differ from the retained database policy")
    if [tuple(row) for row in db.execute("PRAGMA integrity_check")] != [("ok",)]:
        raise CellError("owner integrity check failed")
    validate_owner_history(db)


def _files(path):
    result = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        source = Path(str(path) + suffix)
        try:
            value = source.lstat()
        except FileNotFoundError:
            result[suffix] = None
            continue
        if not stat.S_ISREG(value.st_mode):
            raise CellError("owner store members must be regular files")
        if suffix == "-journal":
            raise CellError("owner rollback journal requires explicit recovery")
        result[suffix] = (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    return result


def open_owner_store(database, limits):
    """Return a connection with its initialization/validation transaction open.

    Only a missing path starts exclusive creation. An existing empty or damaged
    path is never new. ``:memory:`` retains its explicit ephemeral semantics.
    A racing initializer may be rejected until its complete transaction exists.
    """
    path = None if str(database) == ":memory:" else Path(database).absolute()
    new = path is None
    if path is not None:
        try:
            if any(
                Path(str(path) + suffix).exists()
                for suffix in ("-wal", "-shm", "-journal")
            ):
                if not path.exists():
                    raise CellError("orphan owner sidecars require explicit recovery")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            new = True
    db = None
    try:
        if not new:
            before = _files(path)
            with tempfile.TemporaryDirectory(prefix="hepta-owner-open-") as directory:
                copy = Path(directory) / "owner.sqlite"
                for suffix, info in before.items():
                    if info is not None and suffix != "-shm":
                        source = Path(str(path) + suffix)
                        descriptor = os.open(
                            source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                        )
                        with (
                            os.fdopen(descriptor, "rb") as incoming,
                            Path(str(copy) + suffix).open("xb") as outgoing,
                        ):
                            shutil.copyfileobj(incoming, outgoing)
                if _files(path) != before:
                    raise CellError("owner changed while validating its retained bytes")
                readonly = sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True)
                try:
                    _validate(readonly, limits)
                finally:
                    readonly.close()
        if not new and _files(path) != before:
            raise CellError("owner changed after validating its retained bytes")
        db = sqlite3.connect(
            ":memory:" if path is None else path.as_uri() + "?mode=rw",
            uri=path is not None,
            isolation_level=None,
            timeout=10,
        )
        if new:
            db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        if new:
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
        else:
            _validate(db, limits)
        db.row_factory = sqlite3.Row
        return db
    except BaseException as error:
        if db is not None:
            db.close()
        if isinstance(error, (OSError, sqlite3.Error)):
            raise CellError(
                "owner cannot be opened without explicit recovery"
            ) from error
        raise
