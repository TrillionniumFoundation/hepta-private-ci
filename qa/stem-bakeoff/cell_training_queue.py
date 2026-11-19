"""Bounded SQLite training outbox with leases and generation-fenced publication.

The owner supplies trusted source identities. This is a same-host research
queue; it does not authenticate publishers or certify power-loss recovery.
"""

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


class TrainingQueueError(ValueError):
    pass


def _number(value, low=1, high=2**63 - 1):
    if type(value) is not int or not low <= value <= high:
        raise TrainingQueueError("bounded exact integer required")
    return value


def _sha(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise TrainingQueueError("source and feature identity must be SHA256")
    return value


def _blob(value, limit):
    if type(value) is not dict:
        raise TrainingQueueError("typed JSON object required")
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError) as error:
        raise TrainingQueueError("noncanonical training payload") from error
    if len(raw) > limit:
        raise TrainingQueueError("training payload or result exceeds byte quota")
    return raw


class TrainingQueue:
    """Persist work independently of workers; atomically publish current results."""

    def __init__(self, path, *, max_jobs=1024, max_payload_bytes=262144):
        self.path = Path(path)
        self.max_jobs = _number(max_jobs, 1, 65536)
        self.max_payload_bytes = _number(max_payload_bytes, 32, 2**24)
        if self.path.is_symlink() or not self.path.parent.is_dir():
            raise TrainingQueueError("owned database directory and non-symlink path required")
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS frontier (
              cell_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
              source_digest TEXT NOT NULL, feature_identity TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY, cell_id TEXT NOT NULL, generation INTEGER NOT NULL,
              source_digest TEXT NOT NULL, feature_identity TEXT NOT NULL,
              payload BLOB NOT NULL, deadline_ns INTEGER NOT NULL, created_ns INTEGER NOT NULL,
              status TEXT NOT NULL, lease_token TEXT, lease_until_ns INTEGER,
              attempts INTEGER NOT NULL DEFAULT 0, result BLOB, result_sha256 TEXT,
              UNIQUE(cell_id,generation));
            CREATE TABLE IF NOT EXISTS publication (
              cell_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, job_id TEXT NOT NULL,
              source_digest TEXT NOT NULL, feature_identity TEXT NOT NULL,
              result BLOB NOT NULL, result_sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY, latest_ns INTEGER NOT NULL);
            INSERT OR IGNORE INTO clock VALUES (1,0);
        """)

    def _begin(self, now_ns):
        now = _number(time.time_ns() if now_ns is None else now_ns)
        self.db.execute("BEGIN IMMEDIATE")
        previous = self.db.execute("SELECT latest_ns FROM clock WHERE id=1").fetchone()[0]
        if now < previous:
            self.db.rollback()
            raise TrainingQueueError("observed queue clock moved backwards")
        self.db.execute("UPDATE clock SET latest_ns=? WHERE id=1", (now,))
        return now

    def submit(self, cell_id, generation, source_digest, feature_identity, payload,
               *, deadline_ns, now_ns=None):
        if type(cell_id) is not str or not 1 <= len(cell_id) <= 256:
            raise TrainingQueueError("bounded Cell identity required")
        generation = _number(generation)
        source_digest, feature_identity = _sha(source_digest), _sha(feature_identity)
        deadline_ns, raw = _number(deadline_ns), _blob(payload, self.max_payload_bytes)
        job_id = hashlib.sha256(_blob({"cell": cell_id, "generation": generation,
            "source": source_digest, "feature": feature_identity,
            "payload_sha256": hashlib.sha256(raw).hexdigest(), "deadline": deadline_ns}, 4096)).hexdigest()
        now = self._begin(now_ns)
        try:
            if deadline_ns <= now:
                raise TrainingQueueError("new training job has already expired")
            frontier = self.db.execute("SELECT * FROM frontier WHERE cell_id=?", (cell_id,)).fetchone()
            if frontier and generation < frontier["generation"]:
                raise TrainingQueueError("stale source generation cannot be submitted")
            existing = self.db.execute("SELECT * FROM jobs WHERE cell_id=? AND generation=?",
                                       (cell_id, generation)).fetchone()
            if existing:
                if existing["job_id"] != job_id:
                    raise TrainingQueueError("same generation has different source, payload or deadline")
                self.db.commit()
                return job_id
            if frontier and generation <= frontier["generation"]:
                raise TrainingQueueError("stale source generation cannot be submitted")
            if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= self.max_jobs:
                raise TrainingQueueError("retained queue job quota exhausted")
            self.db.execute("UPDATE jobs SET status='superseded' WHERE cell_id=? AND status IN ('pending','running')",
                            (cell_id,))
            self.db.execute("INSERT OR REPLACE INTO frontier VALUES (?,?,?,?)",
                            (cell_id, generation, source_digest, feature_identity))
            self.db.execute("INSERT INTO jobs(job_id,cell_id,generation,source_digest,feature_identity,payload,"
                            "deadline_ns,created_ns,status) VALUES (?,?,?,?,?,?,?,?, 'pending')",
                            (job_id, cell_id, generation, source_digest, feature_identity, raw, deadline_ns, now))
            self.db.commit()
            return job_id
        except Exception:
            self.db.rollback()
            raise

    def claim(self, *, lease_ns=30_000_000_000, now_ns=None):
        lease_ns = _number(lease_ns, 1, 3_600_000_000_000)
        now = self._begin(now_ns)
        try:
            self.db.execute("UPDATE jobs SET status='expired' WHERE status IN ('pending','running') AND deadline_ns<=?", (now,))
            self.db.execute("UPDATE jobs SET status='pending',lease_token=NULL WHERE status='running' AND lease_until_ns<=?", (now,))
            row = self.db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created_ns,job_id LIMIT 1").fetchone()
            if row is None:
                self.db.commit()
                return None
            token = uuid.uuid4().hex
            until = min(row["deadline_ns"], now + lease_ns)
            self.db.execute("UPDATE jobs SET status='running',lease_token=?,lease_until_ns=?,attempts=attempts+1 WHERE job_id=?",
                            (token, until, row["job_id"]))
            self.db.commit()
            return {"job_id": row["job_id"], "cell_id": row["cell_id"],
                    "generation": row["generation"], "source_digest": row["source_digest"],
                    "feature_identity": row["feature_identity"], "payload": json.loads(row["payload"]),
                    "lease_token": token, "lease_until_ns": until, "attempt": row["attempts"] + 1}
        except Exception:
            self.db.rollback()
            raise

    def complete(self, job_id, lease_token, result, *, now_ns=None):
        _sha(job_id)
        raw = _blob(result, self.max_payload_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        now = self._begin(now_ns)
        try:
            row = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            frontier = None if row is None else self.db.execute(
                "SELECT * FROM frontier WHERE cell_id=?", (row["cell_id"],)).fetchone()
            current = row is not None and frontier is not None and all(
                row[key] == frontier[key] for key in ("generation", "source_digest", "feature_identity"))
            if (current and row["status"] == "done" and row["lease_token"] == lease_token
                    and row["result_sha256"] == digest and row["result"] == raw):
                self.db.commit()
                return digest
            if (row is None or frontier is None or row["status"] != "running"
                    or type(lease_token) is not str or row["lease_token"] != lease_token
                    or now >= row["lease_until_ns"] or now >= row["deadline_ns"]
                    or any(row[key] != frontier[key] for key in
                           ("generation", "source_digest", "feature_identity"))):
                raise TrainingQueueError("expired, superseded or foreign worker cannot publish")
            self.db.execute("UPDATE jobs SET status='done',result=?,result_sha256=? WHERE job_id=?",
                            (raw, digest, job_id))
            self.db.execute("INSERT OR REPLACE INTO publication VALUES (?,?,?,?,?,?,?)",
                            (row["cell_id"], row["generation"], job_id, row["source_digest"],
                             row["feature_identity"], raw, digest))
            self.db.commit()
            return digest
        except Exception:
            self.db.rollback()
            raise

    def read_current(self, cell_id):
        row = self.db.execute("SELECT p.* FROM publication p JOIN frontier f USING(cell_id) "
            "WHERE p.cell_id=? AND p.generation=f.generation AND p.source_digest=f.source_digest "
            "AND p.feature_identity=f.feature_identity", (cell_id,)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row["result"]).hexdigest() != row["result_sha256"]:
            raise TrainingQueueError("persisted publication bytes changed")
        return {k: json.loads(row[k]) if k == "result" else row[k] for k in row.keys()}

    def run_one(self, train, *, lease_ns=30_000_000_000):
        job = self.claim(lease_ns=lease_ns)
        if job is None:
            return None
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            result = train(job)
            result_sha = self.complete(job["job_id"], job["lease_token"], result)
        except Exception:
            self.db.execute("UPDATE jobs SET status='failed' WHERE job_id=? AND status='running' AND lease_token=?",
                            (job["job_id"], job["lease_token"]))
            raise
        return {"job_id": job["job_id"], "generation": job["generation"],
                "result_sha256": result_sha, "wall_ns": time.perf_counter_ns() - started,
                "cpu_ns": time.process_time_ns() - cpu}

    def accounting(self):
        states = dict(self.db.execute("SELECT status,count(*) FROM jobs GROUP BY status"))
        payload, result = self.db.execute("SELECT coalesce(sum(length(payload)),0),coalesce(sum(length(result)),0) FROM jobs").fetchone()
        files = [Path(str(self.path) + suffix) for suffix in ("", "-wal", "-shm")]
        return {"jobs_by_status": states, "payload_bytes": payload, "job_result_bytes": result,
                "database_files_bytes": sum(p.stat().st_size for p in files if p.exists()),
                "max_jobs": self.max_jobs, "max_payload_bytes": self.max_payload_bytes}

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
