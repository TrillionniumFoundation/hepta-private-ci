"""Single-writer SQLite event owner with immutable revisions and revocations."""

import json
from pathlib import Path
import sqlite3

from .contracts import KINDS, bounded_text, canonical, digest, integer
from .values import validate_typed_value


class StaleSource(ValueError):
    """Source or artifact no longer belongs to the admitted coherent cut."""


class EventStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL);
            INSERT OR IGNORE INTO clock VALUES (1,0);
            CREATE TABLE IF NOT EXISTS records (
                source_id TEXT PRIMARY KEY, seq INTEGER UNIQUE NOT NULL,
                scope TEXT NOT NULL, entity TEXT NOT NULL, kind TEXT NOT NULL,
                effective_at INTEGER NOT NULL, payload TEXT NOT NULL, value_digest TEXT NOT NULL,
                origin_id TEXT NOT NULL, predecessor TEXT);
            CREATE INDEX IF NOT EXISTS record_lookup ON records(scope, entity, kind, effective_at, seq);
            CREATE TABLE IF NOT EXISTS revocations (
                source_id TEXT PRIMARY KEY REFERENCES records(source_id),
                seq INTEGER UNIQUE NOT NULL, reason TEXT NOT NULL);
        """)

    @property
    def cut(self):
        return self.db.execute("SELECT seq FROM clock WHERE id=1").fetchone()[0]

    def _advance(self):
        self.db.execute("UPDATE clock SET seq=seq+1 WHERE id=1")
        return self.cut

    def append(self, *, scope, entity, kind, effective_at, value, origin_id, predecessor=None):
        if not all(bounded_text(x) for x in (scope, entity, origin_id)) or kind not in KINDS:
            raise ValueError("invalid source identity/type")
        if not integer(effective_at, 0, 2**53 - 1):
            raise ValueError("invalid source time")
        validate_typed_value(kind, value)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if predecessor is not None:
                prior = self.record(predecessor)
                if (prior["scope"], prior["entity"], prior["kind"]) != (scope, entity, kind):
                    raise ValueError("correction crosses source ownership")
                if prior["effective_at"] != effective_at:
                    raise ValueError("correction must retain the original effective time")
            seq = self._advance()
            fields = dict(
                seq=seq,
                scope=scope,
                entity=entity,
                kind=kind,
                effective_at=effective_at,
                value_digest=digest(value),
                origin_id=origin_id,
                predecessor=predecessor,
            )
            source_id = digest(fields)
            self.db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    seq,
                    scope,
                    entity,
                    kind,
                    effective_at,
                    canonical(value).decode(),
                    fields["value_digest"],
                    origin_id,
                    predecessor,
                ),
            )
            self.db.execute("COMMIT")
            return source_id
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def record(self, source_id):
        row = self.db.execute("SELECT * FROM records WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise StaleSource("unknown source")
        result = dict(
            zip(
                (
                    "source_id",
                    "seq",
                    "scope",
                    "entity",
                    "kind",
                    "effective_at",
                    "payload",
                    "value_digest",
                    "origin_id",
                    "predecessor",
                ),
                row,
            )
        )
        result["value"] = json.loads(result.pop("payload"))
        validate_typed_value(result["kind"], result["value"])
        fields = {key: value for key, value in result.items() if key not in {"source_id", "value"}}
        if digest(result["value"]) != result["value_digest"] or digest(fields) != source_id:
            raise StaleSource("source content identity mismatch")
        return result

    def revoke(self, source_id, reason):
        if not bounded_text(reason, 1024):
            raise ValueError("invalid revocation reason")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.record(source_id)
            if self.db.execute("SELECT 1 FROM revocations WHERE source_id=?", (source_id,)).fetchone():
                self.db.execute("COMMIT")
                return self.cut
            seq = self._advance()
            self.db.execute("INSERT INTO revocations VALUES (?,?,?)", (source_id, seq, reason))
            self.db.execute("COMMIT")
            return seq
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def validate_support(self, source_ids, *, scope, cut, expected_entity=None, expected_kind=None):
        if cut > self.cut or not integer(cut, 0, 2**53 - 1):
            raise StaleSource("unknown source cut")
        for source_id in set(source_ids):
            # A parameter read validates provenance without selecting the payload.
            fields = ("seq", "scope", "entity", "kind", "effective_at", "value_digest", "origin_id", "predecessor")
            raw = self.db.execute(
                "SELECT " + ",".join(fields) + " FROM records WHERE source_id=?", (source_id,)
            ).fetchone()
            if raw is None:
                raise StaleSource("unknown source")
            row = dict(zip(fields, raw))
            if digest(row) != source_id:
                raise StaleSource("source metadata identity mismatch")
            if row["scope"] != scope or row["seq"] > cut:
                raise StaleSource("source scope/cut differs")
            if expected_entity is not None and row["entity"] != expected_entity:
                raise StaleSource("source entity differs")
            if expected_kind is not None and row["kind"] != expected_kind:
                raise StaleSource("source type differs")
            if self.db.execute("SELECT 1 FROM revocations WHERE source_id=?", (source_id,)).fetchone():
                raise StaleSource("source revoked, including after snapshot creation")

    def resolve(self, scope, entity, kind, *, at, cut):
        row = self.db.execute(
            "SELECT source_id FROM records WHERE scope=? AND entity=? AND kind=? AND effective_at<=? AND seq<=? ORDER BY effective_at DESC,seq DESC LIMIT 1",
            (scope, entity, kind, at, cut),
        ).fetchone()
        if row is None:
            raise StaleSource("no applicable event")
        # Never fall back to an older record when the selected revision was revoked.
        self.validate_support([row[0]], scope=scope, cut=cut)
        return self.record(row[0])

    def rows(self, scope, kind, *, at=2**53 - 1, cut=None):
        cut = self.cut if cut is None else cut
        entities = [
            row[0]
            for row in self.db.execute(
                "SELECT DISTINCT entity FROM records WHERE scope=? AND kind=? AND seq<=?", (scope, kind, cut)
            )
        ]
        result = []
        for entity in sorted(entities):
            selected = self.db.execute(
                "SELECT source_id FROM records WHERE scope=? AND entity=? AND kind=? AND effective_at<=? AND seq<=? ORDER BY effective_at DESC,seq DESC LIMIT 1",
                (scope, entity, kind, at, cut),
            ).fetchone()
            if selected is None or self.db.execute("SELECT 1 FROM revocations WHERE source_id=?", selected).fetchone():
                continue
            result.append(self.resolve(scope, entity, kind, at=at, cut=cut))
        return result

    def frontier(self, scope, cut=None):
        cut = self.cut if cut is None else cut
        records = [
            x[0]
            for x in self.db.execute(
                "SELECT source_id FROM records WHERE scope=? AND seq<=? ORDER BY seq", (scope, cut)
            )
        ]
        revoked = [x[0] for x in self.db.execute("SELECT source_id FROM revocations WHERE seq<=? ORDER BY seq", (cut,))]
        return digest(dict(scope=scope, cut=cut, records=records, revoked=revoked))

    def close(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
