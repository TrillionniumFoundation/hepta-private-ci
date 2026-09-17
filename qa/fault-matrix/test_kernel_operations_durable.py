import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "codex-rs/hepta-operations/migrations/0001_durable_operations.sql"


def u64(value: int) -> bytes:
    return value.to_bytes(8, "big")


def operation_values(operation_id: str):
    return (
        "scope:fault-matrix",
        operation_id,
        b"s" * 32,
        b"r" * 32,
        b"p" * 32,
        "destination:fault-matrix",
        None,
        u64(3),
        u64(9),
        u64(1),
        1,
        1,
    )


def outbox_values(operation_id: str):
    return (
        "scope:fault-matrix",
        operation_id,
        "destination:fault-matrix",
        b"p" * 32,
        1,
        1,
        1,
    )


class DurableKernelOperationsFaultMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "operations.sqlite"
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=1.0)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def abrupt_prepare(self, operation_id: str, commit: bool) -> None:
        script = r'''
import os, sqlite3, sys
p, operation_id, commit = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
u64 = lambda value: value.to_bytes(8, "big")
db = sqlite3.connect(p, isolation_level=None, timeout=1.0)
db.execute("PRAGMA synchronous=FULL")
db.execute("PRAGMA foreign_keys=ON")
db.execute("BEGIN IMMEDIATE")
db.execute(
    "INSERT INTO operation_records "
    "(scope_id,operation_id,scope_digest,request_digest,payload_digest,destination_id,"
    "predecessor_operation_id,writer_generation,authority_epoch,revision,state,created_at_ms,updated_at_ms) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?)",
    ("scope:fault-matrix", operation_id, b"s"*32, b"r"*32, b"p"*32,
     "destination:fault-matrix", None, u64(3), u64(9), u64(1), 1, 1),
)
if commit:
    db.execute(
        "INSERT INTO cross_owner_outbox "
        "(scope_id,operation_id,destination_id,payload_digest,state,fence,attempts,next_eligible_ms,created_at_ms,updated_at_ms) "
        "VALUES (?,?,?,?,'queued',0,0,?,?,?)",
        ("scope:fault-matrix", operation_id, "destination:fault-matrix", b"p"*32, 1, 1, 1),
    )
    db.execute("COMMIT")
os._exit(77)
'''
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.path), operation_id, "1" if commit else "0"],
            timeout=15,
            check=False,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 77, result.stderr.decode(errors="replace"))

    def counts(self, operation_id: str) -> tuple[int, int]:
        operations = self.db.execute(
            "SELECT COUNT(*) FROM operation_records WHERE operation_id=?", (operation_id,)
        ).fetchone()[0]
        outbox = self.db.execute(
            "SELECT COUNT(*) FROM cross_owner_outbox WHERE operation_id=?", (operation_id,)
        ).fetchone()[0]
        return operations, outbox

    def test_ops_01_abrupt_exit_before_commit_leaves_no_partial_dual_write(self):
        operation_id = "operation:crash-before-commit"
        self.abrupt_prepare(operation_id, False)
        self.assertEqual(self.counts(operation_id), (0, 0))

    def test_ops_01_abrupt_exit_after_commit_recovers_one_operation_and_outbox(self):
        operation_id = "operation:crash-after-commit"
        self.abrupt_prepare(operation_id, True)
        self.assertEqual(self.counts(operation_id), (1, 1))
        self.db.close()
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=1.0)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.assertEqual(self.counts(operation_id), (1, 1))
        self.assertEqual(self.db.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_ops_03_two_writers_cannot_hold_begin_immediate(self):
        self.db.execute("BEGIN IMMEDIATE")
        other = sqlite3.connect(self.path, isolation_level=None, timeout=0.01)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()
            self.db.execute("ROLLBACK")

    def test_ops_04_injected_outbox_write_failure_rolls_back_operation(self):
        self.db.execute(
            "CREATE TRIGGER fixture_disk_full BEFORE INSERT ON cross_owner_outbox "
            "BEGIN SELECT RAISE(ABORT, 'fixture disk full'); END"
        )
        operation_id = "operation:disk-full"
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "INSERT INTO operation_records "
                "(scope_id,operation_id,scope_digest,request_digest,payload_digest,destination_id,"
                "predecessor_operation_id,writer_generation,authority_epoch,revision,state,created_at_ms,updated_at_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?)",
                operation_values(operation_id),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO cross_owner_outbox "
                    "(scope_id,operation_id,destination_id,payload_digest,state,fence,attempts,next_eligible_ms,created_at_ms,updated_at_ms) "
                    "VALUES (?,?,?,?,'queued',0,0,?,?,?)",
                    outbox_values(operation_id),
                )
        finally:
            self.db.execute("ROLLBACK")
        self.assertEqual(self.counts(operation_id), (0, 0))

    def test_ops_04_corrupt_database_does_not_pass_integrity_check(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
        with self.path.open("r+b") as handle:
            handle.seek(0)
            handle.write(b"BROKEN!!")
            handle.flush()
            os.fsync(handle.fileno())
        with self.assertRaises(sqlite3.DatabaseError):
            sqlite3.connect(self.path).execute("PRAGMA quick_check").fetchone()
        self.db = sqlite3.connect(":memory:")


if __name__ == "__main__":
    unittest.main()
