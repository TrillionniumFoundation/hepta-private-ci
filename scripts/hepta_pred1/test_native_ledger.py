"""Synthetic rows on real SQLite using exact native migrations.

No real owner/business/task-benefit evidence is produced by these fixtures.
SQL source f5f2ca2: migrations/0011 and /0013, Git blobs
db8e533b282e37472af9bd3a414c16f8093ff991 and
790ccc918f4d66409511adf9cc8808e5f0703fc4.
"""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


from .native_ledger import (
    ATTEMPT_FIELDS,
    IDENTITY_FIELDS,
    OBSERVATION_FIELDS,
    collect_native,
)

MIGRATION_11 = """-- Durable provider-contact boundary for final-use-authorized TaskFlow effects.
-- The start row is immutable evidence that external dispatch may have happened.
-- The observation row is separately immutable so a crash between provider
-- return and TaskFlow projection update can be repaired without redispatch.
CREATE TABLE taskflow_effect_dispatch_attempts (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    intent_digest TEXT NOT NULL CHECK (
        length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'
    ),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    binding_digest TEXT NOT NULL CHECK (
        length(binding_digest) = 64 AND binding_digest NOT GLOB '*[^0-9a-f]*'
    ),
    destination_id TEXT NOT NULL CHECK (length(destination_id) BETWEEN 1 AND 128),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    grant_id TEXT NOT NULL CHECK (length(grant_id) BETWEEN 1 AND 128),
    grant_nonce_digest TEXT NOT NULL CHECK (
        length(grant_nonce_digest) = 64 AND grant_nonce_digest NOT GLOB '*[^0-9a-f]*'
    ),
    record_command_id TEXT NOT NULL CHECK (length(record_command_id) BETWEEN 1 AND 256),
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    UNIQUE(owner_agent_id, grant_nonce_digest),
    FOREIGN KEY(owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id)
);

CREATE TABLE taskflow_effect_dispatch_observations (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    observation TEXT NOT NULL CHECK (
        observation IN ('proven_absent', 'succeeded', 'failed', 'indeterminate')
    ),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64 AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(
            owner_agent_id, run_id, step_id, attempt
        )
);

CREATE TRIGGER taskflow_effect_dispatch_attempts_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_attempts
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch attempts are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_attempts_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_attempts
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch attempts are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_observations_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_observations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch observations are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_observations_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_observations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch observations are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 11 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
"""
MIGRATION_13 = """-- A provider may first return an indeterminate observation and later supply a
-- terminal reconciliation for the same immutable dispatch identity. Preserve
-- both facts append-only; the reconciliation row never authorizes redispatch.
CREATE TABLE taskflow_effect_dispatch_reconciliations (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    observation TEXT NOT NULL CHECK (
        observation IN ('proven_absent', 'succeeded', 'failed')
    ),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64 AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(
            owner_agent_id, run_id, step_id, attempt
        )
);

CREATE TRIGGER taskflow_effect_dispatch_reconciliations_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect reconciliations are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_reconciliations_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect reconciliations are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 13 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
"""


class NativeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "native.sqlite3"
        self.writer = sqlite3.connect(self.db)
        self.addCleanup(self.writer.close)
        self.writer.executescript("""
            CREATE TABLE taskflow_runs (
                owner_agent_id TEXT NOT NULL, run_id TEXT NOT NULL,
                PRIMARY KEY(owner_agent_id, run_id));
            CREATE TABLE automation_meta (
                singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL);
            INSERT INTO automation_meta VALUES (1, 10);
            CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
            BEGIN SELECT RAISE(ABORT, 'automation owner metadata is immutable'); END;
        """)
        self.writer.executescript(MIGRATION_11)
        self.writer.executescript(MIGRATION_13)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("PRAGMA wal_autocheckpoint=0")
        self.identity = dict(
            zip(
                IDENTITY_FIELDS,
                (
                    "fixture-owner",
                    "fixture-run",
                    "fixture-step",
                    1,
                    "1" * 64,
                    "2" * 64,
                    "3" * 64,
                    "fixture-destination",
                ),
            )
        )
        self.writer.execute(
            "INSERT INTO taskflow_runs VALUES (?, ?)", ("fixture-owner", "fixture-run")
        )
        self.writer.commit()
        self.snapshot_path = self.root / "snapshot.json"

    def insert_attempt(self):
        row = {
            **self.identity,
            "authority_epoch": 1,
            "grant_id": "fixture-grant",
            "grant_nonce_digest": "4" * 64,
            "record_command_id": "fixture-command",
            "started_at_ms": 900_000,
        }
        self.writer.execute(
            f"INSERT INTO taskflow_effect_dispatch_attempts ({','.join(ATTEMPT_FIELDS)})"
            f" VALUES ({','.join('?' for _ in ATTEMPT_FIELDS)})",
            tuple(row[k] for k in ATTEMPT_FIELDS),
        )
        self.writer.commit()
        return row

    def insert_observation(self, kind, table="observations", native_time=999_000):
        row = {k: self.identity[k] for k in IDENTITY_FIELDS[:4]}
        row.update(
            observation=kind, evidence_digest="5" * 64, observed_at_ms=native_time
        )
        self.writer.execute(
            f"INSERT INTO taskflow_effect_dispatch_{table} ({','.join(OBSERVATION_FIELDS)})"
            f" VALUES ({','.join('?' for _ in OBSERVATION_FIELDS)})",
            tuple(row[k] for k in OBSERVATION_FIELDS),
        )
        self.writer.commit()
        return row

    def collect(self, cursor=1, at=10):
        with patch("hepta_pred1.native_ledger.monotonic", return_value=at):
            return collect_native(
                self.db, identity=self.identity, clock_id="fixture-boot", cursor=cursor
            )

    def test_wal_readonly_collection_retains_raw_clocks_and_missing_rows(self):
        absent = self.collect()
        self.assertEqual(
            absent.payload["rows"],
            {"attempts": [], "observations": [], "reconciliations": []},
        )
        expected = self.insert_attempt()
        wal = Path(str(self.db) + "-wal")
        self.assertGreater(wal.stat().st_size, 0)
        before = (self.db.read_bytes(), wal.read_bytes(), self.writer.total_changes)
        original = sqlite3.connect
        calls, traced = [], []

        def read_connection(database, **kwargs):
            calls.append((database, kwargs))
            con = original(database, **kwargs)
            con.set_trace_callback(traced.append)
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                con.execute("CREATE TABLE must_not_exist (value INTEGER)")
            return con

        with patch(
            "hepta_pred1.native_ledger.sqlite3.connect", side_effect=read_connection
        ):
            got = self.collect()
        self.assertEqual(got.payload["rows"]["attempts"], [expected])
        self.assertEqual(got.payload["available_at"], 10)
        self.assertEqual(got.payload["rows"]["attempts"][0]["started_at_ms"], 900_000)
        self.assertIn("?mode=ro", calls[0][0])
        self.assertTrue(calls[0][1]["uri"])
        self.assertIn("PRAGMA query_only = ON", traced)
        self.assertIn("BEGIN", traced)
        self.assertEqual(
            before, (self.db.read_bytes(), wal.read_bytes(), self.writer.total_changes)
        )
        self.assertEqual(
            self.writer.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='must_not_exist'"
            ).fetchone(),
            (0,),
        )

    def test_python310_projection_bounds_without_connection_setlimit(self):
        row = self.insert_attempt()
        original, captured = sqlite3.connect, []

        class LegacyConnection:
            # Expose exactly the methods the Python 3.10 reader needs, without
            # the Python 3.11 setlimit API. The underlying engine is real SQLite.
            def __init__(self, *args, **kwargs):
                self.real = original(*args, **kwargs)

            row_factory = property(
                lambda self: self.real.row_factory,
                lambda self, value: setattr(self.real, "row_factory", value),
            )

            def execute(self, *args):
                cursor = self.real.execute(*args)
                if args[0].startswith("SELECT"):
                    rows = list(cursor)
                    captured.extend(dict(value) for value in rows)
                    return rows
                return cursor

            def rollback(self):
                self.real.rollback()

            def close(self):
                self.real.close()

        with patch("hepta_pred1.native_ledger.sqlite3.connect", LegacyConnection):
            self.assertEqual(self.collect().payload["rows"]["attempts"], [row])
        # Corrupt only this isolated fixture: remove its immutable-update trigger
        # and bypass CHECKs. No real owner database is modified.
        self.writer.execute("PRAGMA ignore_check_constraints=ON")
        self.writer.execute("DROP TRIGGER taskflow_effect_dispatch_attempts_no_update")
        self.writer.execute(
            "UPDATE taskflow_effect_dispatch_attempts SET grant_id=?", ("x" * 2048,)
        )
        self.writer.commit()
        captured.clear()
        with patch("hepta_pred1.native_ledger.sqlite3.connect", LegacyConnection):
            with self.assertRaisesRegex(ValueError, "identity"):
                self.collect()
        self.assertEqual(len(captured), 1)
        self.assertIsNone(captured[0]["grant_id"])


if __name__ == "__main__":
    unittest.main()
