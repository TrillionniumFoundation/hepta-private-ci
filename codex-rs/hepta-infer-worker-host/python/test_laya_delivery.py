"""Real child/final-delivery races, not product authority or resource attestation."""
import selectors
import subprocess
import threading
import unittest
from unittest.mock import patch

from laya_process import ProcessFailure
from laya_wait import observation_supported
import test_laya_process as fixtures


@unittest.skipUnless(observation_supported(), "requires owned child observation")
class DeliveryTests(unittest.TestCase):
    setUp = fixtures.ProcessTests.setUp
    command = fixtures.ProcessTests.command
    execute = fixtures.ProcessTests.execute

    def test_cancellation_during_reap_never_delivers_valid_reply(self):
        cancel = threading.Event()
        original = subprocess.Popen.wait
        def reap(child, **kwargs):
            result = original(child, **kwargs)
            cancel.set()
            return result
        with patch.object(subprocess.Popen, "wait", reap):
            with self.assertRaises(ProcessFailure) as caught:
                self.execute(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})", cancel=cancel)
        observed = caught.exception.observation
        self.assertTrue(observed["direct_child_reaped"])
        self.assertEqual(observed["returncode"], 0)
        self.assertEqual(observed["stdout_bytes"], len(self.reply))
        self.assertFalse(observed["eligible_reply"])
        self.assertFalse(observed["retry_allowed"])
        self.assertIsNone(observed["reply_sha256"])

    def test_selector_finalization_failure_still_reaps_owned_child(self):
        original = selectors.DefaultSelector.close
        def close(selector):
            original(selector)
            raise OSError("private finalizer detail")
        with patch.object(selectors.DefaultSelector, "close", close):
            with self.assertRaises(ProcessFailure) as caught:
                self.execute(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})")
        observed = caught.exception.observation
        self.assertTrue(observed["direct_child_reaped"])
        self.assertFalse(observed["eligible_reply"])
        self.assertNotIn("private", str(observed))
        self.assertIsNone(caught.exception.child)

    def test_finalizer_failure_plus_denied_cleanup_retains_exact_child(self):
        original = selectors.DefaultSelector.close
        def close(selector):
            original(selector)
            raise OSError("private finalizer detail")
        with patch.object(selectors.DefaultSelector, "close", close), \
             patch("laya_process.os.killpg", side_effect=PermissionError("injected")):
            with self.assertRaises(ProcessFailure) as caught:
                self.execute(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})")
        failure = caught.exception
        self.addCleanup(failure.reconcile_cleanup)
        self.assertIsNotNone(failure.child)
        self.assertFalse(failure.observation["direct_child_reaped"])
        observed = failure.reconcile_cleanup()
        self.assertTrue(observed["direct_child_reaped"])
        self.assertFalse(observed["eligible_reply"])
        self.assertFalse(observed["retry_allowed"])

    def test_finalizer_interrupt_after_safe_reap_preserves_interrupt(self):
        original = selectors.DefaultSelector.close
        def close(selector):
            original(selector)
            raise KeyboardInterrupt()
        with patch.object(selectors.DefaultSelector, "close", close):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(f"sys.stdin.buffer.read()\nsys.stdout.buffer.write({self.reply!r})")


if __name__ == "__main__":
    unittest.main()
