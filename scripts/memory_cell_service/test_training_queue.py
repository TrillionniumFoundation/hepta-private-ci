"""Crash recovery and expired-worker fencing use durable independent connections."""

from pathlib import Path
import tempfile
import unittest

from service_types import LeaseLost
from source_store import SourceStore
from training_queue import TrainingQueue


class TrainingQueueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "source.sqlite3"
        self.store = SourceStore(self.path, "scope")
        self.queue = TrainingQueue(self.store)

    def test_only_latest_queued_snapshot_is_claimed(self):
        first = self.store.write("s1", "Alice", "color", "red")
        second = self.store.correct("s1", "blue", expected_revision=0)
        lease = self.queue.claim("worker", now=10)
        self.assertEqual(lease.job_id, second.training_job_id)
        self.assertEqual(lease.snapshot["facts"][0]["value"], "blue")
        self.assertEqual(
            self.queue.status(first.training_job_id)["state"], "superseded"
        )
        self.assertIsNone(self.queue.claim("other-worker", now=11))

    def test_expired_attempt_is_recovered_but_old_worker_is_fenced(self):
        self.store.write("s1", "Alice", "color", "red")
        first = self.queue.claim("worker", lease_seconds=5, now=10)
        restarted = TrainingQueue(SourceStore(self.path, "scope"))
        second = restarted.claim("replacement", now=15)
        self.assertEqual((second.job_id, second.attempt), (first.job_id, 2))
        self.assertNotEqual(first.token, second.token)
        with self.assertRaises(LeaseLost):
            self.queue.stage(
                first, {"source_snapshot_digest": first.snapshot["digest"]}, now=16
            )
        restarted.renew(second, lease_seconds=20, now=16)
        self.assertIsNone(self.queue.claim("third", now=20))

    def test_staged_candidate_survives_worker_crash(self):
        self.store.write("s1", "Alice", "color", "red")
        first = self.queue.claim("worker", lease_seconds=5, now=10)
        candidate = {
            "source_snapshot_digest": first.snapshot["digest"],
            "manifest_sha256": "a" * 64,
        }
        self.queue.stage(first, candidate, now=11)
        second = self.queue.claim("replacement", now=15)
        self.assertEqual(second.candidate, candidate)
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.queue.stage(second, candidate | {"manifest_sha256": "b" * 64}, now=16)

    def test_retries_are_bounded_and_old_epochs_are_not_restarted(self):
        receipt = self.store.write("s1", "Alice", "color", "red")
        queue = TrainingQueue(self.store, max_attempts=1)
        queue.claim("worker", lease_seconds=1, now=1)
        self.assertIsNone(queue.claim("replacement", now=2))
        self.assertEqual(queue.status(receipt.training_job_id)["state"], "failed")
        receipt = self.store.correct("s1", "blue", expected_revision=0)
        queue.claim("worker", lease_seconds=1, now=3)
        latest = self.store.correct("s1", "green", expected_revision=1)
        replacement = queue.claim("replacement", now=4)
        self.assertEqual(replacement.job_id, latest.training_job_id)
        self.assertEqual(queue.status(receipt.training_job_id)["state"], "superseded")

    def test_staged_exception_retries_exact_candidate_until_budget_exhausted(self):
        receipt = self.store.write("s1", "Alice", "color", "red")
        queue = TrainingQueue(self.store, max_attempts=2)
        first = queue.claim("worker", now=10)
        candidate = {
            "source_snapshot_digest": first.snapshot["digest"],
            "manifest_sha256": "a" * 64,
        }
        queue.stage(first, candidate, now=11)
        queue.fail(first, OSError("publication interrupted"), now=12)
        self.assertEqual(queue.status(receipt.training_job_id)["state"], "queued")
        second = queue.claim("recovery", now=13)
        self.assertEqual(second.candidate, candidate)
        self.assertNotEqual(second.token, first.token)
        with self.assertRaises(LeaseLost):
            queue.fail(first, "old worker cannot end a newer attempt", now=14)
        queue.fail(second, OSError("still cannot publish"), now=14)
        self.assertEqual(queue.status(receipt.training_job_id)["state"], "failed")
        self.assertIsNone(queue.claim("excess-retry", now=15))


if __name__ == "__main__":
    unittest.main()
