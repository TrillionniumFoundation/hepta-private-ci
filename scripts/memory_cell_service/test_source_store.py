"""Immediate source semantics and atomic outbox behavior, without a model."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from service_types import ReadStatus, SourceConflict
from source_store import SourceStore


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "sources.sqlite3"
        self.store = SourceStore(self.path, "research:test")

    def test_write_is_immediately_readable_and_survives_restart(self):
        self.assertEqual(self.store.read("Alice", "color").status, ReadStatus.UNKNOWN)
        receipt = self.store.write("source:1", "Alice", "color", "red")
        restarted = SourceStore(self.path, "research:test")
        result = restarted.read("Alice", "color")
        self.assertEqual(
            (result.status, result.answer, result.origin),
            (ReadStatus.ANSWERED, "red", "source_overlay"),
        )
        self.assertEqual(result.source_roots, (receipt.source_digest,))
        with restarted.transaction(write=False) as db:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (receipt.training_job_id,)
                ).fetchone()[0],
                "queued",
            )

    def test_conflict_correction_and_revocation_are_explicit(self):
        first = self.store.write("source:1", "Alice", "color", "red")
        self.store.write("source:2", "Alice", "color", "blue")
        conflict = self.store.read("Alice", "color")
        self.assertEqual(
            (conflict.status, conflict.answer), (ReadStatus.CONFLICT, None)
        )
        self.store.correct("source:1", "blue", expected_revision=0)
        self.assertEqual(self.store.read("Alice", "color").answer, "blue")
        self.assertIn(first.source_digest, self.store.snapshot()["revoked"])
        self.store.revoke("source:2", expected_revision=0)
        self.assertEqual(self.store.read("Alice", "color").answer, "blue")
        self.store.revoke("source:1", expected_revision=1)
        final = self.store.read("Alice", "color")
        self.assertEqual((final.status, final.answer), (ReadStatus.REVOKED, None))
        self.assertEqual(self.store.snapshot()["facts"], [])

    def test_revision_cas_and_revoked_identity_cannot_be_reused(self):
        self.store.write("source:1", "Alice", "color", "red")
        self.store.correct("source:1", "blue", expected_revision=0)
        before = self.store.snapshot()
        with self.assertRaises(SourceConflict):
            self.store.correct("source:1", "green", expected_revision=0)
        self.assertEqual(before, self.store.snapshot())
        self.store.revoke("source:1", expected_revision=1)
        with self.assertRaises(SourceConflict):
            self.store.write("source:1", "Alice", "color", "green", expected_revision=1)

    def test_queue_failure_rolls_back_source_and_old_job_supersession(self):
        self.store.write("source:1", "Alice", "color", "red")
        before = self.store.snapshot()
        with patch.object(
            self.store, "_enqueue", side_effect=RuntimeError("disk failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "disk failed"):
                self.store.correct("source:1", "blue", expected_revision=0)
        self.assertEqual(before, self.store.snapshot())
        with self.store.transaction(write=False) as db:
            self.assertEqual(
                [r[0] for r in db.execute("SELECT state FROM jobs")], ["queued"]
            )

    def test_conflicting_facts_are_excluded_from_training_snapshot(self):
        self.store.write("source:1", "Alice", "color", "red")
        self.store.write("source:2", "Alice", "color", "blue")
        self.store.write("source:3", "Bob", "color", "green")
        snapshot = self.store.snapshot()
        self.assertEqual([f["entity"] for f in snapshot["facts"]], ["Bob"])
        self.assertEqual(snapshot["conflicts"][0]["entity"], "Alice")
        self.assertEqual(len(snapshot["roots"]), 3)

    def test_owner_scope_and_cell_identity_cannot_change_on_reopen(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            SourceStore(self.path, "other")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            SourceStore(self.path, "research:test", "another-cell")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            SourceStore(self.path, "research:test", role="procedural")

    def test_source_payload_mutation_is_detected_before_read(self):
        self.store.write("source:1", "Alice", "color", "red")
        with self.store.transaction() as db:
            db.execute("UPDATE sources SET payload=replace(payload,'red','blue')")
        with self.assertRaisesRegex(ValueError, "source bytes"):
            self.store.read("Alice", "color")


if __name__ == "__main__":
    unittest.main()
