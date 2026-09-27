"""Lost-child ownership is a terminal latch, not a transient wait error.

These exercise the real transport and direct child, injecting only the later
PID-reuse observation. They never create an external-effect or model claim.
"""
import errno
import os
import signal
import subprocess
import unittest

from laya_wait import observation_supported, observe_owned_exit
from unittest.mock import patch

from laya_binary import OwnerDeadline
from laya_process import ProcessFailure, _cleanup_owned_child
import test_laya_process as fixtures


@unittest.skipUnless(observation_supported(),
                     "non-reaping child observation is unsupported")
class OwnershipTests(unittest.TestCase):
    setUp = fixtures.ProcessTests.setUp
    command = fixtures.ProcessTests.command
    execute = fixtures.ProcessTests.execute

    def retained(self):
        # Denied signalling of a LIVE child is unresolved on both platforms.
        # An exited singleton is not a permission-denied fixture on Darwin.
        deadline = OwnerDeadline.start(fixtures.decode_request_deadline(self.wire), maximum_seconds=0.25)
        with patch("laya_process.os.killpg", side_effect=PermissionError(errno.EPERM, "private")):
            with self.assertRaises(ProcessFailure) as caught:
                self.execute("sys.stdin.buffer.read()\ntime.sleep(30)", deadline=deadline)
        failure = caught.exception
        self.assertIsNotNone(failure.child)
        self.assertIsNone(observe_owned_exit(failure.child.pid))
        self.addCleanup(failure.reconcile_cleanup)
        return failure

    def test_external_wait_without_popen_update_permanently_loses_identity(self):
        failure = self.retained()
        child = failure.child
        os.kill(child.pid, signal.SIGKILL)  # still the owned, unreaped live child
        os.waitpid(child.pid, 0)  # a prohibited external reaper; returncode stays None
        self.assertIsNone(child.returncode)
        first = failure.reconcile_cleanup()
        self.assertEqual(first["cleanup_error"], "ChildOwnershipLost")
        # A later waitid(P_PID, stale_pid) could name ANOTHER child with this PID.
        # Merely returning success must never renew a previously lost identity.
        with patch("laya_process.observe_owned_exit", return_value=None) as observe:
            with patch("laya_process.os.killpg") as signal_group:
                with patch.object(child, "wait", return_value=0) as reap:
                    second = failure.reconcile_cleanup()
        observe.assert_not_called()
        signal_group.assert_not_called()
        reap.assert_not_called()
        self.assertEqual(second["cleanup_error"], "ChildOwnershipLost")
        self.assertFalse(second["direct_child_reaped"])
        self.assertFalse(second["eligible_reply"])
        self.assertFalse(second["retry_allowed"])
        # Record the external result for Popen destructor only, never as owner success.
        child.returncode = -signal.SIGKILL

    def test_observation_projection_cannot_forge_cleanup_completion(self):
        failure = self.retained()
        projection = failure.observation
        projection.update(direct_child_reaped=True, cleanup_error=None,
                          eligible_reply=True, retry_allowed=True)
        result = failure.reconcile_cleanup()
        self.assertTrue(result["direct_child_reaped"])
        self.assertTrue(result["group_kill_sent"])
        self.assertFalse(result["eligible_reply"])
        self.assertFalse(result["retry_allowed"])
        self.assertIsNone(failure.child)

    def test_constructor_takes_an_owned_observation_snapshot(self):
        original = {"direct_child_reaped": False, "cleanup_error": "ChildOwnershipLost"}
        failure = ProcessFailure("fixture", original)
        original["cleanup_error"] = None
        self.assertEqual(failure.observation["cleanup_error"], "ChildOwnershipLost")
        projected = failure.reconcile_cleanup()
        projected["cleanup_error"] = None
        self.assertEqual(failure.observation["cleanup_error"], "ChildOwnershipLost")

    def test_cleanup_retains_bounded_stage_and_errno_not_exception_text(self):
        failure = self.retained()
        observed = failure.observation
        self.assertEqual(observed["cleanup_stage"], "signal_group")
        self.assertEqual(observed["cleanup_errno"], errno.EPERM)
        self.assertNotIn("private", str(observed))
        observed = failure.reconcile_cleanup()
        self.assertTrue(observed["direct_child_reaped"])
        self.assertIsNone(observed["cleanup_errno"])
        self.assertIsNone(observed["cleanup_stage"])

    def test_observation_failure_records_phase_and_does_not_signal_or_reap(self):
        failure = self.retained()
        with patch("laya_process.observe_owned_exit", side_effect=OSError(errno.EIO, "private")):
            with patch("laya_process.os.killpg") as signal_group:
                with patch.object(failure.child, "wait") as reap:
                    result = failure.reconcile_cleanup()
        signal_group.assert_not_called()
        reap.assert_not_called()
        self.assertEqual(result["cleanup_stage"], "observe_child")
        self.assertEqual(result["cleanup_errno"], errno.EIO)
        self.assertNotIn("private", str(result))
        self.assertFalse(result["direct_child_reaped"])

    def test_wait_timeout_records_phase_and_keeps_retained_child(self):
        failure = self.retained()
        with patch.object(failure.child, "wait", side_effect=subprocess.TimeoutExpired("private", 1)):
            result = failure.reconcile_cleanup()
        self.assertEqual(result["cleanup_stage"], "reap_child")
        self.assertIsNone(result["cleanup_errno"])
        self.assertNotIn("private", str(result))
        self.assertFalse(result["direct_child_reaped"])
        self.assertIsNotNone(failure.child)

    def test_lower_level_loss_latch_rejects_successful_later_observation(self):
        observation = {"direct_child_reaped": False, "cleanup_error": "ChildOwnershipLost"}
        with patch("laya_process.observe_owned_exit") as observe, patch("laya_process.os.killpg") as kill:
            _cleanup_owned_child(None, observation)
        observe.assert_not_called()
        kill.assert_not_called()
        self.assertEqual(observation["cleanup_error"], "ChildOwnershipLost")


if __name__ == "__main__":
    unittest.main()
