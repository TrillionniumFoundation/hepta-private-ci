"""Atomic publication, expiry, restart and quota tests with an actual database."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cell_training_queue import TrainingQueue, TrainingQueueError

SOURCE, FEATURE = "a" * 64, "b" * 64


class TrainingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "queue.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, queue, generation=1, now=10, deadline=1000, **options):
        return queue.submit("cell", generation, SOURCE, FEATURE, {"samples": [1, 2]},
                            now_ns=now, deadline_ns=deadline, **options)

    def test_restart_reclaims_expired_lease_and_rejects_old_worker(self):
        with TrainingQueue(self.path) as queue:
            job = self.submit(queue)
            first = queue.claim(now_ns=11, lease_ns=10)
        with TrainingQueue(self.path) as queue:
            second = queue.claim(now_ns=22, lease_ns=10)
            self.assertEqual((second["job_id"], second["attempt"]), (job, 2))
            self.assertNotEqual(first["lease_token"], second["lease_token"])
            with self.assertRaises(TrainingQueueError):
                queue.complete(job, first["lease_token"], {"weight": 1}, now_ns=23)
            result = queue.complete(job, second["lease_token"], {"weight": 2}, now_ns=24)
        with TrainingQueue(self.path) as queue:
            publication = queue.read_current("cell")
            self.assertEqual((publication["generation"], publication["result"],
                              publication["result_sha256"]), (1, {"weight": 2}, result))

    def test_supersession_blocks_old_publication_and_hides_previous_generation(self):
        with TrainingQueue(self.path) as queue:
            old = self.submit(queue)
            lease = queue.claim(now_ns=11)
            queue.complete(old, lease["lease_token"], {"weight": 1}, now_ns=12)
            self.submit(queue, generation=2, now=13)
            self.assertIsNone(queue.read_current("cell"))
            with self.assertRaises(TrainingQueueError):
                queue.complete(old, lease["lease_token"], {"weight": 1}, now_ns=14)
            lease2 = queue.claim(now_ns=15)
            self.submit(queue, generation=3, now=16)
            with self.assertRaises(TrainingQueueError):
                queue.complete(lease2["job_id"], lease2["lease_token"], {"weight": 2}, now_ns=17)
            self.assertEqual(queue.accounting()["jobs_by_status"], {"done": 1, "pending": 1, "superseded": 1})

    def test_exact_retry_is_idempotent_but_conflicting_retry_rejects(self):
        with TrainingQueue(self.path) as queue:
            job = self.submit(queue)
            self.assertEqual(self.submit(queue, now=11), job)
            lease = queue.claim(now_ns=12)
            digest = queue.complete(job, lease["lease_token"], {"weight": 1}, now_ns=13)
            self.assertEqual(queue.complete(job, lease["lease_token"], {"weight": 1}, now_ns=14), digest)
            with self.assertRaises(TrainingQueueError):
                queue.complete(job, lease["lease_token"], {"weight": 2}, now_ns=15)
            self.assertEqual(queue.accounting()["jobs_by_status"], {"done": 1})

    def test_deadline_quota_and_clock_reject_without_advancing_current_source(self):
        with TrainingQueue(self.path, max_jobs=1, max_payload_bytes=64) as queue:
            job = self.submit(queue, deadline=30)
            lease = queue.claim(now_ns=11, lease_ns=10)
            with self.assertRaises(TrainingQueueError):
                queue.complete(job, lease["lease_token"], {"weight": 1}, now_ns=21)
            with self.assertRaises(TrainingQueueError):
                self.submit(queue, generation=2, now=22)
            self.assertEqual(queue.db.execute("SELECT generation FROM frontier").fetchone()[0], 1)
            self.assertIsNone(queue.claim(now_ns=31))
            self.assertEqual(queue.accounting()["jobs_by_status"], {"expired": 1})
            with self.assertRaises(TrainingQueueError):
                queue.claim(now_ns=30)

    def test_invalid_scalar_and_oversized_payload_reject_before_job(self):
        with TrainingQueue(self.path, max_payload_bytes=64) as queue:
            for gen in (True, 0, 1.0):
                with self.subTest(gen=gen), self.assertRaises(TrainingQueueError):
                    self.submit(queue, generation=gen)
            with self.assertRaises(TrainingQueueError):
                queue.submit("cell", 1, SOURCE, FEATURE, {"x": "z" * 100}, deadline_ns=50, now_ns=10)
            self.assertEqual(queue.accounting()["jobs_by_status"], {})

    def test_actual_callback_publishes_and_failure_stays_unpublished(self):
        import time
        with TrainingQueue(self.path) as queue:
            queue.submit("cell", 1, SOURCE, FEATURE, {"x": [2, 3]}, deadline_ns=time.time_ns() + 10**10)
            receipt = queue.run_one(lambda job: {"sum": sum(job["payload"]["x"])})
            self.assertGreater(receipt["wall_ns"], 0)
            self.assertEqual(queue.read_current("cell")["result"], {"sum": 5})
            queue.submit("cell", 2, SOURCE, FEATURE, {}, deadline_ns=time.time_ns() + 10**10)
            def fail(_):
                raise RuntimeError("training stopped")
            with self.assertRaises(RuntimeError):
                queue.run_one(fail)
            self.assertIsNone(queue.read_current("cell"))
            self.assertEqual(queue.accounting()["jobs_by_status"], {"done": 1, "failed": 1})

    def test_fresh_process_recovers_lease_and_persists_clock_fence(self):
        with TrainingQueue(self.path) as queue:
            self.submit(queue)
            first = queue.claim(now_ns=11, lease_ns=10)
        code = """
import sys
from cell_training_queue import TrainingQueue
with TrainingQueue(sys.argv[1]) as queue:
    job = queue.claim(now_ns=22, lease_ns=10)
    assert job['attempt'] == 2
    queue.complete(job['job_id'], job['lease_token'], {'weight': 9}, now_ns=23)
"""
        subprocess.run([sys.executable, "-c", code, str(self.path)], check=True,
                       cwd=Path(__file__).parent, capture_output=True, text=True)
        with TrainingQueue(self.path) as queue:
            self.assertEqual(queue.read_current("cell")["result"], {"weight": 9})
            with self.assertRaises(TrainingQueueError):
                queue.claim(now_ns=22)
            with self.assertRaises(TrainingQueueError):
                queue.complete(first["job_id"], first["lease_token"], {"weight": 1}, now_ns=24)


if __name__ == "__main__":
    unittest.main()
