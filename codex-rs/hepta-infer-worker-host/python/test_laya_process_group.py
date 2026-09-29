"""Real child identity plus deterministic Darwin ABI/failure injection.

Linux runs do not certify Darwin execution; the existing macOS source/merge
workflow exercises the actual libproc branch with the full transport suite.
"""
import ctypes
import errno
import os
import signal
import subprocess
import sys
import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch

import laya_process_group as group


class GroupTests(unittest.TestCase):
    def child(self, running=False):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)" if running else "pass"],
                                 start_new_session=True)
        def clean():
            if child.returncode is None:
                # Test owner only: kill the owned direct child, then reap. All
                # fixtures are leaves; there is no group signal after reaping.
                child.kill()
                child.wait(timeout=3)
        self.addCleanup(clean)
        observed = group.observe_owned_exit(child.pid)
        end = time.monotonic() + 3
        while not running and observed is None and time.monotonic() < end:
            time.sleep(0.005)
            observed = group.observe_owned_exit(child.pid)
        if not running:
            self.assertIsNotNone(observed, "fixture child did not exit")
        return child, observed

    def denied(self, child, observed, members=None):
        with patch.object(group.sys, "platform", "darwin"), \
             patch.object(group.os, "killpg", side_effect=PermissionError(errno.EPERM, "private diagnostic")), \
             patch.object(group, "_darwin_group_members", return_value=members or (child.pid,)):
            return group.signal_owned_group(child, observed)

    def test_successful_signal_preserves_unreaped_live_identity(self):
        child, observed = self.child(True)
        self.assertEqual(group.signal_owned_group(child, observed), group.SIGNALLED)
        self.assertIsNone(child.returncode)
        self.assertEqual(child.wait(timeout=3), -signal.SIGKILL)

    def test_owned_exited_singleton_allows_reap_without_claiming_signal(self):
        child, observed = self.child()
        with patch.object(child, "wait", wraps=child.wait) as wait:
            self.assertEqual(self.denied(child, observed), group.EXITED_LEADER_ONLY)
            wait.assert_not_called()
        self.assertIsNone(child.returncode)
        self.assertEqual(child.wait(timeout=3), 0)

    def test_live_child_eperm_never_queries_or_reaps(self):
        child, observed = self.child(True)
        with patch.object(group.sys, "platform", "darwin"), \
             patch.object(group.os, "killpg", side_effect=PermissionError(errno.EPERM, "denied")), \
             patch.object(group, "_darwin_group_members") as query:
            with self.assertRaises(PermissionError):
                group.signal_owned_group(child, observed)
            query.assert_not_called()
        self.assertIsNone(child.returncode)

    def test_other_member_never_permits_reap(self):
        child, observed = self.child()
        with self.assertRaises(PermissionError):
            self.denied(child, observed, (child.pid, child.pid + 1))
        self.assertIsNone(child.returncode)

    def test_wrong_singleton_never_permits_reap(self):
        child, observed = self.child()
        with self.assertRaises(PermissionError):
            self.denied(child, observed, (child.pid + 1,))
        self.assertIsNone(child.returncode)

    def test_non_darwin_does_not_reinterpret_eperm(self):
        child, observed = self.child()
        with patch.object(group.sys, "platform", "linux"), \
             patch.object(group.os, "killpg", side_effect=PermissionError(errno.EPERM, "denied")), \
             patch.object(group, "_darwin_group_members") as query:
            with self.assertRaises(PermissionError):
                group.signal_owned_group(child, observed)
            query.assert_not_called()

    def test_different_permission_errno_is_not_empty_group(self):
        child, observed = self.child()
        with patch.object(group.sys, "platform", "darwin"), \
             patch.object(group.os, "killpg", side_effect=PermissionError(errno.EACCES, "denied")), \
             patch.object(group, "_darwin_group_members") as query:
            with self.assertRaises(PermissionError):
                group.signal_owned_group(child, observed)
            query.assert_not_called()

    def test_incomplete_observation_keeps_owned_child(self):
        child, observed = self.child()
        with patch.object(group.sys, "platform", "darwin"), \
             patch.object(group.os, "killpg", side_effect=PermissionError(errno.EPERM, "denied")), \
             patch.object(group, "_darwin_group_members", side_effect=OSError(errno.EAGAIN, "incomplete")):
            with self.assertRaises(OSError):
                group.signal_owned_group(child, observed)
        self.assertIsNone(child.returncode)

    def test_exit_between_initial_observation_and_signal_is_rechecked(self):
        child, observed = self.child()
        # A real unreaped zombie, with the caller's earlier live observation.
        self.assertIsNotNone(observed)
        self.assertEqual(self.denied(child, None), group.EXITED_LEADER_ONLY)
        self.assertIsNone(child.returncode)
        self.assertEqual(child.wait(timeout=3), 0)

    def test_exit_identity_change_after_group_query_is_not_reaped(self):
        child, observed = self.child()
        other = SimpleNamespace(si_pid=child.pid, si_signo=signal.SIGCHLD,
                                si_code=1, si_status=9)
        with patch.object(group, "observe_owned_exit", side_effect=[observed, other]):
            with self.assertRaises(ChildProcessError):
                self.denied(child, observed)
        self.assertIsNone(child.returncode)

    def test_external_reap_never_signals(self):
        child, observed = self.child()
        child.wait(timeout=3)
        with patch.object(group.os, "killpg") as kill:
            with self.assertRaises(ChildProcessError):
                group.signal_owned_group(child, observed)
            kill.assert_not_called()

    def test_echild_after_group_snapshot_is_ownership_loss(self):
        child, observed = self.child()
        with patch.object(group, "observe_owned_exit", side_effect=ChildProcessError()):
            with self.assertRaises(ChildProcessError):
                self.denied(child, observed)

    def test_changed_exit_status_is_ownership_loss(self):
        child, observed = self.child()
        other = SimpleNamespace(si_pid=child.pid, si_signo=signal.SIGCHLD,
                                si_code=1, si_status=7)
        with patch.object(group, "observe_owned_exit", return_value=other):
            with self.assertRaises(ChildProcessError):
                self.denied(child, observed)

    def test_actual_darwin_zombie_or_posix_signal(self):
        child, observed = self.child()
        result = group.signal_owned_group(child, observed)
        self.assertIn(result, (group.SIGNALLED, group.ABSENT, group.EXITED_LEADER_ONLY))
        self.assertIsNone(child.returncode)
        self.assertEqual(child.wait(timeout=3), 0)


