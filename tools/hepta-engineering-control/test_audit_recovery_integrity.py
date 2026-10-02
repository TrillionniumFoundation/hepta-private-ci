"""The ordinary owner must reject the same corrupt history as suffix reads."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from control_engineering_v2 import EngineeringError, EngineeringStore, WorkEnvelope
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


class AuditRecoveryIntegrityTests(unittest.TestCase):
    def create_history(self, database):
        with EngineeringStore(database) as store:
            for number in range(2):
                store.issue_work_envelope(WorkEnvelope(
                    f"envelope-{number}", "a" * 40, "b" * 40, "c" * 64,
                    "d" * 64, "owner", ("src",), tuple(sorted(DENIED_AUTHORITIES)),
                    4, 1000,
                ), now_ns=10 + number)

    def test_reopen_rejects_sequence_gaps_without_rewriting_history(self):
        for sequence in (1, 2):
            with self.subTest(sequence=sequence), tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / "owner.sqlite3"
                self.create_history(database)
                with sqlite3.connect(database) as connection:
                    connection.execute("UPDATE audit_events SET sequence=? WHERE sequence=?",
                                       (sequence + 10, sequence))
                    before = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
                with self.assertRaisesRegex(EngineeringError, "audit_chain"):
                    EngineeringStore(database)
                with sqlite3.connect(database) as connection:
                    self.assertEqual(before, connection.execute(
                        "SELECT * FROM audit_events ORDER BY sequence").fetchall())

    def test_reopen_rejects_semantically_equal_noncanonical_payload(self):
        for transform in (
            lambda raw: json.dumps(json.loads(raw), indent=2).encode(),
            lambda raw: b'{"envelopeId":"discarded",' + raw[1:],
        ):
            with self.subTest(transform=transform), tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / "owner.sqlite3"
                self.create_history(database)
                with sqlite3.connect(database) as connection:
                    raw = connection.execute("SELECT payload_json FROM audit_events WHERE sequence=1").fetchone()[0]
                    rewritten = transform(raw)
                    self.assertEqual(json.loads(raw), json.loads(rewritten))
                    connection.execute("UPDATE audit_events SET payload_json=? WHERE sequence=1", (rewritten,))
                with self.assertRaisesRegex(EngineeringError, "audit_chain"):
                    EngineeringStore(database)

    def test_valid_history_still_reopens_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            self.create_history(database)
            with sqlite3.connect(database) as connection:
                before = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
            with EngineeringStore(database) as store:
                store.verify_audit_chain()
                self.assertEqual(before, [tuple(row) for row in store.connection.execute(
                    "SELECT * FROM audit_events ORDER BY sequence")])


if __name__ == "__main__":
    unittest.main()
