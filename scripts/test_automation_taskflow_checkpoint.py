from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("checkpoint", Path(__file__).with_name("automation_taskflow_checkpoint.py"))
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
OWNER = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"


class CheckpointTests(unittest.TestCase):
    """Real SQLite/filesystem tests, not native AutomationStore qualification."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "automation_1.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.addCleanup(self.connection.close)
        os.chmod(self.db, 0o600)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA wal_autocheckpoint=0")
        self.connection.executescript("""
            CREATE TABLE automation_meta (schema_version INTEGER, owner_agent_id TEXT);
            CREATE TABLE automation_timer_lifecycle (writer_epoch INTEGER, phase TEXT);
            CREATE TABLE automation_tasks (owner_agent_id TEXT);
            CREATE TABLE automation_runs (state TEXT);
            CREATE TABLE automation_occurrence_lifecycle (state TEXT);
            CREATE TABLE automation_dispatch_outcomes (outcome TEXT);
            CREATE TABLE taskflow_runs (state TEXT);
            CREATE TABLE taskflow_events (event TEXT);
            CREATE TABLE _sqlx_migrations (version INTEGER PRIMARY KEY, success INTEGER, checksum BLOB);
        """)
        self.connection.execute("INSERT INTO automation_meta VALUES (21, ?)", (OWNER,))
        self.connection.execute("INSERT INTO automation_timer_lifecycle VALUES (7, 'draining')")
        self.connection.execute("INSERT INTO automation_tasks VALUES (?)", (OWNER,))
        self.connection.execute("INSERT INTO automation_runs VALUES ('pending')")
        self.connection.execute("INSERT INTO automation_occurrence_lifecycle VALUES ('indeterminate')")
        self.connection.execute("INSERT INTO taskflow_runs VALUES ('running')")
        self.connection.executemany("INSERT INTO _sqlx_migrations VALUES (?, 1, ?)",
                                    [(i, hashlib.sha384(f"fixture-{i}".encode()).digest()) for i in range(1, 22)])
        self.connection.commit()
        self.bundle = self.root / "backup"

    def change(self, sql: str, args: tuple = ()) -> None:
        self.connection.execute(sql, args)
        self.connection.commit()

    def snapshot(self, **kwargs) -> dict:
        return M.snapshot(self.db, self.bundle, OWNER, 21, **kwargs)

    def test_wal_backup_and_create_only_restore_preserve_owner_epoch_and_uncertainty(self) -> None:
        self.change("INSERT INTO automation_dispatch_outcomes VALUES ('uncertain')")
        self.change("INSERT INTO taskflow_events VALUES ('committed-in-wal')")
        receipt = self.snapshot()
        result = M.verify(self.bundle, receipt["manifestSha256"])
        self.assertEqual(result["ownerSnapshot"]["counts"]["queueUnknown"], 1)
        self.assertEqual(result["ownerSnapshot"]["counts"]["taskflow_events"], 1)
        staged = M.restore_stage(self.bundle, self.root / "staged", receipt["manifestSha256"])
        self.assertEqual(staged["writerEpoch"], 7)
        self.assertFalse(staged["epochAdvanced"])
        self.assertFalse(staged["sourceFenced"])
        self.assertFalse(staged["targetAdmitted"])
        observed = M.inspect(self.root / "staged" / M.DATABASE, OWNER, 21)
        self.assertEqual(observed["counts"]["queueUnknown"], 1)
        self.assertEqual(observed["writerEpoch"], 7)

    def test_read_inspection_identifies_its_own_sqlite_not_rust_runtime(self) -> None:
        result = M.inspect(self.db, OWNER, 21)
        self.assertEqual(result["inspectionRuntime"]["pythonSqliteVersion"], sqlite3.sqlite_version)
        self.assertTrue(result["inspectionRuntime"]["sqliteSourceId"])
        self.assertFalse(result["nativeProductExecutionProved"])

    def test_active_timer_rejected_before_commit(self) -> None:
        self.change("UPDATE automation_timer_lifecycle SET phase='active'")
        with self.assertRaises(M.CheckpointError):
            self.snapshot()
        self.assertFalse((self.bundle / M.COMMIT).exists())
        self.assertEqual(self.connection.execute("SELECT phase FROM automation_timer_lifecycle").fetchone(), ("active",))

    def test_wrong_owner_rejected(self) -> None:
        with self.assertRaises(M.CheckpointError):
            M.inspect(self.db, "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c99", 21)

    def test_wrong_schema_rejected(self) -> None:
        with self.assertRaises(M.CheckpointError):
            M.inspect(self.db, OWNER, 19)

    def test_noncanonical_owner_rejected(self) -> None:
        with self.assertRaises(M.CheckpointError):
            M.inspect(self.db, OWNER.upper(), 21)

    def test_foreign_task_rejected(self) -> None:
        self.change("INSERT INTO automation_tasks VALUES ('foreign-agent')")
        with self.assertRaises(M.CheckpointError):
            self.snapshot()

    def test_invalid_lifecycle_rejected(self) -> None:
        self.change("UPDATE automation_timer_lifecycle SET writer_epoch=0")
        with self.assertRaises(M.CheckpointError):
            self.snapshot()

    def test_extra_metadata_row_rejected(self) -> None:
        self.change("INSERT INTO automation_meta VALUES (21, ?)", (OWNER,))
        with self.assertRaises(M.CheckpointError):
            self.snapshot()

    def test_failed_migration_rejected(self) -> None:
        self.change("UPDATE _sqlx_migrations SET success=0 WHERE version=20")
        with self.assertRaises(M.CheckpointError):
            self.snapshot()

    def test_missing_middle_migration_is_not_a_valid_frontier(self) -> None:
        self.change("DELETE FROM _sqlx_migrations WHERE version=13")
        with self.assertRaises(M.CheckpointError):
            self.snapshot()

    def test_migration_frontier_mismatch_rejected(self) -> None:
        self.change("DELETE FROM _sqlx_migrations WHERE version=21")
        with self.assertRaises(M.CheckpointError):
            self.snapshot()

    def test_byte_limit_and_timeout_are_not_success(self) -> None:
        with self.assertRaises(M.CheckpointError):
            self.snapshot(max_bytes=1)
        self.assertFalse((self.bundle / M.COMMIT).exists())
        with self.assertRaises((M.CheckpointError, sqlite3.Error)):
            M.inspect(self.db, OWNER, 21, timeout=0.000000001)

    def test_limits_reject_boolean_or_unbounded_input(self) -> None:
        for value in (True, 0, 2 * 1024**4):
            with self.assertRaises(M.CheckpointError):
                M.limits(value, 60)
        with self.assertRaises(M.CheckpointError):
            M.limits(1024, float("nan"))

    def test_existing_backup_and_staged_target_never_overwritten(self) -> None:
        receipt = self.snapshot()
        before = (self.bundle / M.DATABASE).read_bytes()
        with self.assertRaises(FileExistsError):
            self.snapshot()
        M.restore_stage(self.bundle, self.root / "staged", receipt["manifestSha256"])
        with self.assertRaises(FileExistsError):
            M.restore_stage(self.bundle, self.root / "staged", receipt["manifestSha256"])
        self.assertEqual((self.bundle / M.DATABASE).read_bytes(), before)

    def test_incomplete_bundle_without_commit_marker_rejected(self) -> None:
        receipt = self.snapshot()
        (self.bundle / M.COMMIT).unlink()
        with self.assertRaises(OSError):
            M.verify(self.bundle, receipt["manifestSha256"])

    def test_partial_commit_marker_rejected(self) -> None:
        receipt = self.snapshot()
        (self.bundle / M.COMMIT).write_bytes(b"partial")
        with self.assertRaises(M.CheckpointError):
            M.verify(self.bundle, receipt["manifestSha256"])

    def test_missing_or_changed_retained_digest_rejected(self) -> None:
        self.snapshot()
        for value in ("", "0" * 64, "G" * 64):
            with self.assertRaises(M.CheckpointError):
                M.verify(self.bundle, value)

    def test_checkpoint_bytes_tamper_rejected(self) -> None:
        receipt = self.snapshot()
        with (self.bundle / M.DATABASE).open("r+b") as stream:
            stream.seek(200)
            stream.write(b"tampered")
        with self.assertRaises(M.CheckpointError):
            M.verify(self.bundle, receipt["manifestSha256"])

    def test_manifest_tamper_rejected(self) -> None:
        receipt = self.snapshot()
        value = json.loads((self.bundle / M.MANIFEST).read_bytes())
        value["ownerSnapshot"]["writerEpoch"] += 1
        (self.bundle / M.MANIFEST).write_bytes(M.canonical(value))
        with self.assertRaises(M.CheckpointError):
            M.verify(self.bundle, receipt["manifestSha256"])

    def test_even_rehashed_manifest_cannot_grant_authority(self) -> None:
        self.snapshot()
        value = json.loads((self.bundle / M.MANIFEST).read_bytes())
        value["targetAdmitted"] = True
        raw = M.canonical(value)
        (self.bundle / M.MANIFEST).write_bytes(raw)
        new_hash = M.digest(raw)
        (self.bundle / M.COMMIT).write_text(new_hash + "\n")
        with self.assertRaises(M.CheckpointError):
            M.verify(self.bundle, new_hash)

    def test_sealed_checkpoint_sidecars_rejected(self) -> None:
        receipt = self.snapshot()
        (self.bundle / (M.DATABASE + "-wal")).write_bytes(b"")
        with self.assertRaises(M.CheckpointError):
            M.verify(self.bundle, receipt["manifestSha256"])

    def test_symlink_hardlink_and_nonprivate_database_rejected(self) -> None:
        alias = self.root / "alias.sqlite3"
        alias.symlink_to(self.db)
        with self.assertRaises(M.CheckpointError):
            M.inspect(alias, OWNER, 21)
        alias.unlink()
        os.link(self.db, alias)
        with self.assertRaises(M.CheckpointError):
            M.inspect(self.db, OWNER, 21)
        alias.unlink()
        os.chmod(self.db, 0o644)
        with self.assertRaises(M.CheckpointError):
            M.inspect(self.db, OWNER, 21)

    def test_manifest_duplicate_keys_rejected(self) -> None:
        with self.assertRaises(M.CheckpointError):
            M.json_object(b'{"targetAdmitted":false,"targetAdmitted":true}')

    def test_actual_child_process_exit_before_commit_leaves_no_usable_backup(self) -> None:
        module_path = str(Path(M.__file__).resolve())
        code = f'''
import importlib.util, os
from pathlib import Path
s = importlib.util.spec_from_file_location("checkpoint", {module_path!r})
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
original = m.create_file
def crash_before_manifest(path, contents):
    if path.name == m.MANIFEST:
        os._exit(77)
    original(path, contents)
m.create_file = crash_before_manifest
m.snapshot(Path({str(self.db)!r}), Path({str(self.bundle)!r}), {OWNER!r}, 21)
'''
        result = subprocess.run([sys.executable, "-c", code], timeout=10, capture_output=True)
        self.assertEqual(result.returncode, 77, result.stderr.decode())
        self.assertTrue((self.bundle / M.DATABASE).exists())
        self.assertFalse((self.bundle / M.COMMIT).exists())
        self.assertEqual(M.inspect(self.db, OWNER, 21)["writerEpoch"], 7)

    def test_long_retained_history_is_copied_and_counted_without_row_materialization(self) -> None:
        self.connection.executemany("INSERT INTO taskflow_events VALUES (?)", ((f"event-{i}",) for i in range(100_000)))
        self.connection.commit()
        receipt = self.snapshot(timeout=20)
        verified = M.verify(self.bundle, receipt["manifestSha256"], timeout=20)
        self.assertEqual(verified["ownerSnapshot"]["counts"]["taskflow_events"], 100_000)
        self.assertGreater(verified["pagesCopied"], 128)


if __name__ == "__main__":
    unittest.main()
