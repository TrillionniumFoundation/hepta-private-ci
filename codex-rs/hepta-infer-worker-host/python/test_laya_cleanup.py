"""Actual child ownership under injected signal/reap failures; no model claim."""
import os
import signal
import subprocess
import threading
import time
import unittest

from laya_wait import observation_supported, observe_owned_exit
from unittest.mock import patch

from laya_process import ProcessFailure
import test_laya_process as fixtures


@unittest.skipUnless(observation_supported(),
                     "non-reaping child observation is unsupported")
class CleanupTests(unittest.TestCase):
    # Share fixture methods, not TestCase inheritance (which duplicates cases).
    setUp = fixtures.ProcessTests.setUp
    command = fixtures.ProcessTests.command
    execute = fixtures.ProcessTests.execute

    def retained(self, code, cancel=None):
        with patch("laya_process.os.killpg", side_effect=PermissionError("injected")):
            with patch.object(subprocess.Popen, "wait") as wait:
                with self.assertRaises(ProcessFailure) as caught:
                    self.execute(code, cancel=cancel)
                wait.assert_not_called()
        failure = caught.exception
        self.assertIsNotNone(failure.child)
        self.assertIsNone(failure.child.returncode)
        self.assertFalse(failure.observation["direct_child_reaped"])
        self.assertFalse(failure.observation["retry_allowed"])
        self.assertFalse(failure.observation["eligible_reply"])
        self.addCleanup(failure.reconcile_cleanup)
        return failure

    def test_failed_group_signal_retains_exited_leader_then_reconciles_once(self):
        failure = self.retained(
            f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})")
        child = failure.child
        # The exited child has not been reaped; its PID still reserves identity.
        self.assertIsNotNone(observe_owned_exit(child.pid))
        observed = failure.reconcile_cleanup()
        self.assertTrue(observed["direct_child_reaped"])
        self.assertTrue(observed["direct_child_exit_observed"])
        self.assertIsNone(failure.child)
        self.assertFalse(observed["eligible_reply"])
        self.assertFalse(observed["retry_allowed"])
        self.assertIsNone(observed["task_success"])
        with patch("laya_process.os.killpg") as signal_group:
            self.assertEqual(failure.reconcile_cleanup(), observed)
        signal_group.assert_not_called()

    def test_cancellation_and_failed_signal_retain_live_child(self):
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        try:
            failure = self.retained("sys.stdin.buffer.read()\ntime.sleep(5)", cancel)
        finally:
            timer.join()
        result = failure.reconcile_cleanup()
        self.assertEqual(result["returncode"], -signal.SIGKILL)
        self.assertFalse(result["descendant_exit_verified"])
        self.assertIsNone(result["observed_memory_bytes"])

    def test_second_failed_signal_still_does_not_reap(self):
        failure = self.retained("sys.stdin.buffer.read()")
        with patch("laya_process.os.killpg", side_effect=PermissionError("again")):
            with patch.object(subprocess.Popen, "wait") as wait:
                observed = failure.reconcile_cleanup()
        wait.assert_not_called()
        self.assertFalse(observed["direct_child_reaped"])
        self.assertEqual(observed["cleanup_error"], "PermissionError")
        self.assertIsNotNone(failure.child)
        failure.reconcile_cleanup()

    def test_lost_child_ownership_never_signals_a_recycled_group(self):
        failure = self.retained("sys.stdin.buffer.read()")
        # Simulate a prohibited external reaper. Do not actually reuse the PID.
        failure.child.wait(timeout=2)
        with patch("laya_process.os.killpg") as signal_group:
            observed = failure.reconcile_cleanup()
        signal_group.assert_not_called()
        self.assertEqual(observed["cleanup_error"], "ChildOwnershipLost")
        self.assertFalse(observed["direct_child_reaped"])
        self.assertFalse(observed["retry_allowed"])

    def test_wait_timeout_retains_identity_after_signal_and_can_reconcile(self):
        # Keep the leader live until cancellation so this is genuinely a signal
        # test on Darwin too, not an assertion that a zombie received SIGKILL.
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        try:
            with patch.object(subprocess.Popen, "wait", side_effect=subprocess.TimeoutExpired("fixture", 1)):
                with self.assertRaises(ProcessFailure) as caught:
                    self.execute("sys.stdin.buffer.read()\ntime.sleep(5)", cancel=cancel)
        finally:
            timer.join()
        failure = caught.exception
        self.addCleanup(failure.reconcile_cleanup)
        self.assertTrue(failure.observation["group_kill_sent"])
        self.assertIsNotNone(failure.child)
        # SIGKILL delivery and waitability are distinct kernel events. The
        # injected wait timeout may return before Darwin publishes the exited
        # singleton. Reconcile through the real owner within a fixed bound;
        # never weaken EPERM, externally reap, or rerun the model request.
        limit = time.monotonic() + 3
        observed = failure.reconcile_cleanup()
        while not observed["direct_child_reaped"] and time.monotonic() < limit:
            self.assertNotEqual(observed["cleanup_error"], "ChildOwnershipLost", observed)
            self.assertFalse(observed["eligible_reply"], observed)
            self.assertFalse(observed["retry_allowed"], observed)
            time.sleep(0.005)
            observed = failure.reconcile_cleanup()
        self.assertTrue(observed["direct_child_reaped"], observed)
        self.assertIsNone(failure.child)
        self.assertFalse(observed["eligible_reply"])
        self.assertFalse(observed["retry_allowed"])

    def test_interruption_with_failed_cleanup_retains_child_on_typed_failure(self):
        # Inject interrupt only in the exchange; the cleanup observation uses
        # the real waitid. The typed exception retains the original cause.
        import laya_process
        original = laya_process.observe_owned_exit
        calls = [0]
        def interrupt_once(*args):
            calls[0] += 1
            if calls[0] == 1:
                raise KeyboardInterrupt()
            return original(*args)
        with patch("laya_process.observe_owned_exit", side_effect=interrupt_once):
            failure = self.retained("sys.stdin.buffer.read()\ntime.sleep(5)")
        self.assertIsInstance(failure.__cause__, KeyboardInterrupt)
        self.assertTrue(failure.reconcile_cleanup()["direct_child_reaped"])

    def test_interruption_during_cleanup_retains_child(self):
        with patch("laya_process.os.killpg", side_effect=KeyboardInterrupt()):
            with self.assertRaises(ProcessFailure) as caught:
                self.execute("sys.stdin.buffer.read()")
        failure = caught.exception
        self.addCleanup(failure.reconcile_cleanup)
        self.assertIsNotNone(failure.child)
        self.assertIsInstance(failure.__cause__, KeyboardInterrupt)
        self.assertTrue(failure.reconcile_cleanup()["direct_child_reaped"])


if __name__ == "__main__":
    unittest.main()
