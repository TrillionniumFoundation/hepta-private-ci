"""Atomic local source revisions, immediate reads and a durable training outbox.

This is an explicit local research source owner, not an authenticated adapter to
the production HNMF ledger. Revocation blocks use; retained audit history is not
physical deletion. Every source change invalidates the cell's parameter epoch.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from durability import sync_directory
from service_types import (
    MemoryCellRoleV1,
    ReadResult,
    ReadStatus,
    SourceConflict,
    WriteReceipt,
    canonical,
    digest,
    identifier,
    key,
)

MAX_ACTIVE_SOURCES = 128
MAX_SOURCE_EVENTS = 4096


class SourceStore:
    """One scoped logical cell's immutable revisions and transactional outbox."""

    def __init__(self, database, scope, cell_id="memory", role="semantic"):
        self.database = str(Path(database).absolute())
        self.scope, self.cell_id = identifier(scope), identifier(cell_id)
        self.role = MemoryCellRoleV1(role).value
        if Path(self.database).is_symlink():
            raise ValueError("source database cannot be a symlink")
        with self.transaction() as db:
            for sql in (
                "CREATE TABLE IF NOT EXISTS metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sources (source_id TEXT NOT NULL, revision INTEGER NOT NULL, root TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(source_id, revision))",
                "CREATE TABLE IF NOT EXISTS heads (source_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, revoked INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS withdrawals (root TEXT PRIMARY KEY, epoch INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, epoch INTEGER UNIQUE NOT NULL, snapshot TEXT NOT NULL, state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, worker TEXT, token TEXT, deadline REAL, candidate TEXT, error TEXT)",
                "CREATE TABLE IF NOT EXISTS parameter_binding (singleton INTEGER PRIMARY KEY CHECK(singleton=1), value TEXT NOT NULL)",
            ):
                db.execute(sql)
            row = db.execute("SELECT value FROM metadata WHERE singleton=1").fetchone()
            if row is None:
                value = dict(
                    schema=1,
                    scope=self.scope,
                    cell_id=self.cell_id,
                    role=self.role,
                    epoch=0,
                )
                db.execute(
                    "INSERT INTO metadata VALUES (1,?)", (canonical(value).decode(),)
                )
            else:
                value = json.loads(row[0])
                if (
                    value.get("schema"),
                    value.get("scope"),
                    value.get("cell_id"),
                    value.get("role"),
                ) != (1, self.scope, self.cell_id, self.role):
                    raise ValueError("source owner identity mismatch")
        sync_directory(Path(self.database).parent)

    @contextmanager
    def transaction(self, write=True):
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def metadata(self, db):
        return json.loads(
            db.execute("SELECT value FROM metadata WHERE singleton=1").fetchone()[0]
        )

    def records(self, db, active_only=True):
        rows = db.execute(
            "SELECT s.payload,s.root,h.revoked FROM heads h JOIN sources s "
            "ON h.source_id=s.source_id AND h.revision=s.revision ORDER BY h.source_id"
        ).fetchall()
        records = []
        for row in rows:
            payload = json.loads(row["payload"])
            if digest(payload) != row["root"] or (
                payload.get("scope"),
                payload.get("cell_id"),
                payload.get("role"),
            ) != (self.scope, self.cell_id, self.role):
                raise ValueError("source bytes or owner identity changed")
            if not active_only or not row["revoked"]:
                records.append(
                    payload
                    | {"source_digest": row["root"], "revoked": bool(row["revoked"])}
                )
        return records

    def snapshot_in(self, db):
        records = self.records(db)
        groups = {}
        for record in records:
            groups.setdefault((record["entity"], record["relation"]), []).append(record)
        facts, conflicts = [], []
        for (entity, relation), group in sorted(groups.items()):
            roots = sorted(r["source_digest"] for r in group)
            if len({r["value"] for r in group}) != 1:
                conflicts.append(dict(entity=entity, relation=relation, roots=roots))
                continue
            facts.append(
                dict(
                    scope=self.scope,
                    entity=entity,
                    relation=relation,
                    value=group[0]["value"],
                    source_digest=roots[0],
                )
            )
        value = dict(
            schema="hepta.memory-service.source-snapshot.v1",
            scope=self.scope,
            cell_id=self.cell_id,
            role=self.role,
            epoch=self.metadata(db)["epoch"],
            sources=records,
            facts=facts,
            conflicts=conflicts,
            roots=sorted(r["source_digest"] for r in records),
            revoked=[
                r[0] for r in db.execute("SELECT root FROM withdrawals ORDER BY root")
            ],
        )
        return value | {"digest": digest(value)}

    def snapshot(self):
        with self.transaction(write=False) as db:
            return self.snapshot_in(db)

    def read(self, entity, relation):
        key(entity, relation)
        with self.transaction(write=False) as db:
            epoch = self.metadata(db)["epoch"]
            rows = [
                r
                for r in self.records(db, active_only=False)
                if (r["entity"], r["relation"]) == (entity, relation)
            ]
            active = [r for r in rows if not r["revoked"]]
            if not active:
                status = ReadStatus.REVOKED if rows else ReadStatus.UNKNOWN
                answer = None
                support = rows
            else:
                values = {r["value"] for r in active}
                status = (
                    ReadStatus.ANSWERED if len(values) == 1 else ReadStatus.CONFLICT
                )
                answer = next(iter(values)) if len(values) == 1 else None
                support = active
            return ReadResult(
                status,
                answer,
                "source_overlay",
                tuple(sorted(r["source_digest"] for r in support)),
                tuple(sorted(r["source_id"] for r in support)),
                epoch,
            )

    def _enqueue(self, db, epoch):
        snapshot = self.snapshot_in(db)
        db.execute("UPDATE jobs SET state='superseded' WHERE state='queued'")
        cursor = db.execute(
            "INSERT INTO jobs(epoch,snapshot,state) VALUES (?,?,'queued')",
            (epoch, canonical(snapshot).decode()),
        )
        return cursor.lastrowid

    def write(self, source_id, entity, relation, value, expected_revision=None):
        identifier(source_id)
        key(entity, relation)
        if type(value) is not str or not value.strip() or len(value.encode()) > 1024:
            raise ValueError("bounded nonempty source value required")
        if expected_revision is not None and (
            type(expected_revision) is not int
            or not 0 <= expected_revision < MAX_SOURCE_EVENTS
        ):
            raise ValueError("bounded expected source revision required")
        with self.transaction() as db:
            old = db.execute(
                "SELECT * FROM heads WHERE source_id=?", (source_id,)
            ).fetchone()
            if (old["revision"] if old else None) != expected_revision or (
                old and old["revoked"]
            ):
                raise SourceConflict("source revision CAS failed or source was revoked")
            if (
                db.execute("SELECT count(*) FROM sources").fetchone()[0]
                >= MAX_SOURCE_EVENTS
            ):
                raise ValueError("source history budget exhausted")
            if (
                old is None
                and db.execute("SELECT count(*) FROM heads WHERE revoked=0").fetchone()[
                    0
                ]
                >= MAX_ACTIVE_SOURCES
            ):
                raise ValueError("active source budget exhausted")
            metadata = self.metadata(db)
            metadata["epoch"] += 1
            revision = 0 if old is None else old["revision"] + 1
            payload = dict(
                scope=self.scope,
                cell_id=self.cell_id,
                role=self.role,
                source_id=source_id,
                revision=revision,
                entity=entity,
                relation=relation,
                value=value,
            )
            root = digest(payload)
            if old:
                previous = db.execute(
                    "SELECT root,payload FROM sources WHERE source_id=? AND revision=?",
                    (source_id, old["revision"]),
                ).fetchone()
                previous_payload = json.loads(previous["payload"])
                if (previous_payload["entity"], previous_payload["relation"]) != (
                    entity,
                    relation,
                ):
                    raise SourceConflict(
                        "correction cannot silently change the source key"
                    )
                db.execute(
                    "INSERT OR IGNORE INTO withdrawals VALUES (?,?)",
                    (previous["root"], metadata["epoch"]),
                )
            db.execute(
                "INSERT INTO sources VALUES (?,?,?,?)",
                (source_id, revision, root, canonical(payload).decode()),
            )
            db.execute(
                "INSERT OR REPLACE INTO heads VALUES (?,?,0)", (source_id, revision)
            )
            db.execute(
                "UPDATE metadata SET value=? WHERE singleton=1",
                (canonical(metadata).decode(),),
            )
            job_id = self._enqueue(db, metadata["epoch"])
            return WriteReceipt(
                "write" if old is None else "correct",
                source_id,
                revision,
                root,
                metadata["epoch"],
                job_id,
            )

    def correct(self, source_id, value, expected_revision):
        identifier(source_id)
        with self.transaction(write=False) as db:
            rows = [
                r
                for r in self.records(db, active_only=False)
                if r["source_id"] == source_id
            ]
        if not rows:
            raise SourceConflict("cannot correct an unknown source")
        return self.write(
            source_id, rows[0]["entity"], rows[0]["relation"], value, expected_revision
        )

    def revoke(self, source_id, expected_revision):
        identifier(source_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected source revision required")
        with self.transaction() as db:
            row = db.execute(
                "SELECT h.revision,h.revoked,s.root FROM heads h JOIN sources s ON h.source_id=s.source_id AND h.revision=s.revision WHERE h.source_id=?",
                (source_id,),
            ).fetchone()
            if row is None or row["revision"] != expected_revision:
                raise SourceConflict("revocation source revision CAS failed")
            metadata = self.metadata(db)
            job_id = None
            if not row["revoked"]:
                metadata["epoch"] += 1
                db.execute("UPDATE heads SET revoked=1 WHERE source_id=?", (source_id,))
                db.execute(
                    "INSERT OR IGNORE INTO withdrawals VALUES (?,?)",
                    (row["root"], metadata["epoch"]),
                )
                db.execute(
                    "UPDATE metadata SET value=? WHERE singleton=1",
                    (canonical(metadata).decode(),),
                )
                job_id = self._enqueue(db, metadata["epoch"])
            return WriteReceipt(
                "revoke",
                source_id,
                row["revision"],
                row["root"],
                metadata["epoch"],
                job_id,
            )
