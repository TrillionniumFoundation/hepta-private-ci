"""Read-only metadata checks on isolated SQLite fixtures, never real owners."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from .native_ledger import ATTEMPT_FIELDS
from .owner_preflight import inspect_owner_database
from .test_native_ledger import MIGRATION_11, MIGRATION_13


class OwnerPreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "owner.sqlite3"
        self.writer = sqlite3.connect(self.path)
        self.addCleanup(self.writer.close)
        self.writer.executescript("""
            CREATE TABLE automation_meta(singleton INTEGER, schema_version INTEGER, owner_agent_id TEXT);
            INSERT INTO automation_meta VALUES (1,20,'fixture-owner');
            CREATE TABLE taskflow_runs(owner_agent_id TEXT, run_id TEXT, PRIMARY KEY(owner_agent_id,run_id));
            CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
            BEGIN SELECT RAISE(ABORT, 'immutable'); END;
        """)
        self.writer.executescript(MIGRATION_11)
        self.writer.executescript(MIGRATION_13)
        self.writer.execute("DROP TRIGGER automation_meta_no_update")
        self.writer.execute("UPDATE automation_meta SET schema_version=20")
        self.writer.commit()
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("PRAGMA wal_autocheckpoint=0")

    def inspect(self, **kwargs):
        return inspect_owner_database(
            self.path, expected_owner="fixture-owner", **kwargs
        )

    def insert_attempt(self, index):
        values = (
            "fixture-owner",
            "run",
            str(index),
            1,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "destination",
            1,
            "grant",
            f"{index:064x}",
            "command",
            1,
        )
        self.writer.execute(
            f"INSERT INTO taskflow_effect_dispatch_attempts ({','.join(ATTEMPT_FIELDS)}) "
            f"VALUES ({','.join('?' for _ in ATTEMPT_FIELDS)})",
            values,
        )
        self.writer.commit()

    def test_wal_rows_and_metadata_are_read_without_owner_writes(self):
        self.insert_attempt(1)
        wal = Path(str(self.path) + "-wal")
        before = self.path.read_bytes(), wal.read_bytes(), self.writer.total_changes
        original, calls, traces = sqlite3.connect, [], []

        def reader(*args, **kwargs):
            calls.append((args, kwargs))
            db = original(*args, **kwargs)
            db.set_trace_callback(traces.append)
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                db.execute("CREATE TABLE denied(value)")
            return db

        with patch("hepta_pred1.owner_preflight.sqlite3.connect", side_effect=reader):
            result = self.inspect().payload
        table = result["tables"]["taskflow_effect_dispatch_attempts"]
        self.assertEqual(
            (table["bounded_rows"], table["row_count_complete"]), (1, True)
        )
        self.assertEqual(result["owner_agent_id"], "fixture-owner")
        self.assertNotIn("database_path", result)
        self.assertFalse(result["native_provenance_authenticated"])
        self.assertEqual(
            before,
            (self.path.read_bytes(), wal.read_bytes(), self.writer.total_changes),
        )
        self.assertIn("?mode=ro", calls[0][0][0])
        self.assertIn("PRAGMA query_only = ON", traces)
        self.assertIn("BEGIN", traces)

    def test_wrong_owner_schema_and_metadata_fail_without_receipt(self):
        for sql, message in (
            (
                "UPDATE automation_meta SET owner_agent_id='another-owner'",
                "identity differs",
            ),
            ("UPDATE automation_meta SET schema_version=19", "schema version"),
            ("UPDATE automation_meta SET singleton=2", "singleton"),
            ("INSERT INTO automation_meta VALUES(1,20,'fixture-owner')", "exactly one"),
            ("DELETE FROM automation_meta", "exactly one"),
        ):
            with self.subTest(sql=sql):
                self.writer.execute("DELETE FROM automation_meta")
                self.writer.execute(
                    "INSERT INTO automation_meta VALUES(1,20,'fixture-owner')"
                )
                self.writer.execute(sql)
                self.writer.commit()
                with self.assertRaisesRegex(ValueError, message):
                    self.inspect()

    def test_required_tables_columns_and_missing_path_are_not_created(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError):
            inspect_owner_database(missing, expected_owner="fixture-owner")
        self.assertFalse(missing.exists())
        self.writer.execute(
            "ALTER TABLE automation_meta RENAME COLUMN owner_agent_id TO wrong_column"
        )
        self.writer.commit()
        with self.assertRaisesRegex(ValueError, "columns missing"):
            self.inspect()
        self.writer.execute("DROP TABLE automation_meta")
        self.writer.execute(
            "CREATE VIEW automation_meta AS SELECT 1 AS singleton,20 AS schema_version,'fixture-owner' AS owner_agent_id"
        )
        self.writer.commit()
        with self.assertRaisesRegex(ValueError, "table missing"):
            self.inspect()

    def test_inventory_is_bounded_and_a_later_transaction_observes_new_wal_rows(self):
        self.assertEqual(
            self.inspect(row_limit=1).payload["tables"][
                "taskflow_effect_dispatch_attempts"
            ]["bounded_rows"],
            0,
        )
        for index in range(3):
            self.insert_attempt(index)
        table = self.inspect(row_limit=1).payload["tables"][
            "taskflow_effect_dispatch_attempts"
        ]
        self.assertEqual(
            (table["bounded_rows"], table["row_count_complete"]), (2, False)
        )

    def test_python310_fallback_bounds_corrupt_metadata_before_materialization(self):
        original, captured = sqlite3.connect, []

        class LegacyConnection:
            def __init__(self, *args, **kwargs):
                self.real = original(*args, **kwargs)

            def execute(self, *args):
                cursor = self.real.execute(*args)
                if args[0].startswith("SELECT CASE WHEN typeof(singleton)"):
                    rows = cursor.fetchall()
                    captured.extend(rows)

                    class Rows:
                        def fetchall(self):
                            return rows

                    return Rows()
                return cursor

            def rollback(self):
                self.real.rollback()

            def close(self):
                self.real.close()

        self.writer.execute(
            "UPDATE automation_meta SET owner_agent_id=?", ("x" * 2048,)
        )
        self.writer.commit()
        with patch("hepta_pred1.owner_preflight.sqlite3.connect", LegacyConnection):
            with self.assertRaisesRegex(ValueError, "identity"):
                self.inspect()
        self.assertEqual(captured, [(1, 20, None)])
        for field, message, expected in (
            ("singleton", "singleton", (None, 20, "fixture-owner")),
            ("schema_version", "schema version", (1, None, "fixture-owner")),
        ):
            with self.subTest(field=field):
                self.writer.execute("DELETE FROM automation_meta")
                self.writer.execute(
                    "INSERT INTO automation_meta VALUES(1,20,'fixture-owner')"
                )
                self.writer.execute(
                    f"UPDATE automation_meta SET {field}=?", (b"x" * 2_000_000,)
                )
                self.writer.commit()
                captured.clear()
                with patch(
                    "hepta_pred1.owner_preflight.sqlite3.connect", LegacyConnection
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        self.inspect()
                self.assertEqual(captured, [expected])

    def test_metadata_and_counts_share_one_snapshot_during_concurrent_wal_commit(self):
        original, inserted = sqlite3.connect, []

        class Reader(sqlite3.Connection):
            def execute(reader, *args, **kwargs):
                cursor = super().execute(*args, **kwargs)
                if args[0].startswith("SELECT CASE WHEN typeof(singleton)"):
                    self.insert_attempt(1)
                    inserted.append(True)
                return cursor

        def connect(*args, **kwargs):
            return original(*args, **kwargs, factory=Reader)

        with patch("hepta_pred1.owner_preflight.sqlite3.connect", side_effect=connect):
            table = self.inspect().payload["tables"][
                "taskflow_effect_dispatch_attempts"
            ]
        self.assertEqual(inserted, [True])
        self.assertEqual(table["bounded_rows"], 0)
        self.assertEqual(
            self.inspect().payload["tables"]["taskflow_effect_dispatch_attempts"][
                "bounded_rows"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
