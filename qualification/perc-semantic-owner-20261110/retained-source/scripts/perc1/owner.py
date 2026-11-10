"""Durable local POSIX capture owner; reservations precede external effects.

The operator supplies the grant, source frontier and model binding. A journal is
not permission or origin attestation. SQLite FULL synchronization and a lifetime
flock serialize cooperating writers on one local store; copied stores and remote
actors are not fenced. Acquisition units bound admitted attempts, not wall time,
energy, provider billing, or arbitrary callback effects. UNKNOWN holds its units.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .schema import Invalid, canonical, digest, exact, identifier, integer, require, sha

MAX_REQUEST_BYTES = 65536
MAX_RECEIPT_BYTES = 1024 * 1024


class UnknownOutcome(Invalid):
    """Dispatch was durable but no receipt survived; never automatically retry."""


def _json(raw):
    try:
        value = json.loads(raw)
        require(canonical(value).decode() == raw, "noncanonical journal JSON")
        return value
    except (TypeError, ValueError) as error:
        raise Invalid("invalid journal JSON") from error


class Owner:
    """One explicitly provisioned source/model owner with finite retained history."""

    def __init__(self, root, binding, budget_units, *, max_operations=4096):
        require(os.name == "posix", "owner v1 requires a local POSIX filesystem")
        exact(
            binding, "owner_id generation source_frontier encoder_sha256 grant_sha256"
        )
        identifier(binding["owner_id"])
        integer(binding["generation"], 1)
        for name in ("source_frontier", "encoder_sha256", "grant_sha256"):
            require(digest(binding[name]) != "0" * 64, "empty owner binding")
        integer(budget_units, 1)
        require(1 <= integer(max_operations, 1) <= 4096, "operation limit exceeds 4096")
        self.root = Path(root).absolute()
        require(self.root == self.root.resolve(), "owner path contains a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(
            self.root.stat().st_uid == os.getuid(),
            "owner directory belongs to another user",
        )
        self._binding = _json(canonical(binding).decode())
        self._metadata = {
            "schema": "perc1.owner.v1",
            "binding": self._binding,
            "budget_units": budget_units,
            "unit": "admitted_acquisition_attempt_v1",
            "max_operations": max_operations,
            "code_sha256": {
                name: sha(Path(__file__).with_name(name + ".py").read_bytes())
                for name in ("owner", "schema")
            },
        }
        self._db, self._lock = None, None
        try:
            import fcntl

            lock_path = self.root / "writer.lock"
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self._lock = os.fdopen(fd, "a+b")
            try:
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Invalid("another writer owns this capture store") from error
            path = self.root / "owner.sqlite3"
            require(not path.is_symlink(), "journal symlink refused")
            self._db = sqlite3.connect(path, timeout=0, isolation_level=None)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=DELETE")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA trusted_schema=OFF")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS metadata (value TEXT NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS operations ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, request_sha TEXT NOT NULL,"
                "units INTEGER NOT NULL, state TEXT NOT NULL, receipt TEXT, receipt_sha TEXT)"
            )
            with self._transaction():
                rows = self._db.execute("SELECT value FROM metadata").fetchall()
                require(len(rows) <= 1, "ambiguous owner metadata")
                if not rows:
                    require(
                        self._db.execute("SELECT COUNT(*) FROM operations").fetchone()[
                            0
                        ]
                        == 0,
                        "operations without owner metadata",
                    )
                    self._db.execute(
                        "INSERT INTO metadata VALUES (?)",
                        (canonical(self._metadata).decode(),),
                    )
                else:
                    require(
                        _json(rows[0][0]) == self._metadata,
                        "owner generation/source/model/grant/budget changed",
                    )
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            rows = self._db.execute("SELECT * FROM operations").fetchall()
            require(len(rows) <= max_operations, "operation count exceeds contract")
            require(
                sum(row["units"] for row in rows) <= budget_units,
                "journal overspent its reservation budget",
            )
            for row in rows:
                self._validate(row)
            for row in rows:
                if row["state"] == "retained":
                    self._settle(row["id"])
        except BaseException:
            self.close()
            raise

    @property
    def binding(self):
        return _json(canonical(self._binding).decode())

    @contextmanager
    def _transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _row(self, operation_id):
        return self._db.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id,)
        ).fetchone()

    def _validate(self, row):
        identifier(row["id"])
        integer(row["units"], 1)
        require(
            row["state"] in ("reserved", "dispatched", "retained", "settled"),
            "invalid journal state",
        )
        require(
            len(row["payload"].encode()) <= MAX_REQUEST_BYTES,
            "journal request exceeds bound",
        )
        payload = _json(row["payload"])
        exact(payload, "request units")
        require(
            type(payload["request"]) is dict
            and integer(payload["units"], 1) == row["units"],
            "invalid reservation",
        )
        require(
            sha(payload) == digest(row["request_sha"]), "reservation digest mismatch"
        )
        if row["state"] in ("reserved", "dispatched"):
            require(
                row["receipt"] is None and row["receipt_sha"] is None,
                "receipt/state mismatch",
            )
            return None
        require(
            type(row["receipt"]) is str
            and len(row["receipt"].encode()) <= MAX_RECEIPT_BYTES,
            "invalid receipt size",
        )
        receipt = _json(row["receipt"])
        exact(
            receipt,
            "schema operation_id request_sha256 owner_binding_sha256 reserved_units status result error measurements scientific_status receipt_sha256",
        )
        require(
            receipt["schema"] == "perc1.owner-receipt.v1"
            and receipt["operation_id"] == row["id"]
            and receipt["request_sha256"] == row["request_sha"]
            and receipt["owner_binding_sha256"] == sha(self._binding)
            and receipt["reserved_units"] == row["units"]
            and receipt["status"] in ("executed", "failed")
            and receipt["scientific_status"] == "HOLD",
            "receipt owner/request mismatch",
        )
        require(
            (
                receipt["status"] == "executed"
                and type(receipt["result"]) is dict
                and receipt["error"] is None
            )
            or (
                receipt["status"] == "failed"
                and receipt["result"] is None
                and type(receipt["error"]) is dict
            ),
            "receipt result/status mismatch",
        )
        measurements = exact(
            receipt["measurements"],
            "wall_ns process_cpu_ns energy_joules provider_billing scope",
        )
        integer(measurements["wall_ns"])
        integer(measurements["process_cpu_ns"])
        pin = sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        require(
            pin == receipt["receipt_sha256"] == row["receipt_sha"],
            "receipt digest mismatch",
        )
        return receipt

    def _reserve(self, operation_id, request, units):
        identifier(operation_id)
        integer(units, 1)
        require(type(request) is dict, "request must be an object")
        payload = canonical({"request": request, "units": units}).decode()
        require(len(payload.encode()) <= MAX_REQUEST_BYTES, "request exceeds 64 KiB")
        pin = sha(payload.encode())
        with self._transaction():
            prior = self._row(operation_id)
            if prior is not None:
                self._validate(prior)
                require(
                    prior["payload"] == payload and prior["request_sha"] == pin,
                    "operation identity reused with different payload",
                )
                return prior
            count, used = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(units),0) FROM operations"
            ).fetchone()
            require(
                count < self._metadata["max_operations"],
                "retained operation limit reached",
            )
            require(
                used + units <= self._metadata["budget_units"],
                "acquisition reservation denied",
            )
            self._db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,NULL,NULL)",
                (operation_id, payload, pin, units, "reserved"),
            )
        return self._row(operation_id)

    def _begin_dispatch(self, operation_id):
        with self._transaction():
            require(
                self._row(operation_id)["state"] == "reserved",
                "operation is not reserved",
            )
            self._db.execute(
                "UPDATE operations SET state='dispatched' WHERE id=?", (operation_id,)
            )

    def _retain(self, operation_id, receipt):
        raw = canonical(receipt).decode()
        require(len(raw.encode()) <= MAX_RECEIPT_BYTES, "receipt exceeds 1 MiB")
        with self._transaction():
            require(
                self._row(operation_id)["state"] == "dispatched",
                "operation is not dispatched",
            )
            self._db.execute(
                "UPDATE operations SET state='retained',receipt=?,receipt_sha=? WHERE id=?",
                (raw, receipt["receipt_sha256"], operation_id),
            )

    def _settle(self, operation_id):
        with self._transaction():
            row = self._row(operation_id)
            self._validate(row)
            require(row["state"] in ("retained", "settled"), "receipt is not retained")
            self._db.execute(
                "UPDATE operations SET state='settled' WHERE id=?", (operation_id,)
            )

    def execute(self, operation_id, request, *, units=1, dispatch):
        """Reserve before invoking a configured effect; replay never invokes dispatch."""
        require(callable(dispatch), "configured dispatch callback required")
        row = self._reserve(operation_id, request, units)
        if row["state"] == "dispatched":
            raise UnknownOutcome(
                "dispatch outcome UNKNOWN; reservation retained, no automatic replay"
            )
        if row["state"] in ("retained", "settled"):
            return self.receipt(operation_id)
        self._begin_dispatch(operation_id)
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        result, error, status = None, None, "executed"
        try:
            result = dispatch(_json(row["payload"])["request"])
            require(type(result) is dict, "dispatch result must be an object")
            require(
                len(canonical(result)) <= MAX_RECEIPT_BYTES - 4096,
                "dispatch result exceeds retained bound",
            )
        except Exception as failure:
            result, status = None, "failed"
            error = {
                "type": type(failure).__name__,
                "message": str(failure)[:512],
                "effect_outcome": "unverified",
            }
        receipt = {
            "schema": "perc1.owner-receipt.v1",
            "operation_id": operation_id,
            "request_sha256": row["request_sha"],
            "owner_binding_sha256": sha(self._binding),
            "reserved_units": units,
            "status": status,
            "result": result,
            "error": error,
            "measurements": {
                "wall_ns": time.perf_counter_ns() - started,
                "process_cpu_ns": time.process_time_ns() - cpu,
                "energy_joules": None,
                "provider_billing": None,
                "scope": "dispatch including capture/encoder; owner journal bookkeeping excluded",
            },
            "scientific_status": "HOLD",
        }
        receipt["receipt_sha256"] = sha(receipt)
        self._retain(operation_id, receipt)
        self._settle(operation_id)
        return self.receipt(operation_id)

    def receipt(self, operation_id):
        """Read the exact retained receipt for a subsequent task under the same pins."""
        row = self._row(identifier(operation_id))
        require(row is not None, "unknown operation identity")
        if row["state"] == "dispatched":
            raise UnknownOutcome("dispatch outcome UNKNOWN; no retained receipt")
        require(row["state"] in ("retained", "settled"), "operation has no receipt")
        receipt = self._validate(row)
        if row["state"] == "retained":
            self._settle(operation_id)
        return receipt

    def status(self):
        rows = self._db.execute(
            "SELECT state,COUNT(*),SUM(units) FROM operations GROUP BY state"
        ).fetchall()
        states = {row[0]: {"operations": row[1], "units": row[2]} for row in rows}
        used = sum(value["units"] for value in states.values())
        return {
            "binding_sha256": sha(self._binding),
            "states": states,
            "reserved_units": used,
            "remaining_units": self._metadata["budget_units"] - used,
            "unresolved_dispatch": bool(states.get("dispatched")),
        }

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
