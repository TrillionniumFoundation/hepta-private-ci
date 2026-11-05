"""One-filesystem experiment reservations for trusted, prospective evaluation.

This ledger prevents duplicate dispatch and exact holdout reuse across processes.
It is not authentication, a distributed authority, a semantic leakage detector, or
protection against rollback/copy/deletion of the complete SQLite filesystem. All
hosts must submit to the same owner; starting a fresh database loses that history.
"""

from contextlib import contextmanager
import hashlib
import json
import secrets
import sqlite3
import time


class LedgerRejected(ValueError):
    """An immutable binding, dispatch slot, or retained outcome cannot be changed."""


def canonical(value):
    wire = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(wire.encode()) > 64 * 1024 * 1024:
        raise LedgerRejected("ledger object exceeds 64 MiB")
    return wire


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _name(value):
    if not isinstance(value, str) or not value or len(value.encode()) > 512:
        raise LedgerRejected("invalid experiment/operation identity")
    return value


class ExperimentLedger:
    """Single trusted owner, SQLite serialized reservations and durable receipts.

    The new-reservation token is returned only to its creating caller. A repeated
    request can observe the original outcome but cannot obtain a new dispatch
    grant. Reserved/running/unknown/cancelled slots are never automatically reused.
    """

    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=20, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=20000")
        self.db.execute("PRAGMA foreign_keys=ON")
        if self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            self.db.close()
            raise LedgerRejected("a persistent WAL database is required")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS experiments(
          id TEXT PRIMARY KEY, family TEXT NOT NULL, family_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_claims(
          claim TEXT PRIMARY KEY, experiment TEXT NOT NULL REFERENCES experiments(id));
        CREATE TABLE IF NOT EXISTS operations(
          id TEXT PRIMARY KEY, experiment TEXT NOT NULL REFERENCES experiments(id),
          comparison TEXT NOT NULL, look INTEGER NOT NULL,
          request TEXT NOT NULL, request_hash TEXT NOT NULL, token_hash TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('reserved','running','completed','unknown','cancelled')),
          result TEXT, result_hash TEXT, reason TEXT,
          UNIQUE(experiment,comparison,look));
        CREATE TABLE IF NOT EXISTS events(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL REFERENCES operations(id),
          state TEXT NOT NULL, recorded_ns INTEGER NOT NULL, reason TEXT);
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _event(self, operation, state, reason=None):
        self.db.execute("INSERT INTO events(operation,state,recorded_ns,reason) VALUES (?,?,?,?)",
                        (operation, state, time.time_ns(), reason))

    def _row(self, operation):
        row = self.db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
        if row is None:
            raise LedgerRejected("unknown operation")
        family = self.db.execute("SELECT family,family_hash FROM experiments WHERE id=?", (row["experiment"],)).fetchone()
        if family is None or fingerprint(json.loads(family[0])) != family[1]:
            raise LedgerRejected("corrupt family receipt")
        if fingerprint(json.loads(row["request"])) != row["request_hash"]:
            raise LedgerRejected("corrupt request receipt")
        if row["result"] is not None and fingerprint(json.loads(row["result"])) != row["result_hash"]:
            raise LedgerRejected("corrupt result receipt")
        return row

    def _response(self, row):
        return {"operation": row["id"], "experiment": row["experiment"],
                "comparison": json.loads(row["comparison"]), "look": row["look"],
                "request": row["request_hash"], "state": row["state"], "reason": row["reason"],
                "result": None if row["result"] is None else json.loads(row["result"])}

    def read(self, operation):
        return self._response(self._row(_name(operation)))

    def history(self, operation):
        self._row(_name(operation))
        return [dict(row) for row in self.db.execute(
            "SELECT sequence,state,recorded_ns,reason FROM events WHERE operation=? ORDER BY sequence",
            (operation,))]

    def reserve(self, experiment, operation, family, comparison, look, request):
        """Commit binding and holdout claims before returning one dispatch token.

        family is normalized by DurableMatchedEvaluator. Its complete comparison
        roster and planned look count are frozen across restarts. Source claims
        cover stable unit/cluster IDs and exact public query/payload hashes.
        """
        experiment, operation = _name(experiment), _name(operation)
        family_wire, request_wire = canonical(family), canonical(request)
        family = json.loads(family_wire)
        comparisons, looks, claims = (family.get("comparisons"), family.get("planned_looks"),
                                      family.get("source_claims"))
        if (not isinstance(comparisons, list) or not comparisons
                or any(not isinstance(pair, list) or len(pair) != 2
                       or any(not isinstance(x, str) or not x for x in pair) for pair in comparisons)
                or len({tuple(pair) for pair in comparisons}) != len(comparisons)
                or comparison not in comparisons or type(looks) is not int or looks < 1
                or type(look) is not int or not 1 <= look <= looks
                or not isinstance(claims, list) or not claims or len(claims) > 100000
                or claims != sorted(set(claims))
                or any(not isinstance(x, str) or len(x) != 64
                       or any(c not in "0123456789abcdef" for c in x) for x in claims)):
            raise LedgerRejected("invalid frozen family/slot")
        family_hash, request_hash = fingerprint(family), fingerprint(json.loads(request_wire))
        comparison_wire = canonical(comparison)
        with self._transaction():
            existing = self.db.execute("SELECT id FROM operations WHERE id=?", (operation,)).fetchone()
            if existing:
                row = self._row(operation)
                prior = self.db.execute("SELECT family_hash FROM experiments WHERE id=?",
                                        (row["experiment"],)).fetchone()
                if ((row["experiment"], row["comparison"], row["look"], row["request_hash"], prior[0])
                        != (experiment, comparison_wire, look, request_hash, family_hash)):
                    raise LedgerRejected("operation identity already bound")
                return dict(self._response(row), dispatch_token=None)
            prior = self.db.execute("SELECT family,family_hash FROM experiments WHERE id=?",
                                    (experiment,)).fetchone()
            if prior:
                if prior[0] != family_wire or prior[1] != family_hash:
                    raise LedgerRejected("experiment family already frozen")
            else:
                self.db.execute("INSERT INTO experiments VALUES (?,?,?)", (experiment, family_wire, family_hash))
                for claim in claims:
                    owner = self.db.execute("SELECT experiment FROM source_claims WHERE claim=?", (claim,)).fetchone()
                    if owner is not None and owner[0] != experiment:
                        raise LedgerRejected("source cohort already reserved by another experiment")
                    self.db.execute("INSERT INTO source_claims VALUES (?,?)", (claim, experiment))
            if self.db.execute("SELECT 1 FROM operations WHERE experiment=? AND comparison=? AND look=?",
                               (experiment, comparison_wire, look)).fetchone():
                raise LedgerRejected("comparison/look already reserved")
            token = secrets.token_hex(32)
            self.db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (operation, experiment, comparison_wire, look, request_wire, request_hash,
                 hashlib.sha256(token.encode()).hexdigest(), "reserved", None, None, None))
            self._event(operation, "reserved")
            return dict(self._response(self._row(operation)), dispatch_token=token)

    def _authorize(self, row, token):
        if (not isinstance(token, str)
                or not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["token_hash"])):
            raise LedgerRejected("reservation token mismatch")

    def start(self, operation, token):
        with self._transaction():
            row = self._row(_name(operation))
            self._authorize(row, token)
            if row["state"] != "reserved":
                raise LedgerRejected("operation cannot be dispatched again")
            self.db.execute("UPDATE operations SET state='running' WHERE id=?", (operation,))
            self._event(operation, "running")
            return self._response(self._row(operation))

    def finish(self, operation, token, result):
        wire, result_hash = canonical(result), fingerprint(result)
        with self._transaction():
            row = self._row(_name(operation))
            self._authorize(row, token)
            if row["state"] == "completed" and row["result_hash"] == result_hash:
                return self._response(row)
            if row["state"] != "running":
                raise LedgerRejected("terminal or unresolved outcome cannot be replaced")
            self.db.execute("UPDATE operations SET state='completed',result=?,result_hash=? WHERE id=?",
                            (wire, result_hash, operation))
            self._event(operation, "completed")
            return self._response(self._row(operation))

    def retain(self, operation, state, reason):
        """Record cancellation/uncertainty; never release a look or erase a result.

        A supervisor decides whether an old process is gone. This call does not
        terminate a worker, transfer ownership, or prove an external effect stopped.
        Late successful settlement cannot overwrite retained unknown/cancelled state.
        """
        if state not in ("unknown", "cancelled") or not isinstance(reason, str) or not reason:
            raise LedgerRejected("invalid retained outcome")
        with self._transaction():
            row = self._row(_name(operation))
            if row["state"] in ("reserved", "running"):
                self.db.execute("UPDATE operations SET state=?,reason=? WHERE id=?", (state, reason, operation))
                self._event(operation, state, reason)
            return self._response(self._row(operation))
