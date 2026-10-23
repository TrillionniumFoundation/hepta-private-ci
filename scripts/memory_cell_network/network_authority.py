"""One durable authority for placement CAS and monotonic withdrawal frontiers.

This is a trusted single-writer authority, not a consensus implementation.
Checkpoint roots are registered by the trusted publisher, never a query caller.
"""

from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import sqlite3

from parametric_owner import Frontier, MAX_CELLS, _digest, _name, _roots
from tensor_contract import strict_json
from network_wire import encode, fields


@contextmanager
def transaction(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def frontier_after(previous, current):
    if (
        current.scope != previous.scope
        or current.epoch < previous.epoch
        or not set(previous.revoked) <= set(current.revoked)
        or (current.epoch == previous.epoch and current != previous)
    ):
        raise ValueError("withdrawal frontier rollback or same-epoch fork")


def placement(value):
    fields(
        value, ("scope", "cell_id", "node_id", "generation", "manifest_sha256", "roots")
    )
    if (
        any(not _name(value[key]) for key in ("scope", "cell_id", "node_id"))
        or not _digest(value["manifest_sha256"])
        or type(value["generation"]) is not int
        or not 0 <= value["generation"] < 2**63
        or not _roots(value["roots"])
        or value["roots"] != list(_roots(value["roots"]))
    ):
        raise ValueError("invalid canonical cell placement")
    return value


class Authority:
    def __init__(self, database, *, source_frontier=None):
        self.database = str(Path(database).absolute())
        self.source_frontier = source_frontier
        if Path(self.database).is_symlink():
            raise ValueError("authority database cannot be a symlink")
        with transaction(self.database) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS frontier (scope TEXT PRIMARY KEY, value BLOB)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS placement (scope TEXT, cell TEXT, value BLOB, PRIMARY KEY(scope, cell))"
            )

    @staticmethod
    def _frontier(db, scope):
        row = db.execute(
            "SELECT value FROM frontier WHERE scope=?", (scope,)
        ).fetchone()
        return Frontier(**strict_json(row[0])) if row else Frontier(scope)

    @staticmethod
    def _placement(db, scope, cell_id):
        row = db.execute(
            "SELECT value FROM placement WHERE scope=? AND cell=?", (scope, cell_id)
        ).fetchone()
        return placement(strict_json(row[0])) if row else None

    def sync_frontier(self, view):
        if type(view) is not Frontier:
            raise ValueError("typed source frontier required")
        with transaction(self.database) as db:
            frontier_after(self._frontier(db, view.scope), view)
            if (
                db.execute("SELECT count(*) FROM frontier").fetchone()[0] >= MAX_CELLS
                and not db.execute(
                    "SELECT 1 FROM frontier WHERE scope=?", (view.scope,)
                ).fetchone()
            ):
                raise ValueError("authority scope budget exceeded")
            db.execute(
                "INSERT OR REPLACE INTO frontier VALUES (?, ?)",
                (view.scope, encode(asdict(view))),
            )
        return asdict(view)

    def snapshot(self, scope, cell_id):
        if not _name(scope) or not _name(cell_id):
            raise ValueError("scope and cell identity required")
        if self.source_frontier is not None:
            view = self.source_frontier(scope)
            if type(view) is not Frontier or view.scope != scope:
                raise ValueError("source provider scope mismatch")
            self.sync_frontier(view)
        with transaction(self.database) as db:
            return dict(
                placement=self._placement(db, scope, cell_id),
                frontier=asdict(self._frontier(db, scope)),
            )

    def publish(self, candidate, expected_generation):
        candidate = placement(candidate)
        if expected_generation is not None and (
            type(expected_generation) is not int or not 0 <= expected_generation < 2**63
        ):
            raise ValueError("bounded expected generation required")
        if candidate["generation"] != (
            0 if expected_generation is None else expected_generation + 1
        ):
            raise ValueError("placement generation must advance once")
        self.snapshot(candidate["scope"], candidate["cell_id"])
        with transaction(self.database) as db:
            view = self._frontier(db, candidate["scope"])
            if set(candidate["roots"]) & set(view.revoked):
                raise ValueError("withdrawn learning ancestor")
            old = self._placement(db, candidate["scope"], candidate["cell_id"])
            if old == candidate:
                return old  # Identical retries cannot create another generation.
            if (old["generation"] if old else None) != expected_generation:
                raise ValueError("placement CAS mismatch")
            if (
                old is None
                and db.execute("SELECT count(*) FROM placement").fetchone()[0]
                >= MAX_CELLS
            ):
                raise ValueError("authority cell budget exceeded")
            db.execute(
                "INSERT OR REPLACE INTO placement VALUES (?, ?, ?)",
                (candidate["scope"], candidate["cell_id"], encode(candidate)),
            )
        return candidate

    def dispatch(self, request):
        if type(request) is not dict:
            raise ValueError("RPC object required")
        operation = request.get("op")
        if operation == "snapshot":
            fields(request, ("op", "scope", "cell_id"))
            return self.snapshot(request["scope"], request["cell_id"])
        if operation == "publish":
            fields(request, ("op", "placement", "expected_generation"))
            return self.publish(request["placement"], request["expected_generation"])
        if operation == "frontier":
            fields(request, ("op", "frontier"))
            if self.source_frontier is not None:
                raise ValueError("frontier is owned by the bound source service")
            return self.sync_frontier(Frontier(**request["frontier"]))
        if operation == "status":
            fields(request, ("op",))
            return dict(role="authority", pid=os.getpid(), consensus=False)
        raise ValueError("unknown authority operation")
