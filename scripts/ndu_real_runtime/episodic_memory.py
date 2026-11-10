"""Bounded MEM6 source evidence with an explicit, current authority frontier.

Snapshots are portable read inputs, never an authority backup. Reusing the live
authority rejects stale versions and revoked dependencies. This is a research
store, not protection against an owner who rolls back or edits that authority.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote
import uuid


SCHEMA = "hepta.mem6.authority.v1"
SNAPSHOT_SCHEMA = "hepta.mem6.snapshot.v1"
PROVENANCE = {"source_uri", "source_sha256", "source_version", "episode_id"}
RECORD_FIELDS = {"namespace", "source_id", "key", "version", "text", "provenance",
                 "dependencies", "write_sequence", "record_id"}


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def bounded_text(value, name, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError(f"bounded nonempty {name} required")
    return value


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def sha256(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("canonical SHA-256 required")
    return value


def _validate_record_fields(record):
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        raise ValueError("invalid source record fields")
    for field in ("namespace", "source_id", "key"):
        bounded_text(record[field], field)
    bounded_text(record["text"], "record text", 4096)
    for field in ("version", "write_sequence"):
        integer(record[field], field, 1, 2**63 - 1)
    provenance = record["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE:
        raise ValueError("complete source provenance required")
    for field in PROVENANCE - {"source_sha256"}:
        bounded_text(provenance[field], field, 1024 if field == "source_uri" else 128)
    sha256(provenance["source_sha256"])
    dependencies = record["dependencies"]
    if not isinstance(dependencies, list) or len(dependencies) > 32:
        raise ValueError("bounded dependency roster required")
    for dependency in dependencies:
        sha256(dependency)
    if len(set(dependencies)) != len(dependencies):
        raise ValueError("duplicate dependency")
    sha256(record["record_id"])
    return record


def validate_record(record):
    _validate_record_fields(record)
    if record["record_id"] != digest({k: v for k, v in record.items() if k != "record_id"}):
        raise ValueError("record content digest mismatch")
    return record


class WorkingState:
    """Task-local values; switching session clears them and nothing is persisted."""

    def __init__(self, session_id, *, max_serialized_bytes=8192):
        self.limit = integer(max_serialized_bytes, "working-state bound", 2, 65536)
        self.session_id = None
        self._values = {}
        self.begin_session(session_id)

    def begin_session(self, session_id):
        bounded_text(session_id, "session id")
        if session_id != self.session_id:
            self._values = {}
            self.session_id = session_id

    def put(self, key, value):
        bounded_text(key, "working key")
        proposed = {**self._values, key: value}
        encoded = canonical_bytes(proposed)
        if len(encoded) > self.limit:
            raise ValueError("working-state byte bound exceeded")
        self._values = json.loads(encoded)

    def get(self, key):
        return json.loads(canonical_bytes(self._values.get(key)))


class EpisodicStore:
    """SQLite serializes atomic updates; tombstones count against admission caps.

    Scope is (namespace, source_id, key); a fact update advances its version and
    invalidates dependent facts transitively. No implicit tombstone eviction or
    authority restoration exists. Bounds measure logical serialized state.
    """

    def __init__(self, path, *, namespace, max_records=None,
                 max_serialized_bytes=None, create=True):
        self.path = Path(path).resolve()
        self.namespace = bounded_text(namespace, "namespace")
        fresh = not self.path.exists()
        if fresh and not create:
            raise ValueError("current authority is missing; refusing reconstruction")
        if fresh:
            count = integer(256 if max_records is None else max_records,
                            "record bound", 1, 4096)
            size = integer(1024**2 if max_serialized_bytes is None else max_serialized_bytes,
                           "serialized-byte bound", 1024, 16 * 1024**2)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.executescript("""
                    CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                    CREATE TABLE records (namespace TEXT, source_id TEXT, key TEXT,
                        version INTEGER, record_id TEXT, status TEXT, payload TEXT,
                        PRIMARY KEY(namespace, source_id, key));
                """)
                value = {"schema": SCHEMA, "authority_id": uuid.uuid4().hex,
                         "generation": 0, "max_records": count,
                         "max_serialized_bytes": size}
                db.execute("INSERT INTO meta VALUES (1, ?)", (canonical_bytes(value).decode(),))
        with self._transaction() as db:
            meta = self._meta(db)
        for name, requested in (("max_records", max_records),
                                ("max_serialized_bytes", max_serialized_bytes)):
            if requested is not None and requested != meta[name]:
                raise ValueError("existing authority bounds cannot be changed")
        self.max_records = meta["max_records"]
        self.max_serialized_bytes = meta["max_serialized_bytes"]

    @contextmanager
    def _transaction(self, *, write=False):
        uri = "file:" + quote(str(self.path), safe="/") + "?mode=rw"
        db = sqlite3.connect(uri, uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _meta(self, db):
        row = db.execute("SELECT value FROM meta WHERE id=1").fetchone()
        value = json.loads(row[0]) if row else {}
        if set(value) != {"schema", "authority_id", "generation", "max_records",
                          "max_serialized_bytes"} or value["schema"] != SCHEMA:
            raise ValueError("unknown authority schema")
        if re.fullmatch(r"[0-9a-f]{32}", value["authority_id"]) is None:
            raise ValueError("invalid authority identity")
        integer(value["generation"], "authority generation", 0, 2**63 - 1)
        integer(value["max_records"], "record bound", 1, 4096)
        integer(value["max_serialized_bytes"], "byte bound", 1024, 16 * 1024**2)
        return value

    def _rows(self, db):
        count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))),0) FROM records").fetchone()
        if count > self.max_records or size > self.max_serialized_bytes:
            raise ValueError("authority exceeds admission bounds")
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM records ORDER BY namespace, source_id, key")]
        for row in rows:
            integer(row["version"], "frontier version", 1, 2**63 - 1)
            sha256(row["record_id"])
            if row["status"] not in {"active", "revoked", "dependency_revoked"}:
                raise ValueError("invalid frontier status")
            if row["status"] == "active":
                record = validate_record(json.loads(row["payload"]))
                if any(record[k] != row[k] for k in ("namespace", "source_id", "key", "version", "record_id")):
                    raise ValueError("frontier and record disagree")
            elif row["payload"] is not None:
                raise ValueError("revoked payload must be removed")
        return rows

    def _finish(self, db, meta):
        meta["generation"] += 1
        integer(meta["generation"], "authority generation", 0, 2**63 - 1)
        rows = self._rows(db)
        if len(canonical_bytes({"meta": meta, "rows": rows})) > self.max_serialized_bytes:
            raise ValueError("serialized authority bound exceeded; mutation rolled back")
        db.execute("UPDATE meta SET value=? WHERE id=1", (canonical_bytes(meta).decode(),))

    def _dependency_descendants(self, rows, roots):
        """Active dependent IDs in O(records + declared edges), regardless of key order."""
        roots = set(roots)
        reverse = {}
        for row in rows:
            if row["namespace"] != self.namespace or row["status"] != "active":
                continue
            for dependency in json.loads(row["payload"])["dependencies"]:
                reverse.setdefault(dependency, []).append(row["record_id"])
        descendants, pending = set(), list(roots)
        while pending:
            for record_id in reverse.get(pending.pop(), ()):
                if record_id not in roots and record_id not in descendants:
                    descendants.add(record_id)
                    pending.append(record_id)
        return descendants

    def _invalidate(self, db, roots):
        rows = self._rows(db)
        affected = self._dependency_descendants(rows, roots)
        for row in rows:
            if (row["namespace"] == self.namespace and row["status"] == "active"
                    and row["record_id"] in affected):
                db.execute("UPDATE records SET version=version+1, status='dependency_revoked', payload=NULL WHERE namespace=? AND source_id=? AND key=?",
                           (self.namespace, row["source_id"], row["key"]))
        return sorted(affected)

    def put(self, source_id, key, text, *, provenance, dependencies=()):
        """Admit copied source evidence, never evaluator answers or learned weights."""
        bounded_text(source_id, "source id")
        bounded_text(key, "fact key")
        if not isinstance(dependencies, (tuple, list)):
            raise ValueError("dependency roster required")
        with self._transaction(write=True) as db:
            meta, rows = self._meta(db), self._rows(db)
            old = next((r for r in rows if (r["namespace"], r["source_id"], r["key"]) ==
                        (self.namespace, source_id, key)), None)
            record = {"namespace": self.namespace, "source_id": source_id, "key": key,
                      "version": 1 if old is None else old["version"] + 1,
                      "text": text, "provenance": provenance,
                      "dependencies": list(dependencies), "write_sequence": meta["generation"] + 1}
            record["record_id"] = "0" * 64
            _validate_record_fields(record)
            record["record_id"] = digest({k: v for k, v in record.items() if k != "record_id"})
            active = {r["record_id"] for r in rows
                      if r["namespace"] == self.namespace and r["status"] == "active"}
            if not set(dependencies) <= active or (old and old["record_id"] in dependencies):
                raise ValueError("dependencies must reference other current in-namespace facts")
            if old:
                invalid = {old["record_id"]} | self._dependency_descendants(
                    rows, [old["record_id"]]
                )
                if invalid.intersection(dependencies):
                    raise ValueError("update cannot depend on facts it would invalidate")
            db.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, 'active', ?) ON CONFLICT(namespace,source_id,key) DO UPDATE SET version=excluded.version,record_id=excluded.record_id,status='active',payload=excluded.payload",
                       (self.namespace, source_id, key, record["version"], record["record_id"],
                        canonical_bytes(record).decode()))
            if old:
                self._invalidate(db, [old["record_id"]])
            self._finish(db, meta)
        return json.loads(canonical_bytes(record))

    def revoke(self, source_id, key):
        """Remove current payload and transitively revoke its dependent payloads."""
        bounded_text(source_id, "source id")
        bounded_text(key, "fact key")
        with self._transaction(write=True) as db:
            meta, rows = self._meta(db), self._rows(db)
            row = next((r for r in rows if (r["namespace"], r["source_id"], r["key"]) ==
                        (self.namespace, source_id, key)), None)
            if row is None:
                raise ValueError("unknown fact cannot be revoked")
            if row["status"] != "active":
                return {"status": "already_revoked", "affected_ids": []}
            db.execute("UPDATE records SET version=version+1, status='revoked', payload=NULL WHERE namespace=? AND source_id=? AND key=?",
                       (self.namespace, source_id, key))
            affected = [row["record_id"], *self._invalidate(db, [row["record_id"]])]
            self._finish(db, meta)
        return {"status": "revoked", "affected_ids": affected}

    def view(self, snapshot_path=None):
        """Read live records or filter a snapshot through the current frontier."""
        with self._transaction() as db:
            meta, rows = self._meta(db), self._rows(db)
            relevant = [r for r in rows if r["namespace"] == self.namespace]
            current = {r["record_id"]: json.loads(r["payload"])
                       for r in relevant if r["status"] == "active"}
            if any(not set(r["dependencies"]) <= current.keys() for r in current.values()):
                raise ValueError("active record has a stale dependency")
            records, rejected, snapshot_sha = list(current.values()), 0, None
            if snapshot_path is not None:
                with Path(snapshot_path).open("rb") as stream:
                    raw = stream.read(self.max_serialized_bytes + 4097)
                if len(raw) > self.max_serialized_bytes + 4096:
                    raise ValueError("snapshot exceeds byte bound")
                envelope = json.loads(raw)
                if not isinstance(envelope, dict) or set(envelope) != {"body", "sha256"}:
                    raise ValueError("invalid snapshot envelope")
                body = envelope["body"]
                if envelope["sha256"] != digest(body) or set(body) != {
                    "schema", "authority_id", "namespace", "generation", "records"
                } or body["schema"] != SNAPSHOT_SCHEMA:
                    raise ValueError("invalid snapshot digest or schema")
                if body["authority_id"] != meta["authority_id"] or body["namespace"] != self.namespace:
                    raise ValueError("snapshot authority or namespace mismatch")
                integer(body["generation"], "snapshot generation", 0, meta["generation"])
                if not isinstance(body["records"], list) or len(body["records"]) > self.max_records:
                    raise ValueError("snapshot record bound exceeded")
                candidates = [validate_record(r) for r in body["records"]]
                if len({r["record_id"] for r in candidates}) != len(candidates):
                    raise ValueError("duplicate snapshot record")
                records = [r for r in candidates if current.get(r["record_id"]) == r]
                rejected, snapshot_sha = len(candidates) - len(records), envelope["sha256"]
            records.sort(key=lambda r: (r["write_sequence"], r["record_id"]))
            frontier = [{k: v for k, v in r.items() if k != "payload"} for r in relevant]
            return {"records": records, "receipt": {
                "authority_id": meta["authority_id"], "authority_generation": meta["generation"],
                "frontier_sha256": digest(frontier), "snapshot_sha256": snapshot_sha,
                "snapshot_rejections": rejected, "resident_record_count": len(current),
                "logical_serialized_bytes": len(canonical_bytes({"meta": meta, "rows": rows})),
                "scientific_acceptance": "HOLD", "malicious_owner_rollback_protected": False,
            }}

    def export_snapshot(self, path):
        """Atomically save a data snapshot; retain the authority separately."""
        view = self.view()
        body = {"schema": SNAPSHOT_SCHEMA, "authority_id": view["receipt"]["authority_id"],
                "namespace": self.namespace, "generation": view["receipt"]["authority_generation"],
                "records": view["records"]}
        encoded = canonical_bytes({"body": body, "sha256": digest(body)})
        path = Path(path).resolve()
        if path == self.path:
            raise ValueError("snapshot must not replace its authority")
        path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                name = stream.name
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
        return {"path": str(path), "snapshot_sha256": digest(body), "records": len(view["records"])}
