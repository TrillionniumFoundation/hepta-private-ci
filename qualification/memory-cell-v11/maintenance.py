"""Persistent evidence ledger and bounded, incremental training replay.

The archive and its lineage grow with accepted evidence; only the pending queue,
replay hot set, and training batches are bounded.  The bottom-k replay set uses an
indexed deterministic random priority.  Ordinary sampling never enumerates the
active archive.  Models must train a shadow copy and publish only after commit.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import time
import uuid


class StaleTraining(RuntimeError):
    """The lease, source records, or parent model is no longer current."""


class ReplayBackpressure(RuntimeError):
    """The durable queue is full; the producer must let training catch up."""


@dataclass(frozen=True)
class ReplayBatch:
    token: str
    records: tuple
    pending_ids: tuple
    replay_ids: tuple
    watermark: int
    expires_at: float


def artifact_identity(path):
    """Hash the actual checkpoint bytes, including relative filenames."""
    path = Path(path)
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        raise ValueError("checkpoint artifact is empty or absent")
    digest, size = hashlib.sha256(), 0
    for file in files:
        name = file.name if path.is_file() else file.relative_to(path).as_posix()
        digest.update(name.encode() + b"\0")
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
    return digest.hexdigest(), size


class SQLiteReplayStore:
    def __init__(self, path, *, replay_capacity=64, pending_capacity=1024,
                 max_batch_size=128, seed=0):
        if replay_capacity < 0 or pending_capacity < 1 or max_batch_size < 1:
            raise ValueError("invalid replay limits")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records(
                id INTEGER PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL,
                key TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                digest TEXT NOT NULL, priority INTEGER NOT NULL, status TEXT NOT NULL,
                UNIQUE(scope,kind,key,version));
            CREATE INDEX IF NOT EXISTS active_priority ON records(priority,id) WHERE status='active';
            CREATE INDEX IF NOT EXISTS active_ids ON records(id) WHERE status='active';
            CREATE TABLE IF NOT EXISTS record_sources(
                record_id INTEGER NOT NULL REFERENCES records(id), source_id TEXT NOT NULL,
                PRIMARY KEY(record_id,source_id));
            CREATE INDEX IF NOT EXISTS source_records ON record_sources(source_id,record_id);
            CREATE TABLE IF NOT EXISTS dependencies(
                parent INTEGER NOT NULL REFERENCES records(id), child INTEGER NOT NULL REFERENCES records(id),
                PRIMARY KEY(parent,child));
            CREATE TABLE IF NOT EXISTS source_tombstones(source_id TEXT PRIMARY KEY, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS key_tombstones(
                scope TEXT, kind TEXT, key TEXT, reason TEXT NOT NULL, PRIMARY KEY(scope,kind,key));
            CREATE TABLE IF NOT EXISTS pending(
                record_id INTEGER PRIMARY KEY REFERENCES records(id), token TEXT, deadline REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS pending_deadline ON pending(deadline,record_id);
            CREATE TABLE IF NOT EXISTS replay(record_id INTEGER PRIMARY KEY REFERENCES records(id), priority INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS replay_priority ON replay(priority,record_id);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, action TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(
                id TEXT PRIMARY KEY, parent TEXT REFERENCES checkpoints(id), path TEXT NOT NULL,
                digest TEXT NOT NULL, bytes INTEGER NOT NULL, valid INTEGER NOT NULL, reason TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS checkpoint_parent ON checkpoints(parent,id);
            CREATE TABLE IF NOT EXISTS checkpoint_records(
                checkpoint_id TEXT NOT NULL REFERENCES checkpoints(id), record_id INTEGER NOT NULL REFERENCES records(id),
                PRIMARY KEY(checkpoint_id,record_id));
            CREATE INDEX IF NOT EXISTS record_checkpoints ON checkpoint_records(record_id,checkpoint_id);
            CREATE TEMP TABLE IF NOT EXISTS affected(id INTEGER PRIMARY KEY);
        """)
        settings = dict(replay_capacity=replay_capacity, pending_capacity=pending_capacity,
                        max_batch_size=max_batch_size, seed=seed, schema=1)
        with self.transaction():
            for key, value in settings.items():
                found = self.db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
                if found and int(found[0]) != value:
                    raise ValueError(f"persistent configuration mismatch: {key}")
                self.db.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (key, str(value)))
            self.db.execute("INSERT OR IGNORE INTO config VALUES ('sample_tick','0')")
        self.capacity, self.pending_capacity = replay_capacity, pending_capacity
        self.max_batch_size, self.seed = max_batch_size, seed

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def _event(self, action, details):
        return self.db.execute("INSERT INTO events(action,details) VALUES (?,?)",
                               (action, json.dumps(details, sort_keys=True))).lastrowid

    def _invalidate(self, root_query, parameters, reason):
        self.db.execute("DELETE FROM affected")
        self.db.execute(f"""WITH RECURSIVE descendants(id) AS (
            {root_query} UNION SELECT d.child FROM dependencies d JOIN descendants a ON d.parent=a.id)
            INSERT INTO affected SELECT id FROM descendants""", parameters)
        count = self.db.execute("SELECT count(*) FROM affected").fetchone()[0]
        status = "superseded" if reason == "superseded" else "revoked"
        self.db.execute("UPDATE records SET status=? WHERE id IN (SELECT id FROM affected)", (status,))
        for table in ("pending", "replay"):
            self.db.execute(f"DELETE FROM {table} WHERE record_id IN (SELECT id FROM affected)")
        self.db.execute("""WITH RECURSIVE invalid(id) AS (
            SELECT cr.checkpoint_id FROM checkpoint_records cr JOIN affected a ON cr.record_id=a.id
            UNION SELECT c.id FROM checkpoints c JOIN invalid i ON c.parent=i.id)
            UPDATE checkpoints SET valid=0,reason=? WHERE id IN (SELECT id FROM invalid)""", (reason,))
        return count

    def _refill(self):
        missing = self.capacity - self.db.execute("SELECT count(*) FROM replay").fetchone()[0]
        if missing:
            self.db.execute("""INSERT INTO replay SELECT id,priority FROM records
                INDEXED BY active_priority WHERE status='active'
                AND id NOT IN (SELECT record_id FROM replay) ORDER BY priority,id LIMIT ?""", (missing,))

    def append(self, record, *, parent_ids=()):
        """Append a strictly newer fact; supersession invalidates derived models."""
        value = dict(record)
        scope, kind, key = str(value.get("scope", "default")), str(value["type"]), str(value["key"])
        version, sources = int(value["version"]), tuple(sorted(set(value["source_ids"])))
        if not key or version < 1 or not sources or any(not isinstance(s, str) or not s for s in sources):
            raise ValueError("records require a key, positive version, and explicit source_ids")
        value.update(scope=scope, type=kind, key=key, version=version, source_ids=list(sources))
        parent_ids = tuple(sorted(set(int(i) for i in parent_ids)))
        value["parent_ids"] = list(parent_ids)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        identity = json.dumps([self.seed, scope, kind, key, version], separators=(",", ":"))
        priority = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big") >> 1
        with self.transaction():
            if self.db.execute("SELECT 1 FROM key_tombstones WHERE scope=? AND kind=? AND key=?", (scope, kind, key)).fetchone():
                raise ValueError("deleted key cannot be resurrected")
            for source in sources:
                if self.db.execute("SELECT 1 FROM source_tombstones WHERE source_id=?", (source,)).fetchone():
                    raise ValueError("revoked source cannot be reused")
            for parent in parent_ids:
                row = self.db.execute("SELECT status FROM records WHERE id=?", (parent,)).fetchone()
                if not row or row[0] != "active":
                    raise ValueError("derived records require active parents")
            old = self.db.execute("""SELECT id,version,digest,status FROM records
                WHERE scope=? AND kind=? AND key=? ORDER BY version DESC LIMIT 1""", (scope, kind, key)).fetchone()
            if old and version <= old["version"]:
                if version == old["version"] and digest == old["digest"] and old["status"] == "active":
                    return old["id"]
                raise ValueError("version must increase; replay is idempotent only for identical active records")
            if old:
                self._invalidate("SELECT id FROM records WHERE id=?", (old["id"],), "superseded")
                for parent in parent_ids:
                    if self.db.execute("SELECT status FROM records WHERE id=?", (parent,)).fetchone()[0] != "active":
                        raise ValueError("supersession would invalidate a declared parent")
            if self.db.execute("SELECT count(*) FROM pending").fetchone()[0] >= self.pending_capacity:
                raise ReplayBackpressure("pending capacity reached")
            record_id = self.db.execute("""INSERT INTO records(scope,kind,key,version,payload,digest,priority,status)
                VALUES (?,?,?,?,?,?,?,'active')""", (scope, kind, key, version, payload, digest, priority)).lastrowid
            self.db.executemany("INSERT INTO record_sources VALUES (?,?)", [(record_id, source) for source in sources])
            self.db.executemany("INSERT INTO dependencies VALUES (?,?)", [(parent, record_id) for parent in parent_ids])
            self.db.execute("INSERT INTO pending(record_id) VALUES (?)", (record_id,))
            if self.capacity:
                worst = self.db.execute("SELECT record_id,priority FROM replay ORDER BY priority DESC,record_id DESC LIMIT 1").fetchone()
                full = self.db.execute("SELECT count(*) FROM replay").fetchone()[0] == self.capacity
                if full and (priority, record_id) < (worst["priority"], worst["record_id"]):
                    self.db.execute("DELETE FROM replay WHERE record_id=?", (worst["record_id"],))
                self._refill()
            self._event("append", dict(record_id=record_id, version=version, previous=old["id"] if old else None))
        return record_id

    def revoke_source(self, source_id, reason="source_revoked"):
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO source_tombstones VALUES (?,?)", (source_id, reason))
            count = self._invalidate("SELECT record_id FROM record_sources WHERE source_id=?", (source_id,), reason)
            self._refill()
            self._event("revoke_source", dict(source_id=source_id, affected=count, reason=reason))
        return count

    def delete_key(self, key, kind, *, scope="default", reason="deleted"):
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO key_tombstones VALUES (?,?,?,?)", (scope, kind, key, reason))
            count = self._invalidate("SELECT id FROM records WHERE scope=? AND kind=? AND key=?", (scope, kind, key), reason)
            self._refill()
            self._event("delete_key", dict(scope=scope, type=kind, key=key, affected=count, reason=reason))
        return count

    def current(self, key, kind, *, scope="default"):
        row = self.db.execute("""SELECT id,payload FROM records WHERE scope=? AND kind=? AND key=?
            AND status='active' ORDER BY version DESC LIMIT 1""", (scope, kind, key)).fetchone()
        return dict(json.loads(row["payload"]), record_id=row["id"]) if row else None

    def active_page(self, *, after_id=0, limit=64):
        """Bounded cursor for an explicit clean rebuild, never an implicit replay scan."""
        if not 0 < limit <= self.max_batch_size:
            raise ValueError("rebuild page exceeds batch bound")
        rows = self.db.execute("""SELECT id,payload FROM records INDEXED BY active_ids
            WHERE status='active' AND id>? ORDER BY id LIMIT ?""", (after_id, limit)).fetchall()
        return [dict(json.loads(row["payload"]), record_id=row["id"]) for row in rows]

    def claim_batch(self, *, new_count=8, replay_count=24, lease_seconds=300):
        """Lease bounded new work plus a bounded sample of the persistent hot set."""
        if new_count < 1 or replay_count < 0 or new_count + replay_count > self.max_batch_size or lease_seconds <= 0:
            raise ValueError("invalid batch bounds")
        now, token = time.time(), uuid.uuid4().hex
        with self.transaction():
            fresh = tuple(row[0] for row in self.db.execute("""SELECT record_id FROM pending
                WHERE deadline<=? ORDER BY deadline,record_id LIMIT ?""", (now, new_count)))
            if not fresh:
                return None
            available = [row[0] for row in self.db.execute("SELECT record_id FROM replay ORDER BY priority,record_id") if row[0] not in fresh]
            tick = int(self.db.execute("SELECT value FROM config WHERE key='sample_tick'").fetchone()[0])
            replay = tuple(random.Random(self.seed + tick).sample(available, min(replay_count, len(available))))
            self.db.execute("UPDATE config SET value=? WHERE key='sample_tick'", (str(tick + 1),))
            self.db.executemany("UPDATE pending SET token=?,deadline=? WHERE record_id=?", [(token, now + lease_seconds, i) for i in fresh])
            records = []
            for record_id in fresh + replay:
                row = self.db.execute("SELECT payload FROM records WHERE id=? AND status='active'", (record_id,)).fetchone()
                if not row:
                    raise StaleTraining("replay contains inactive evidence")
                records.append(dict(json.loads(row[0]), record_id=record_id))
            watermark = self.db.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0]
        return ReplayBatch(token, tuple(records), fresh, replay, watermark, now + lease_seconds)

    def claim_rebuild_page(self, *, after_id=0, limit=64, lease_seconds=300):
        """Explicit clean-rebuild work when a revocation leaves no pending insert.

        This cursor reads only current sources.  It does not claim that a caller
        actually reset the model; the fit's initialization identity must prove
        that separately.  A crash restarts the caller's clean rebuild.
        """
        if lease_seconds <= 0:
            raise ValueError("invalid rebuild lease")
        with self.transaction():
            rows = self.active_page(after_id=after_id, limit=limit)
            if not rows:
                return None
            watermark = self.db.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0]
        return ReplayBatch(uuid.uuid4().hex, tuple(rows), (), tuple(r["record_id"] for r in rows),
                           watermark, time.time() + lease_seconds)

    def _validate_batch(self, batch, parent_checkpoint):
        if not batch.records or len(batch.records) > self.max_batch_size:
            raise StaleTraining("training batch exceeds its declared bound")
        if time.time() > batch.expires_at:
            raise StaleTraining("training lease expired")
        for record in batch.records:
            found = self.db.execute("SELECT status,payload FROM records WHERE id=?", (record["record_id"],)).fetchone()
            if not found or found["status"] != "active":
                raise StaleTraining("training evidence was superseded or revoked")
            if record != dict(json.loads(found["payload"]), record_id=record["record_id"]):
                raise StaleTraining("training record differs from its durable evidence")
        for record_id in batch.pending_ids:
            found = self.db.execute("SELECT token FROM pending WHERE record_id=?", (record_id,)).fetchone()
            if not found or found[0] != batch.token:
                raise StaleTraining("training lease was replaced")
        if parent_checkpoint:
            found = self.db.execute("SELECT valid FROM checkpoints WHERE id=?", (parent_checkpoint,)).fetchone()
            if not found or not found[0]:
                raise StaleTraining("parent checkpoint is absent or invalid")

    def commit_training(self, batch, checkpoint_id, artifact_path, *, parent_checkpoint=None):
        """Atomically bind a shadow checkpoint to current evidence and consume work."""
        digest, size = artifact_identity(artifact_path)
        with self.transaction():
            self._validate_batch(batch, parent_checkpoint)
            self.db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,1,'current')",
                            (checkpoint_id, parent_checkpoint, str(Path(artifact_path).resolve()), digest, size))
            self.db.executemany("INSERT INTO checkpoint_records VALUES (?,?)", [(checkpoint_id, r["record_id"]) for r in batch.records])
            self.db.executemany("DELETE FROM pending WHERE record_id=? AND token=?", [(i, batch.token) for i in batch.pending_ids])
            self._event("training_commit", dict(checkpoint_id=checkpoint_id, batch_size=len(batch.records), artifact_sha256=digest))
        return dict(checkpoint_id=checkpoint_id, artifact_sha256=digest, artifact_bytes=size, trained_records=len(batch.records))

    def release(self, batch):
        with self.transaction():
            self.db.execute("UPDATE pending SET token=NULL,deadline=0 WHERE token=?", (batch.token,))

    def checkpoint_is_valid(self, checkpoint_id, *, verify_artifact=True):
        row = self.db.execute("SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,)).fetchone()
        if not row or not row["valid"]:
            return False
        if not verify_artifact:
            return True
        try:
            return artifact_identity(row["path"])[0] == row["digest"]
        except (OSError, ValueError):
            return False

    def stats(self):
        """Explicit accounting scan; this is not part of the training hot path."""
        result = {"schema": "hepta.memory.v11.replay-stats.v1", "archive_is_unbounded": True,
                  "replay_capacity": self.capacity, "pending_capacity": self.pending_capacity,
                  "max_batch_size": self.max_batch_size}
        for table in ("records", "replay", "pending", "checkpoints", "events"):
            result[f"{table}_count"] = self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        result["active_records"] = self.db.execute("SELECT count(*) FROM records WHERE status='active'").fetchone()[0]
        result["archive_payload_bytes"] = self.db.execute("SELECT coalesce(sum(length(CAST(payload AS BLOB))),0) FROM records").fetchone()[0]
        result["replay_payload_bytes"] = self.db.execute("SELECT coalesce(sum(length(CAST(r.payload AS BLOB))),0) FROM records r JOIN replay b ON r.id=b.record_id").fetchone()[0]
        result["database_bytes"] = sum(p.stat().st_size for p in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")) if p.exists())
        result["invalid_checkpoints"] = self.db.execute("SELECT count(*) FROM checkpoints WHERE valid=0").fetchone()[0]
        return result
