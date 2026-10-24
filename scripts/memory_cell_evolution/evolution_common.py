"""Bounded, immutable local evidence; this module never imports a model runtime."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def identifier(value):
    require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value),
        "bounded identifier required",
    )
    return value


def roots(values):
    require(
        type(values) in (list, tuple) and len(values) <= 4096,
        "bounded root list required",
    )
    require(
        all(type(v) is str and re.fullmatch(r"[a-f0-9]{64}", v) for v in values),
        "SHA-256 roots required",
    )
    require(len(set(values)) == len(values), "duplicate source root")
    return sorted(values)


def read_json(path):
    return json.loads(Path(path).read_bytes())


def retain(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@contextmanager
def transaction(path):
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def checked_frontier(value, scope):
    require(
        type(value) is dict and set(value) == {"scope", "epoch", "roots", "revoked"},
        "closed source frontier required",
    )
    require(
        value["scope"] == scope
        and type(value["epoch"]) is int
        and 0 <= value["epoch"] < 2**63,
        "source frontier identity",
    )
    current, withdrawn = roots(value["roots"]), roots(value["revoked"])
    require(not set(current) & set(withdrawn), "current/withdrawn root overlap")
    return dict(scope=scope, epoch=value["epoch"], roots=current, revoked=withdrawn)


def advance_frontier(previous, current):
    if previous is not None:
        require(current["epoch"] >= previous["epoch"], "source epoch rollback")
        require(
            set(previous["revoked"]) <= set(current["revoked"]), "withdrawal rollback"
        )
        require(
            current["epoch"] != previous["epoch"] or current == previous,
            "same-epoch source fork",
        )
