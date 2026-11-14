"""Restartable training leases; expired workers cannot stage or publish outputs."""

from dataclasses import dataclass
import json
import math
import secrets
import time

from service_types import LeaseLost, canonical, identifier, verify_snapshot


@dataclass(frozen=True)
class TrainingLease:
    job_id: int
    token: str
    attempt: int
    snapshot: dict
    candidate: dict | None


def clock(value=None):
    value = time.time() if value is None else value
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative lease clock required")
    return value


class TrainingQueue:
    """The source transaction enqueues; one fenced worker claims each job."""

    def __init__(self, store, max_attempts=3):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 16:
            raise ValueError("bounded training retry count required")
        self.store, self.max_attempts = store, max_attempts

    def claim(self, worker_id, lease_seconds=3600, now=None):
        identifier(worker_id)
        now = clock(now)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 86400:
            raise ValueError("bounded lease duration required")
        with self.store.transaction() as db:
            epoch = self.store.metadata(db)["epoch"]
            db.execute(
                "UPDATE jobs SET state=CASE WHEN epoch<>? THEN 'superseded' "
                "WHEN attempt>=? THEN 'failed' ELSE 'queued' END, "
                "error='worker lease expired' WHERE state='running' AND deadline<=?",
                (epoch, self.max_attempts, now),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY epoch DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            snapshot = verify_snapshot(json.loads(row["snapshot"]))
            if (
                snapshot["epoch"] != epoch
                or snapshot["scope"] != self.store.scope
                or snapshot["cell_id"] != self.store.cell_id
                or snapshot["role"] != self.store.role
            ):
                raise ValueError("queued source identity differs from owner")
            token = secrets.token_hex(24)
            attempt = row["attempt"] + 1
            db.execute(
                "UPDATE jobs SET state='running',attempt=?,worker=?,token=?,deadline=? WHERE id=?",
                (attempt, worker_id, token, now + lease_seconds, row["id"]),
            )
            return TrainingLease(
                row["id"],
                token,
                attempt,
                snapshot,
                json.loads(row["candidate"]) if row["candidate"] else None,
            )

    def check(self, db, lease, now=None):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (lease.job_id,)).fetchone()
        if (
            row is None
            or row["state"] != "running"
            or row["token"] != lease.token
            or row["attempt"] != lease.attempt
            or row["deadline"] <= clock(now)
        ):
            raise LeaseLost("training lease is expired, superseded or owned elsewhere")
        snapshot = verify_snapshot(json.loads(row["snapshot"]))
        if snapshot != lease.snapshot:
            raise ValueError("worker training snapshot differs from sealed job")
        return row

    def renew(self, lease, lease_seconds=3600, now=None):
        now = clock(now)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 86400:
            raise ValueError("bounded lease duration required")
        with self.store.transaction() as db:
            self.check(db, lease, now)
            db.execute(
                "UPDATE jobs SET deadline=? WHERE id=?",
                (now + lease_seconds, lease.job_id),
            )

    def stage(self, lease, candidate, now=None):
        if type(candidate) is not dict or len(canonical(candidate)) > 16384:
            raise ValueError("bounded candidate metadata required")
        if candidate.get("source_snapshot_digest") != lease.snapshot["digest"]:
            raise ValueError(
                "candidate was not trained for the claimed source snapshot"
            )
        with self.store.transaction() as db:
            row = self.check(db, lease, now)
            if row["candidate"] and json.loads(row["candidate"]) != candidate:
                raise ValueError("staged candidate is immutable")
            db.execute(
                "UPDATE jobs SET candidate=? WHERE id=?",
                (canonical(candidate).decode(), lease.job_id),
            )

    def fail(self, lease, error, now=None):
        with self.store.transaction() as db:
            row = self.check(db, lease, now)
            if self.store.metadata(db)["epoch"] != lease.snapshot["epoch"]:
                state = "superseded"
            elif row["candidate"] and lease.attempt < self.max_attempts:
                # Publication may have committed in the other owner DB. Keep
                # the exact staged bytes so a fresh fenced attempt reconciles.
                state = "queued"
            else:
                state = "failed"
            db.execute(
                "UPDATE jobs SET state=?,error=? WHERE id=?",
                (state, str(error)[:1024], lease.job_id),
            )

    def status(self, job_id):
        if type(job_id) is not int or job_id <= 0:
            raise ValueError("positive job identity required")
        with self.store.transaction(write=False) as db:
            row = db.execute(
                "SELECT id,epoch,state,attempt,worker,deadline,candidate,error FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None