class DarwinAbiTests(unittest.TestCase):
    def invoke(self, count, pids, error_number=0):
        class Function:
            def __call__(self, pid, buffer, size):
                self.pid = pid
                self.size = size
                for index, value in enumerate(pids):
                    buffer[index] = value
                ctypes.set_errno(error_number)
                return count
        function = Function()
        with patch.object(group.ctypes, "CDLL", return_value=SimpleNamespace(proc_listpgrppids=function)) as load:
            result = group._darwin_group_members(42)
        load.assert_called_once_with("/usr/lib/libproc.dylib", use_errno=True)
        self.assertEqual(function.size, 2 * ctypes.sizeof(ctypes.c_int))
        self.assertEqual(function.pid, 42)
        return result

    def test_count_not_bytes_and_exact_singleton(self):
        self.assertEqual(self.invoke(1, [42]), (42,))

    def test_zero_full_negative_or_malformed_counts_reject(self):
        for count, values in ((0, []), (-1, []), (2, [42, 43]), (8, [42, 43]),
                              (1, [0]), (1, [-1]), (1, [42, 43])):
            with self.subTest(count=count, values=values), self.assertRaises(OSError):
                self.invoke(count, values)

    def test_hidden_api_failure_never_becomes_absence(self):
        with self.assertRaises(OSError) as caught:
            self.invoke(0, [], errno.EPERM)
        self.assertEqual(caught.exception.errno, errno.EPERM)

    def test_error_even_with_plausible_result_rejects(self):
        with self.assertRaises(OSError):
            self.invoke(1, [42], errno.EIO)


if __name__ == "__main__":
    unittest.main()
