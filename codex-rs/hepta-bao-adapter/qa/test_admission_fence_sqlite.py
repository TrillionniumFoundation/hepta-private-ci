"""Execute real AuthBus migrations and SQLite failure boundaries, not Rust tests."""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

MIGRATIONS = Path(__file__).resolve().parents[2] / 'hepta-authbus' / 'migrations'
EFFECT = b'E' * 32
OPERATION = 'operation:sql-admission-test'


def connection(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA synchronous=FULL')
    return db


def insert_reservation(db: sqlite3.Connection, *, archive: bool = False) -> None:
    zero, one = (0).to_bytes(8, 'big'), (1).to_bytes(8, 'big')
    table = 'authbus_quota_reservation_archive' if archive else 'authbus_quota_reservation'
    values = [
        'reservation:sql-test', OPERATION, 'quota:sql-test', 'period:sql-test',
        'principal:sql-test', one, EFFECT, 'policy:sql-test', one, b'P' * 32,
        'cancelled' if archive else 'held', one, one, zero, zero,
        None, None, None, None,
    ]
    if archive:
        values.append(one)
    db.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in values)})', values)


def abrupt_seal(path: str, committed: bool) -> None:
    # A subprocess exits without closing the connection. This is process-crash
    # recovery evidence, not storage-device power-loss qualification.
    db = connection(path)
    db.execute('BEGIN IMMEDIATE')
    db.execute('INSERT INTO authbus_operation_admission_fence VALUES (?, ?)', (OPERATION, EFFECT))
    if committed:
        db.execute('COMMIT')
    os._exit(0)


class AdmissionFenceSqliteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / 'authority.sqlite'
        self.db = connection(self.path)
        self.addCleanup(self.db.close)
        self.assertEqual(self.db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        migrations = sorted(MIGRATIONS.glob('*.sql'))
        self.assertTrue(any(p.name == '0005_operation_admission_fence.sql' for p in migrations))
        for path in migrations:
            self.db.executescript(path.read_text())
        zero, one = (0).to_bytes(8, 'big'), (1).to_bytes(8, 'big')
        self.db.execute('INSERT INTO authbus_quota_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('quota:sql-test', 'principal:sql-test', b'S' * 32, 'request', 'period:sql-test',
                         one, one, zero, zero, one))
        self.db.execute('UPDATE authbus_authority_checkpoint_dirty SET dirty=0')

    def seal(self) -> None:
        self.db.execute('INSERT INTO authbus_operation_admission_fence VALUES (?, ?)', (OPERATION, EFFECT))

    def test_seal_is_immutable_and_marks_checkpoint_dirty(self) -> None:
        self.seal()
        self.assertEqual(self.db.execute('SELECT dirty FROM authbus_authority_checkpoint_dirty').fetchone(), (1,))
        for sql in ['DELETE FROM authbus_operation_admission_fence',
                    'UPDATE authbus_operation_admission_fence SET effect_digest=zeroblob(32)']:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
        self.assertEqual(self.db.execute('SELECT operation_id,effect_digest FROM authbus_operation_admission_fence').fetchall(), [(OPERATION, EFFECT)])

    def test_committed_seal_rejects_late_reservation(self) -> None:
        self.seal()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'admission is fenced'):
            insert_reservation(self.db)
        self.assertEqual(self.db.execute('SELECT count(*) FROM authbus_quota_reservation').fetchone(), (0,))

    def test_hot_reservation_blocks_false_absence(self) -> None:
        insert_reservation(self.db)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'already has a reservation'):
            self.seal()

    def test_archived_reservation_blocks_false_absence(self) -> None:
        insert_reservation(self.db, archive=True)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'already has a reservation'):
            self.seal()

    def test_writer_serialization_then_committed_seal_blocks_waiting_connection(self) -> None:
        other = connection(self.path)
        self.addCleanup(other.close)
        other.execute('PRAGMA busy_timeout=1')
        self.db.execute('BEGIN IMMEDIATE')
        self.seal()
        with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
            other.execute('BEGIN IMMEDIATE')
        self.db.execute('COMMIT')
        other.execute('BEGIN IMMEDIATE')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'admission is fenced'):
            insert_reservation(other)
        other.execute('ROLLBACK')

    def test_rolled_back_seal_does_not_invent_a_committed_denial(self) -> None:
        self.db.execute('BEGIN IMMEDIATE')
        self.seal()
        self.db.execute('ROLLBACK')
        self.assertEqual(self.db.execute('SELECT dirty FROM authbus_authority_checkpoint_dirty').fetchone(), (0,))
        insert_reservation(self.db)

    def test_process_exit_before_commit_recovers_predecessor(self) -> None:
        self.crash_case(committed=False)
        self.assertEqual(self.db.execute('SELECT count(*) FROM authbus_operation_admission_fence').fetchone(), (0,))
        insert_reservation(self.db)

    def test_process_exit_after_commit_preserves_fence(self) -> None:
        self.crash_case(committed=True)
        self.assertEqual(self.db.execute('SELECT count(*) FROM authbus_operation_admission_fence').fetchone(), (1,))
        with self.assertRaises(sqlite3.IntegrityError):
            insert_reservation(self.db)

    def crash_case(self, *, committed: bool) -> None:
        child = multiprocessing.get_context('spawn').Process(target=abrupt_seal, args=(str(self.path), committed))
        child.start()
        child.join(timeout=10)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
            self.fail('synthetic SQLite crash process did not exit')
        self.assertEqual(child.exitcode, 0)
        self.assertEqual(self.db.execute('PRAGMA quick_check').fetchone(), ('ok',))
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
