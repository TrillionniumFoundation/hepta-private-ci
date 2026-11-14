"""Node-local durable observations reject rollback after process restart."""

from dataclasses import asdict
from pathlib import Path

from network_authority import frontier_after, placement, transaction
from parametric_owner import Frontier, MAX_CELLS
from tensor_contract import strict_json
from network_wire import encode, fields


class Fences:
    def __init__(self, database):
        self.database = str(Path(database).absolute())
        if Path(self.database).is_symlink():
            raise ValueError("fence database cannot be a symlink")
        with transaction(self.database) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS seen (scope TEXT, cell TEXT, value BLOB, PRIMARY KEY(scope, cell))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS frontier (scope TEXT PRIMARY KEY, value BLOB)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY CHECK(id=1), calls INTEGER)"
            )
            db.execute("INSERT OR IGNORE INTO counter VALUES (1, 0)")

    def observe(self, scope, cell_id, snapshot):
        fields(snapshot, ("placement", "frontier"))
        view = Frontier(**snapshot["frontier"])
        current = snapshot["placement"]
        if view.scope != scope:
            raise ValueError("network source scope mismatch")
        if current is not None:
            placement(current)
            if (current["scope"], current["cell_id"]) != (scope, cell_id):
                raise ValueError("network cell identity mismatch")
        # A newer valid frontier remains latched even when placement is stale.
        with transaction(self.database) as db:
            old = db.execute(
                "SELECT value FROM frontier WHERE scope=?", (scope,)
            ).fetchone()
            frontier_after(
                Frontier(**strict_json(old[0])) if old else Frontier(scope), view
            )
            if (
                old is None
                and db.execute("SELECT count(*) FROM frontier").fetchone()[0]
                >= MAX_CELLS
            ):
                raise ValueError("node scope budget exceeded")
            db.execute(
                "INSERT OR REPLACE INTO frontier VALUES (?, ?)",
                (scope, encode(asdict(view))),
            )
        with transaction(self.database) as db:
            old = db.execute(
                "SELECT value FROM seen WHERE scope=? AND cell=?", (scope, cell_id)
            ).fetchone()
            previous = strict_json(old[0]) if old else None
            if previous is not None and (
                current is None
                or current["generation"] < previous["generation"]
                or (
                    current["generation"] == previous["generation"]
                    and current != previous
                )
            ):
                raise ValueError("placement rollback or same-generation fork")
            if (
                old is None
                and db.execute("SELECT count(*) FROM seen").fetchone()[0] >= MAX_CELLS
            ):
                raise ValueError("node placement budget exceeded")
            db.execute(
                "INSERT OR REPLACE INTO seen VALUES (?, ?, ?)",
                (scope, cell_id, encode(current)),
            )
        return view, current

    def calls(self, *, increment=False):
        with transaction(self.database) as db:
            if increment:
                db.execute("UPDATE counter SET calls=calls+1 WHERE id=1")
            return db.execute("SELECT calls FROM counter WHERE id=1").fetchone()[0]
