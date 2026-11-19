"""Independent async invocation faults; constructed weights, no learning claim."""

import json
import multiprocessing
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

from async_recurrent_lifecycle import AsyncRecurrentLifecycle, _worker
from durable_lifecycle import canonical
from models import Model
from skill_lifecycle import SkillContract, goals_digest


class AsyncRecurrentAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {
            "id": "independent-original",
            "version": 1,
            "goals": ["original payload"],
            "fault": "normal",
        }
        self.model = self.root / "model.npz"
        model = Model("gru", 41)
        model.p["V"][:] = 0
        model.p["c"][:] = (0, 0, 10)
        np.savez(self.model, **model.p)
        self.session = self.root / "session"

    def start(self):
        self.contract = SkillContract(
            self.task["id"],
            1,
            goals_digest(self.task["goals"]),
            time.monotonic_ns() + 60_000_000_000,
            1,
        )
        return AsyncRecurrentLifecycle.start(
            self.task, self.contract, self.model, self.session
        )

    def restore(self):
        return AsyncRecurrentLifecycle.restore(
            self.task, self.contract, self.model, self.session
        )

    def admit(self, driver):
        for _ in range(5):
            driver.step()
            if driver.async_attempt is not None:
                return
        self.fail("no original ensure was selected")

    def finish_original(self, driver):
        driver.release()
        driver._process.join(timeout=5)
        self.assertFalse(driver._process.is_alive())
        result = driver.wait(time.monotonic_ns())
        self.assertEqual(result["knowledge"], "CONFIRMED_COMPLETE")
        return result

    def test_spawn_failure_preserves_uncertainty_and_never_dispatches_again(self):
        driver = self.start()
        self.assertTrue(driver.step())
        with mock.patch(
            "multiprocessing.process.BaseProcess.start",
            side_effect=OSError("spawn failed"),
        ) as spawn:
            with self.assertRaisesRegex(OSError, "spawn failed"):
                driver.step()
            saved = json.loads(canonical(driver.policy))
            self.assertEqual((saved["phase"], driver.unresolved), ("entered", {0}))
            self.assertFalse(driver.step())
            self.assertEqual(driver.policy, saved)
            self.assertEqual(spawn.call_count, 1)
        driver.close()
        restored = self.restore()
        try:
            with (
                mock.patch(
                    "multiprocessing.process.BaseProcess.start",
                    side_effect=AssertionError("second dispatch"),
                ),
                mock.patch.object(
                    restored.model, "choose", side_effect=AssertionError("re-inference")
                ),
            ):
                result = restored.wait(time.monotonic_ns())
                self.assertEqual(
                    (result["knowledge"], result["recovery_query_only"]),
                    ("UNKNOWN", True),
                )
                with self.assertRaises(ValueError):
                    restored.release()
            self.assertEqual(list((self.session / "destination/effects").iterdir()), [])
        finally:
            restored.close()

    def test_failed_original_pipe_send_cannot_be_retried(self):
        driver = self.start()
        self.admit(driver)
        try:
            driver._commands.close()
            with self.assertRaises(OSError):
                driver.release()
            self.assertTrue(driver.async_attempt["release_attempted"])
            with self.assertRaises(ValueError):
                driver.release()
            driver._process.join(timeout=5)
            self.assertFalse(driver._process.is_alive())
            self.assertEqual(driver.wait(time.monotonic_ns())["knowledge"], "UNKNOWN")
            self.assertEqual(list((self.session / "destination/effects").iterdir()), [])
        finally:
            driver.close()
        restored = self.restore()
        try:
            self.assertTrue(restored.async_attempt["release_attempted"])
            with mock.patch.object(
                restored.model, "choose", side_effect=AssertionError("re-inference")
            ):
                self.assertEqual(
                    restored.wait(time.monotonic_ns())["knowledge"], "UNKNOWN"
                )
                with self.assertRaises(ValueError):
                    restored.release()
            self.assertEqual(restored.owner.audit()["effect_count"], 0)
        finally:
            restored.close()

    def test_settled_wait_reads_again_without_reinferring_missing_original(self):
        driver = self.start()
        self.admit(driver)
        try:
            self.finish_original(driver)
            shutil.rmtree(next((self.session / "destination/effects").iterdir()))
            before = (driver.calls, driver.policy["sequence"], driver.policy["hidden"])
            with mock.patch.object(
                driver.model, "choose", side_effect=AssertionError("re-inference")
            ):
                current = driver.wait(time.monotonic_ns())
            self.assertEqual(current["knowledge"], "UNKNOWN")
            self.assertGreater(driver.calls, before[0])
            self.assertEqual(
                (driver.policy["sequence"], driver.policy["hidden"]), before[1:]
            )
            self.assertTrue(driver.async_attempt["settled"])
        finally:
            driver.close()

    def test_missing_settled_effect_never_readmits_original_invocation(self):
        driver = self.start()
        self.admit(driver)
        try:
            self.finish_original(driver)
            historical = json.loads(canonical(driver.async_attempt))
            shutil.rmtree(next((self.session / "destination/effects").iterdir()))
            self.assertFalse(driver.inspect()["complete"])
            with mock.patch(
                "multiprocessing.process.BaseProcess.start",
                side_effect=AssertionError("settled invocation redispatched"),
            ) as spawn:
                with self.assertRaises(ValueError):
                    driver.step()
                spawn.assert_not_called()
            self.assertEqual(driver.async_attempt, historical)
            self.assertEqual(list((self.session / "destination/effects").iterdir()), [])
        finally:
            driver.close()

    def test_only_freshly_confirmed_first_key_admits_distinct_second_invocation(self):
        self.task["goals"] = ["first", "second"]
        driver = self.start()
        self.admit(driver)
        try:
            original = json.loads(canonical(driver.policy))
            first_pid = driver._process.pid
            with mock.patch(
                "multiprocessing.process.BaseProcess.start",
                side_effect=AssertionError("premature second worker"),
            ):
                self.assertFalse(driver.step())
            self.assertEqual(driver.policy, original)
            self.finish_original(driver)
            self.assertFalse(driver.step())
            self.assertEqual(
                (driver.async_attempt["key"], driver.async_attempt["invocation"]),
                (1, self.task["id"] + ":1"),
            )
            self.assertNotEqual(driver._process.pid, first_pid)
            self.finish_original(driver)
            facts = driver.owner.audit()
            self.assertEqual(
                (facts["complete"], facts["effect_count"], facts["duplicate_effects"]),
                (True, 2, 0),
            )
        finally:
            driver.close()

    def test_changed_worker_packet_is_rejected_by_actual_spawned_reader(self):
        driver = self.start()
        self.admit(driver)
        context = multiprocessing.get_context("spawn")
        try:
            for case in ("pending", "hidden", "task", "deadline", "owner"):
                with self.subTest(case=case):
                    spec = json.loads(canonical(driver._spec))
                    if case == "pending":
                        spec["pending"]["invocation"] = "foreign:0"
                    elif case == "hidden":
                        spec["hidden"] = "00" * 96
                    elif case == "task":
                        spec["task"]["goals"][0] = "foreign payload"
                    elif case == "deadline":
                        spec["contract"]["deadline_ns"] += 1_000_000_000
                    else:
                        spec["owner"][""][1] += 1
                    receiver, command = context.Pipe(duplex=False)
                    notices, sender = context.Pipe(duplex=False)
                    worker = context.Process(
                        target=_worker, args=(spec, receiver, sender)
                    )
                    worker.start()
                    receiver.close()
                    sender.close()
                    try:
                        self.assertTrue(notices.poll(5))
                        self.assertEqual(notices.recv()["phase"], "UNKNOWN")
                        worker.join(timeout=5)
                        self.assertFalse(worker.is_alive())
                        self.assertEqual(
                            list((self.session / "destination/effects").iterdir()), []
                        )
                    finally:
                        command.close()
                        worker.join(timeout=5)
                        notices.close()
        finally:
            driver.close()

    def test_changed_source_in_fresh_interpreter_cannot_attach_original_worker(self):
        driver = self.start()
        self.admit(driver)
        try:
            source = self.root / "changed-source"
            source.mkdir()
            for path in Path(__file__).parent.glob("*.py"):
                shutil.copy2(path, source / path.name)
            path = source / "async_recurrent_lifecycle.py"
            path.write_bytes(path.read_bytes() + b"\n# source drift control\n")
            (self.root / "spec.json").write_bytes(canonical(driver._spec))
            script = """
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from async_recurrent_lifecycle import _original_owner
try:
    _original_owner(json.loads(Path(sys.argv[2]).read_text()),False)
except ValueError as error:
    assert 'binding drift' in str(error), str(error)
else:
    raise AssertionError('changed worker source accepted')
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(source),
                    str(self.root / "spec.json"),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list((self.session / "destination/effects").iterdir()), [])
        finally:
            driver.close()


if __name__ == "__main__":
    unittest.main()
