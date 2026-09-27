"""Migration-only legacy/new-attempt discrimination; no native or network claim."""
from pathlib import Path
import sqlite3
import unittest

SQL = (Path(__file__).resolve().parents[2] / "codex-rs/hepta-matrix-store/migrations/0009_matrix_legacy_content_holds.sql").read_text()

class LegacyContentHoldTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE outbox_messages(stable_txn_id TEXT PRIMARY KEY, attempts INTEGER)")
        self.db.execute("CREATE TABLE matrix_dispatch_content_bindings(stable_txn_id TEXT PRIMARY KEY)")
        self.db.executemany("INSERT INTO outbox_messages VALUES (?,?)", [("old-unknown", 2), ("old-idle", 0), ("pinned", 3)])
        self.db.execute("INSERT INTO matrix_dispatch_content_bindings VALUES ('pinned')")
        self.db.executescript(SQL)

    def test_only_unpinned_inherited_attempts_are_held(self):
        self.assertEqual(self.db.execute("SELECT * FROM matrix_dispatch_legacy_content_holds").fetchall(), [("old-unknown", 2)])

    def test_post_migration_claim_retries_are_not_mislabeled_legacy(self):
        self.db.execute("INSERT INTO outbox_messages VALUES ('new-pre-pin-cancel', 2)")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM matrix_dispatch_legacy_content_holds WHERE stable_txn_id='new-pre-pin-cancel'").fetchone(), (0,))

    def test_old_never_attempted_record_can_start_after_upgrade(self):
        self.db.execute("UPDATE outbox_messages SET attempts=2 WHERE stable_txn_id='old-idle'")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM matrix_dispatch_legacy_content_holds WHERE stable_txn_id='old-idle'").fetchone(), (0,))

    def test_inherited_attempt_remains_held_after_later_retry(self):
        self.db.execute("UPDATE outbox_messages SET attempts=3 WHERE stable_txn_id='old-unknown'")
        self.assertEqual(self.db.execute("SELECT inherited_attempts FROM matrix_dispatch_legacy_content_holds").fetchone(), (2,))

    def test_hold_snapshot_rejects_insertion_update_and_deletion(self):
        for query in ["INSERT INTO matrix_dispatch_legacy_content_holds VALUES ('old-idle', 1)", "UPDATE matrix_dispatch_legacy_content_holds SET inherited_attempts=3", "DELETE FROM matrix_dispatch_legacy_content_holds"]:
            with self.subTest(query=query), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(query)

    def test_all_four_ddl_definitions_are_preserved(self):
        statements = [s for s in SQL.split("\n\n") if s.startswith("CREATE ")]
        self.assertEqual(len(statements), 4)
        normalize = lambda value: " ".join(value.strip().rstrip(";").split())
        for statement in statements:
            actual = self.db.execute("SELECT sql FROM sqlite_schema WHERE name=?", (statement.split()[2],)).fetchone()
            self.assertEqual(normalize(actual[0]), normalize(statement))

if __name__ == "__main__":
    unittest.main()
