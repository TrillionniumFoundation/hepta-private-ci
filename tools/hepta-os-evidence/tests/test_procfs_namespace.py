"""Reject host procfs/local PID collisions before any state write or signal."""

import os
from pathlib import Path
import signal
import subprocess
import unittest
from unittest import mock

import trusted_executor


class ProcfsNamespaceTests(unittest.TestCase):
    def test_signal_entry_rejects_mismatched_namespace_without_pidfd_or_kill(self):
        ident = trusted_executor.ProcIdentity(os.getpid() + 1, os.getpid(), 1, "R", 7)
        with (
            mock.patch.object(
                trusted_executor,
                "_require_procfs_namespace",
                side_effect=trusted_executor.ExecutionError("namespace mismatch"),
            ),
            mock.patch.object(trusted_executor.os, "pidfd_open") as open_pidfd,
            mock.patch.object(
                trusted_executor.signal, "pidfd_send_signal"
            ) as send_pidfd,
            mock.patch.object(trusted_executor.os, "kill") as kill,
        ):
            self.assertFalse(trusted_executor._signal_identity(ident, signal.SIGKILL))
            open_pidfd.assert_not_called()
            send_pidfd.assert_not_called()
            kill.assert_not_called()

    def test_retire_timeout_fallback_never_signals_after_namespace_failure(self):
        proc = mock.Mock(pid=os.getpid() + 1)
        proc.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), 0]
        ident = trusted_executor.ProcIdentity(proc.pid, os.getpid(), 1, "R", 7)
        with (
            mock.patch.object(
                trusted_executor,
                "_require_procfs_namespace",
                side_effect=trusted_executor.ExecutionError("namespace mismatch"),
            ),
            mock.patch.object(
                trusted_executor,
                "_active_descendants",
                side_effect=trusted_executor.ExecutionError("namespace mismatch"),
            ),
            mock.patch.object(
                trusted_executor, "_read_proc_identity", return_value=ident
            ) as read_identity,
            mock.patch.object(trusted_executor.os, "pidfd_open") as open_pidfd,
            mock.patch.object(
                trusted_executor.signal, "pidfd_send_signal"
            ) as send_pidfd,
            mock.patch.object(trusted_executor.os, "kill") as kill,
            mock.patch.object(trusted_executor.time, "sleep"),
        ):
            self.assertEqual(
                trusted_executor.retire(proc, os.getpid(), set()), (True, False, False)
            )
            read_identity.assert_called_once_with(proc.pid)
            self.assertEqual(proc.wait.call_count, 2)
            open_pidfd.assert_not_called()
            send_pidfd.assert_not_called()
            kill.assert_not_called()

    def test_mismatched_procfs_rejects_before_policy_or_started_write(self):
        current = os.getpid()
        original = Path.read_bytes

        def wrong_namespace(path):
            if str(path) == "/proc/self/stat":
                return f"{current + 1} (fixture) R".encode()
            if str(path) == f"/proc/{current}/stat":
                return f"{current} (unrelated-host-process) R".encode()
            return original(path)

        with (
            mock.patch.object(Path, "read_bytes", wrong_namespace),
            mock.patch.object(trusted_executor, "read_policy") as policy,
            mock.patch.object(trusted_executor, "write_raw_once") as write,
            mock.patch.object(trusted_executor, "_signal_identity") as signal,
        ):
            with self.assertRaisesRegex(
                trusted_executor.ExecutionError, "procfs PID namespace mismatch"
            ):
                trusted_executor.execute("a" * 32, config=None)
            policy.assert_not_called()
            write.assert_not_called()
            signal.assert_not_called()

    def test_procfs_disappearing_rejects_before_descendant_enumeration(self):
        with (
            mock.patch.object(
                Path, "read_bytes", side_effect=FileNotFoundError("procfs gone")
            ),
            mock.patch.object(Path, "iterdir") as enumerate_processes,
        ):
            with self.assertRaisesRegex(
                trusted_executor.ExecutionError,
                "cannot establish matching procfs PID namespace",
            ):
                trusted_executor._proc_table()
            enumerate_processes.assert_not_called()
