"""Execute migration-8 constraints in SQLite, not a Rust/runtime qualification.

The small parent table isolates the new migration. Native store integration,
crypto verification and actual homeserver behavior have separate test lanes.
"""
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "codex-rs/hepta-matrix-store/migrations/0008_matrix_content_binding.sql"


def normalized_sql(text):
    return " ".join(text.strip().rstrip(";").split())


class ContentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "content.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE matrix_dispatch_ledger(stable_txn_id TEXT PRIMARY KEY)")
        self.db.executemany("INSERT INTO matrix_dispatch_ledger VALUES (?)", [("txn-a",), ("txn-b",)])
        self.db.executescript(MIGRATION.read_text())

    def insert(self, txn="txn-a", content="a" * 64, scope="b" * 64, version=1, at=12):
        self.db.execute(
            "INSERT INTO matrix_dispatch_content_bindings VALUES (?, ?, ?, ?, ?, ?)",
            (txn, version, content, scope, "c" * 64, at),
        )

    def matches_ddl(self):
        statements = [s for s in MIGRATION.read_text().split("\n\n") if s.startswith("CREATE ")]
        self.assertEqual(len(statements), 3)
        for statement in statements:
            actual = self.db.execute("SELECT sql FROM sqlite_schema WHERE name=?", (statement.split()[2],)).fetchone()
            if actual is None or normalized_sql(actual[0]) != normalized_sql(statement):
                return False
        return True

    def test_pin_survives_database_reopen(self):
        self.insert()
        before = self.db.execute("SELECT * FROM matrix_dispatch_content_bindings").fetchall()
        self.db.commit()
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.assertEqual(before, self.db.execute("SELECT * FROM matrix_dispatch_content_bindings").fetchall())

    def test_duplicate_transaction_is_rejected(self):
        self.insert()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(content="d" * 64)

    def test_same_content_for_distinct_transactions_is_legal(self):
        self.insert()
        self.insert(txn="txn-b")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM matrix_dispatch_content_bindings").fetchone(), (2,))

    def test_update_cannot_retarget_or_change_scope(self):
        self.insert()
        for field in ("canonical_content_sha256", "scope_sha256", "source_payload_sha256"):
            with self.subTest(field=field), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(f"UPDATE matrix_dispatch_content_bindings SET {field}=?", ("d" * 64,))

    def test_delete_cannot_erase_replay_binding(self):
        self.insert()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM matrix_dispatch_content_bindings")

    def test_orphan_pin_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(txn="not-a-dispatch")

    def test_unknown_canonicalization_version_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(version=2)

    def test_malformed_content_or_scope_is_rejected(self):
        for bad in ("", "a" * 63, "A" * 64, "g" * 64, "0" * 64):
            for field in ("content", "scope"):
                with self.subTest(field=field, bad=bad), self.assertRaises(sqlite3.IntegrityError):
                    self.insert(**{field: bad})

    def test_negative_time_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(at=-1)

    def test_transaction_rollback_does_not_publish_pin(self):
        self.insert()
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM matrix_dispatch_content_bindings").fetchone(), (0,))

    def test_expected_ddl_is_exactly_present(self):
        self.assertTrue(self.matches_ddl())

    def test_same_name_weakened_trigger_is_not_accepted(self):
        self.db.execute("DROP TRIGGER matrix_dispatch_content_bindings_no_update")
        self.db.execute("CREATE TRIGGER matrix_dispatch_content_bindings_no_update BEFORE UPDATE ON matrix_dispatch_content_bindings BEGIN SELECT 1; END")
        self.assertFalse(self.matches_ddl())

    def test_missing_trigger_is_not_accepted(self):
        self.db.execute("DROP TRIGGER matrix_dispatch_content_bindings_no_delete")
        self.assertFalse(self.matches_ddl())


if __name__ == "__main__":
    unittest.main()
