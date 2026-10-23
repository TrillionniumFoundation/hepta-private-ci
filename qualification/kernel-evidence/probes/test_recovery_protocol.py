"""Independent SQLite/WAL protocol oracle, NOT execution of the Rust library."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RecoveryProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "evidence.sqlite")
        self.reader = sqlite3.connect(path, isolation_level=None)
        self.writer = sqlite3.connect(path, isolation_level=None)
        self.reader.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE migrations(version INTEGER PRIMARY KEY);
            INSERT INTO migrations VALUES (1);
            CREATE TABLE evidence(seq INTEGER PRIMARY KEY, envelope TEXT, principal TEXT,
                epoch INTEGER, key_digest TEXT, message_id TEXT, auth_sequence INTEGER,
                auth_expiry INTEGER, recorded_at INTEGER);
            CREATE TABLE replay(sequence INTEGER NOT NULL);
            INSERT INTO replay VALUES (0);
        """)

    def tearDown(self) -> None:
        self.reader.close()
        self.writer.close()
        self.tmp.cleanup()

    def append(self) -> None:
        self.writer.execute("BEGIN IMMEDIATE")
        self.writer.execute("INSERT INTO evidence VALUES (1, '{}', 'alice', 1, 'key-1', 'm-1', 1, 2, 1)")
        self.writer.execute("UPDATE replay SET sequence = 1")
        self.writer.execute("COMMIT")

    def state(self) -> tuple[int, int]:
        return (self.reader.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                self.reader.execute("SELECT sequence FROM replay").fetchone()[0])

    def test_legacy_independent_reads_can_mix_epochs(self) -> None:
        old_count = self.reader.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        self.append()
        new_replay = self.reader.execute("SELECT sequence FROM replay").fetchone()[0]
        self.assertEqual((old_count, new_replay), (0, 1))

    def test_one_read_transaction_never_mixes_epochs(self) -> None:
        self.reader.execute("BEGIN")
        self.reader.execute("SELECT COUNT(*) FROM migrations").fetchone()
        self.append()
        self.assertEqual(self.state(), (0, 0))
        self.reader.execute("COMMIT")
        self.assertEqual(self.state(), (1, 1))

    def test_rollback_does_not_leave_partial_evidence_or_replay(self) -> None:
        self.writer.execute("BEGIN IMMEDIATE")
        self.writer.execute("INSERT INTO evidence VALUES (1, '{}', 'alice', 1, 'key-1', 'm-1', 1, 2, 1)")
        self.writer.execute("UPDATE replay SET sequence = 1")
        self.writer.execute("ROLLBACK")
        self.assertEqual(self.state(), (0, 0))

    def test_seven_authentication_fields_are_individually_committed(self) -> None:
        self.append()
        original = self.reader.execute("SELECT * FROM evidence").fetchone()
        for index in range(2, 9):
            with self.subTest(field=index):
                changed = list(original)
                changed[index] = changed[index] + 1 if isinstance(changed[index], int) else changed[index] + '-changed'
                self.assertNotEqual(digest(original), digest(changed))
                self.assertEqual(digest(original[:2]), digest(changed[:2]))

    def test_store_identity_and_version_are_part_of_domain(self) -> None:
        row = ['envelope', 'issuer', 'key']
        self.assertNotEqual(digest([2, 'store:a', row]), digest([2, 'store:b', row]))
        self.assertNotEqual(digest([1, 'store:a', row]), digest([2, 'store:a', row]))

    def test_digest_pin_rejects_semantically_valid_old_registry(self) -> None:
        old = {'issuer': 'alice', 'revoked': False}
        current = {'issuer': 'alice', 'revoked': True}
        admitted_pin = digest(current)
        self.assertNotEqual(digest(old), admitted_pin)
        self.assertEqual(digest(current), admitted_pin)

    def test_keyset_pages_hold_the_same_snapshot(self) -> None:
        self.reader.execute("BEGIN")
        first_page = self.reader.execute("SELECT seq FROM evidence WHERE seq > 0 ORDER BY seq LIMIT 32").fetchall()
        self.append()
        second_page = self.reader.execute("SELECT seq FROM evidence WHERE seq > 0 ORDER BY seq LIMIT 32").fetchall()
        self.assertEqual(first_page, second_page)
        self.reader.execute("COMMIT")
        self.assertEqual(self.state(), (1, 1))

    def test_length_probe_is_in_bytes_not_unicode_characters(self) -> None:
        value = '证据' * 12
        observed = self.reader.execute("SELECT length(CAST(? AS BLOB))", (value,)).fetchone()[0]
        self.assertEqual(observed, len(value.encode()))
        self.assertGreater(observed, len(value))


if __name__ == '__main__':
    unittest.main(verbosity=2)
