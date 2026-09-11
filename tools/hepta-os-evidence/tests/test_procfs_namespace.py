"""Reject host procfs/local PID collisions before any state write or signal."""

import os
from pathlib import Path
import unittest
from unittest import mock

import trusted_executor


class ProcfsNamespaceTests(unittest.TestCase):
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
