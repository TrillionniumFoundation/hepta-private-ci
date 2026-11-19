"""Original subprocess wait, exact-effect readback and conservative UNKNOWN."""

import json
from pathlib import Path
import tempfile
import time
import unittest

from async_owner_wait import start_async_owner


class AsyncOwnerWaitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "owner"
        self.task = {
            "id": "original",
            "goals": ["payload"],
            "version": 2,
            "fault": "normal",
        }

    def start(self, task=None):
        owner = start_async_owner(
            self.path,
            task or self.task,
            0,
            "original:0",
            time.monotonic_ns() + 5_000_000_000,
        )
        self.addCleanup(owner.close)
        observed = owner.observer().observe(time.monotonic_ns() + 3_000_000_000)
        self.assertEqual(
            (observed["knowledge"], observed["phase"]), ("UNKNOWN", "WAITING")
        )
        return owner

    def test_real_pipe_wait_then_original_payload_without_redispatch(self):
        owner = self.start()
        observer = owner.observer()
        self.assertEqual(list((self.path / "effects").iterdir()), [])
        owner.release()
        result = observer.observe(time.monotonic_ns() + 3_000_000_000)
        self.assertEqual(
            (result["knowledge"], result["invocation"]),
            ("CONFIRMED_COMPLETE", "original:0"),
        )
        with self.assertRaises(ValueError):
            owner.release()
        self.assertEqual(len(list((self.path / "effects").iterdir())), 1)
        self.assertEqual(
            json.loads(next((self.path / "effects").glob("*/value")).read_text()),
            {"content": "payload"},
        )

    def test_read_only_wait_timeout_does_not_release_or_create_an_effect(self):
        owner = self.start()
        result = owner.observer().observe(time.monotonic_ns())
        self.assertEqual(
            (result["knowledge"], result["observation_deadline_reached"]),
            ("UNKNOWN", True),
        )
        self.assertEqual(list((self.path / "effects").iterdir()), [])
        owner.release()
        self.assertEqual(
            owner.observer().observe(time.monotonic_ns() + 3_000_000_000)["knowledge"],
            "CONFIRMED_COMPLETE",
        )

    def test_process_exit_without_effect_remains_unknown(self):
        owner = self.start()
        owner._commands.close()  # Original gate EOF; no synthetic success receipt.
        owner._process.join(timeout=3)
        self.assertFalse(owner._process.is_alive())
        result = owner.observer().observe(time.monotonic_ns() + 1_000_000_000)
        self.assertEqual(result["knowledge"], "UNKNOWN")
        self.assertEqual(result["process_exitcode"], 0)
        self.assertEqual(list((self.path / "effects").iterdir()), [])
        owner.close()
        self.assertEqual(
            owner.observer().observe(time.monotonic_ns())["knowledge"], "UNKNOWN"
        )

    def test_foreign_intent_or_payload_cannot_be_reported_complete(self):
        owner = self.start()
        owner.release()
        self.assertEqual(
            owner.observer().observe(time.monotonic_ns() + 3_000_000_000)["knowledge"],
            "CONFIRMED_COMPLETE",
        )
        payload = next((self.path / "effects").glob("*/value"))
        payload.write_text("foreign")
        with self.assertRaisesRegex(ValueError, "payload changed"):
            owner.observer().observe(time.monotonic_ns())

    def test_expired_initial_invocation_is_not_dispatched(self):
        with self.assertRaises(ValueError):
            start_async_owner(
                self.path, self.task, 0, "original:0", time.monotonic_ns() - 1
            )
        self.assertFalse(self.path.exists())

    def test_waiting_original_expires_without_any_mutation(self):
        owner = start_async_owner(
            self.path, self.task, 0, "original:0", time.monotonic_ns() + 1_000_000_000
        )
        self.addCleanup(owner.close)
        observer = owner.observer()
        self.assertEqual(
            observer.observe(time.monotonic_ns() + 2_000_000_000)["phase"], "WAITING"
        )
        expired = observer.observe(time.monotonic_ns() + 2_000_000_000)
        self.assertEqual(
            (
                expired["knowledge"],
                expired["phase"],
                expired["mutation_deadline_reached"],
            ),
            ("UNKNOWN", "EXPIRED", True),
        )
        with self.assertRaises(ValueError):
            owner.release()
        self.assertEqual(list((self.path / "effects").iterdir()), [])

    def test_completed_effect_readback_survives_transport_close(self):
        owner = self.start()
        owner.release()
        observer = owner.observer()
        self.assertEqual(
            observer.observe(time.monotonic_ns() + 3_000_000_000)["knowledge"],
            "CONFIRMED_COMPLETE",
        )
        owner.close()
        self.assertEqual(
            observer.observe(time.monotonic_ns())["knowledge"], "CONFIRMED_COMPLETE"
        )

    def test_opaque_original_result_stays_unknown_after_physical_completion(self):
        owner = self.start({**self.task, "fault": "opaque_after_apply"})
        owner.release()
        observed = owner.observer().observe(time.monotonic_ns() + 3_000_000_000)
        self.assertEqual(
            (observed["phase"], observed["knowledge"]), ("DONE", "UNKNOWN")
        )
        self.assertEqual(len(list((self.path / "effects").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
