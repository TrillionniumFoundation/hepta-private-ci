"""SQLite policy-model checks using the same cases as the native SQLx test.

These run real SQLite statements against a Python authorizer implementation.
They do NOT compile Rust or qualify the SQLx FFI installation or reconnect path.
The native `runtime_authorizer` integration test is the authority for that path.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "qualification/kernel-evidence/SQLITE_RUNTIME_CASES.json").read_text())
IMMUTABLE = {"qualification_evidence", "evidence_recovery_identity", "governance_decisions", "governance_receipts"}
INTROSPECTION = {"table_info", "table_xinfo", "index_info", "index_xinfo", "index_list", "foreign_key_list", "foreign_key_check", "quick_check", "integrity_check"}
READ_PRAGMAS = {"schema_version", "user_version", "database_list", "foreign_keys", "recursive_triggers", "synchronous", "journal_mode", "page_count", "page_size", "freelist_count", "compile_options"}


def authorize(action: int, first: str | None, second: str | None,
              database: str | None, trigger: str | None) -> int:
    """Policy model; unknown actions intentionally have no fallback grant."""
    first = first.lower() if first is not None else None
    second = second.lower() if second is not None else None
    database = database.lower() if database is not None else None
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
        allowed = database == "main" and first is not None and first not in {
            "_sqlx_migrations", "sqlite_master", "sqlite_schema", "sqlite_sequence"
        } and (action == sqlite3.SQLITE_INSERT or first not in IMMUTABLE)
    elif action == sqlite3.SQLITE_PRAGMA:
        allowed = first in INTROSPECTION or (second is None and first in READ_PRAGMAS)
    elif action == sqlite3.SQLITE_FUNCTION:
        allowed = second is not None and second not in {"load_extension", "writefile"}
    elif action == sqlite3.SQLITE_READ:
        allowed = database in {"main", "temp"} or (database is None and first is not None and second == "")
    elif action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE):
        allowed = True
    else:
        allowed = False
    return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY


class RuntimeAuthorizerModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name) / "evidence.sqlite"
        migration = sqlite3.connect(self.path)
        migration.executescript(CASES["setupSql"])
        migration.close()
        self.runtime = self.open_runtime()
        self.addCleanup(self.runtime.close)

    def open_runtime(self) -> sqlite3.Connection:
        db = sqlite3.connect(f"file:{self.path}?mode=rw", uri=True)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA recursive_triggers=ON")
        db.set_authorizer(authorize)
        return db

    def test_forbidden_statements_fail_for_authorization_or_immutable_trigger(self) -> None:
        for sql in CASES["deniedSql"]:
            self.runtime.rollback()
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError) as error:
                self.runtime.execute(sql).fetchall()
            # Exclude syntax errors and missing-table errors masquerading as a
            # passing negative test. SQLITE_CONSTRAINT is valid for REPLACE.
            self.assertIn(error.exception.sqlite_errorcode & 0xFF, (sqlite3.SQLITE_AUTH, sqlite3.SQLITE_CONSTRAINT))
        self.assertEqual(self.runtime.execute("SELECT evidence_id FROM qualification_evidence").fetchall(), [("evidence:original",)])

    def test_reads_and_introspection_still_work(self) -> None:
        for sql in CASES["allowedSql"]:
            with self.subTest(sql=sql):
                self.runtime.execute(sql).fetchall()
        self.runtime.commit()

    def test_autoincrement_and_idempotence_do_not_need_sequence_write_permission(self) -> None:
        for _ in range(2):
            self.runtime.execute("INSERT INTO qualification_evidence(evidence_id) VALUES (?) ON CONFLICT DO NOTHING", ("evidence:new",))
        self.runtime.commit()
        self.assertEqual(self.runtime.execute("SELECT seq FROM qualification_evidence ORDER BY seq").fetchall(), [(1,), (2,)])

    def test_rollback_and_savepoint_do_not_leak_partial_evidence(self) -> None:
        self.runtime.execute("BEGIN IMMEDIATE")
        self.runtime.execute("SAVEPOINT evidence_append")
        self.runtime.execute("INSERT INTO qualification_evidence(evidence_id) VALUES ('evidence:rolled-back')")
        self.runtime.execute("ROLLBACK TO evidence_append")
        self.runtime.execute("RELEASE evidence_append")
        self.runtime.commit()
        self.assertEqual(self.runtime.execute("SELECT COUNT(*) FROM qualification_evidence").fetchone()[0], 1)

    def test_every_fresh_connection_has_the_same_contract(self) -> None:
        for _ in range(10):
            db = self.open_runtime()
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute("PRAGMA recursive_triggers=OFF")
                self.assertEqual(db.execute("PRAGMA recursive_triggers").fetchone()[0], 1)
            finally:
                db.close()

    def test_migration_authority_is_separate_from_runtime_sql(self) -> None:
        migration = sqlite3.connect(self.path)
        try:
            migration.execute("CREATE TABLE explicitly_migrated(id INTEGER PRIMARY KEY)")
            migration.commit()
        finally:
            migration.close()
        self.runtime.execute("SELECT * FROM explicitly_migrated").fetchall()
        with self.assertRaises(sqlite3.DatabaseError):
            self.runtime.execute("DROP TABLE explicitly_migrated")

    def test_missing_file_is_not_recreated(self) -> None:
        missing = Path(self.home.name) / "missing.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            sqlite3.connect(f"file:{missing}?mode=rw", uri=True)
        self.assertFalse(missing.exists())

    def test_unknown_null_and_case_variations(self) -> None:
        for args in [(-1, None, None, None, None), (sqlite3.SQLITE_INSERT, None, None, None, None),
                     (sqlite3.SQLITE_FUNCTION, None, None, None, None),
                     (sqlite3.SQLITE_UPDATE, "QUALIFICATION_EVIDENCE", "evidence_id", "MAIN", None),
                     (sqlite3.SQLITE_PRAGMA, "Recursive_Triggers", "off", None, None)]:
            self.assertEqual(authorize(*args), sqlite3.SQLITE_DENY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
