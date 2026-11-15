"""Real SQLite/WAL tests with explicitly synthetic owner records."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from .native_ledger import Artifact, ATTEMPT_FIELDS
from .owner_capture import capture_native, discover_native
from .test_native_ledger import MIGRATION_11, MIGRATION_13


class OwnerCaptureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.database = self.root / "owner.sqlite3"
        self.db = sqlite3.connect(self.database)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE taskflow_runs(owner_agent_id TEXT, run_id TEXT);
            CREATE TABLE automation_meta(singleton INTEGER, schema_version INTEGER);
            INSERT INTO automation_meta VALUES (1, 10);
            CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
            BEGIN SELECT RAISE(ABORT, 'immutable'); END;
        """)
        self.db.executescript(MIGRATION_11)
        self.db.executescript(MIGRATION_13)
        self.db.execute("PRAGMA journal_mode=WAL")
        for index in range(3):
            values = (
                "fixture-owner", f"run-{index}", "step", 1,
                "1" * 64, "2" * 64, "3" * 64, "fixture-destination", 1,
                "fixture-grant", str(index) * 64, "command", index,
            )
            self.db.execute(
                "INSERT INTO taskflow_effect_dispatch_attempts ("
                + ",".join(ATTEMPT_FIELDS)
                + ") VALUES (" + ",".join("?" for _ in values) + ")", values
            )
        self.db.commit()

    def test_paginated_wal_capture_preserves_rows_without_effect_labels(self):
        before = list(self.db.iterdump())
        first = capture_native(
            self.database, self.root / "first", clock_id="fixture-clock", start_cursor=7, limit=2
        ).payload
        self.assertEqual((first["record_count"], first["next_cursor"]), (2, 9))
        second = capture_native(
            self.database, self.root / "second", clock_id="fixture-clock", start_cursor=9,
            limit=2, after=first["next_after"]
        ).payload
        self.assertEqual((second["record_count"], second["next_after"]), (1, None))
        self.assertEqual(before, list(self.db.iterdump()))
        for parent, manifest in (("first", first), ("second", second)):
            self.assertEqual(manifest["effect_labels_created"], 0)
            self.assertEqual(manifest["predecision_snapshots_created"], 0)
            for item in manifest["records"]:
                artifact = Artifact.read(self.root / parent / item["path"])
                self.assertEqual(artifact.digest, item["sha256"])
                self.assertEqual(len(artifact.payload["rows"]["attempts"]), 1)
        with self.assertRaises(FileExistsError):
            capture_native(self.database, self.root / "first", clock_id="fixture-clock", start_cursor=7)

    def test_missing_database_and_bad_bounds_never_create_owner(self):
        absent = self.root / "absent.sqlite3"
        with self.assertRaises(FileNotFoundError):
            discover_native(absent)
        self.assertFalse(absent.exists())
        for limit in (0, 257, True):
            with self.assertRaises(ValueError):
                discover_native(self.database, limit=limit)
        with self.assertRaises(ValueError):
            discover_native(self.database, after=["owner", "run", "step", 0])

    def test_oversized_identity_is_rejected_before_export(self):
        values = ("x" * 2048, "bad", "step", 1, "1" * 64, "2" * 64, "3" * 64,
                  "destination", 1, "grant", "f" * 64, "command", 0)
        self.db.execute("INSERT INTO taskflow_effect_dispatch_attempts VALUES ("
                        + ",".join("?" for _ in values) + ")", values)
        self.db.commit()
        with self.assertRaises(ValueError):
            capture_native(self.database, self.root / "bad", clock_id="fixture-clock", start_cursor=0)
        self.assertFalse((self.root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
