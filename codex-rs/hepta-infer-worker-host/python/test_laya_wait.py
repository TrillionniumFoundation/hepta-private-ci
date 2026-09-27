"""Exercise native ownership and the Darwin fallback without hiding missing APIs."""
import ctypes
import errno
import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import laya_wait as waiter


class DarwinWaitTests(unittest.TestCase):
    def invoke(self, *, fields=None, result=0, error=0):
        test = self
        class Function:
            calls = 0
            def __call__(self, selector, pid, pointer, options):
                self.calls += 1
                test.assertEqual((selector, pid, options), (1, 42, 0x25))
                target = ctypes.cast(pointer, ctypes.POINTER(waiter._DarwinSiginfo)).contents
                test.assertEqual(bytes(target), bytes(ctypes.sizeof(target)))
                for name, value in (fields or {}).items():
                    setattr(target, name, value)
                ctypes.set_errno(error)
                return result
        function = Function()
        with patch.object(waiter.sys, "platform", "darwin"), \
             patch.object(waiter.os, "waitid", None, create=True), \
             patch.object(waiter.ctypes, "CDLL", return_value=SimpleNamespace(waitid=function)) as load:
            try:
                return waiter.observe_owned_exit(42)
            finally:
                load.assert_called_once_with("/usr/lib/libSystem.B.dylib", use_errno=True)
                self.assertEqual(function.calls, 1, "observation must not retry")

    def test_missing_python_api_uses_complete_zero_initialized_abi(self):
        self.assertIsNone(self.invoke())
        value = self.invoke(fields={"si_pid": 42, "si_signo": signal.SIGCHLD,
                                    "si_code": 1, "si_status": 7})
        self.assertEqual(value, waiter.ExitObservation(42, signal.SIGCHLD, 1, 7))

    def test_killed_and_dumped_status_is_preserved(self):
        for code in (2, 3):
            value = self.invoke(fields={"si_pid": 42, "si_signo": signal.SIGCHLD,
                                        "si_code": code, "si_status": signal.SIGKILL})
            self.assertEqual(value.si_status, signal.SIGKILL)
            self.assertEqual(value.si_code, code)

    def test_echild_preserves_permanent_ownership_loss_class(self):
        with self.assertRaises(ChildProcessError) as caught:
            self.invoke(result=-1, error=errno.ECHILD)
        self.assertEqual(caught.exception.errno, errno.ECHILD)

    def test_interrupt_and_denial_propagate_without_retry(self):
        for error in (errno.EINTR, errno.EPERM, errno.EIO):
            with self.subTest(error=error), self.assertRaises(OSError) as caught:
                self.invoke(result=-1, error=error)
            self.assertEqual(caught.exception.errno, error)

    def test_error_with_plausible_result_does_not_publish_observation(self):
        with self.assertRaises(OSError):
            self.invoke(fields={"si_pid": 42, "si_signo": signal.SIGCHLD,
                                "si_code": 1, "si_status": 0}, error=errno.EIO)

    def test_missing_errno_on_failure_is_still_failure(self):
        with self.assertRaises(OSError) as caught:
            self.invoke(result=-1)
        self.assertEqual(caught.exception.errno, errno.EIO)

    def test_wrong_identity_signal_or_nonterminal_code_rejects(self):
        for field, value in (("si_pid", 43), ("si_signo", signal.SIGTERM),
                             ("si_code", 0), ("si_code", 4), ("si_code", 5), ("si_code", 6)):
            fields = {"si_pid": 42, "si_signo": signal.SIGCHLD, "si_code": 1, "si_status": 0}
            fields[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ChildProcessError):
                self.invoke(fields=fields)

    def test_invalid_caller_identity_never_enters_native_api(self):
        with patch.object(waiter.os, "waitid", create=True) as native, \
             patch.object(waiter.ctypes, "CDLL") as load:
            for pid in (True, False, 0, 1, -1, 2**31, 42.0, "42"):
                with self.subTest(pid=pid), self.assertRaises(ValueError):
                    waiter.observe_owned_exit(pid)
            native.assert_not_called()
            load.assert_not_called()

    def test_unsupported_runtime_does_not_load_abi(self):
        with patch.object(waiter.os, "waitid", None, create=True), \
             patch.object(waiter.sys, "platform", "unsupported"), \
             patch.object(waiter.ctypes, "CDLL") as load:
            self.assertFalse(waiter.observation_supported())
            with self.assertRaises(OSError) as caught:
                waiter.observe_owned_exit(42)
            self.assertEqual(caught.exception.errno, errno.ENOTSUP)
            load.assert_not_called()

    def test_unknown_layout_rejects_before_native_pointer_write(self):
        with patch.object(waiter.os, "waitid", None, create=True), \
             patch.object(waiter.sys, "platform", "darwin"), \
             patch.object(waiter.ctypes, "sizeof", return_value=4), \
             patch.object(waiter.ctypes, "CDLL") as load:
            self.assertFalse(waiter.observation_supported())
            with self.assertRaises(OSError):
                waiter.observe_owned_exit(42)
            load.assert_not_called()


@unittest.skipUnless(waiter.observation_supported(), "requires supported child observation")
class NativeWaitTests(unittest.TestCase):
    def child(self, program):
        child = subprocess.Popen([sys.executable, "-c", program], start_new_session=True)
        def clean():
            if child.returncode is None:
                child.kill()
                child.wait(timeout=3)
        self.addCleanup(clean)
        return child

    def exited(self, child):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            observed = waiter.observe_owned_exit(child.pid)
            if observed is not None:
                return observed
            time.sleep(0.005)
        self.fail("fixture child did not exit")

    def test_repeated_real_exit_observations_do_not_reap(self):
        child = self.child("raise SystemExit(7)")
        first = self.exited(child)
        self.assertEqual(waiter.observe_owned_exit(child.pid), first)
        self.assertIsNone(child.returncode)
        self.assertEqual(first.si_status, 7)
        self.assertEqual(child.wait(timeout=3), 7)
        with self.assertRaises(ChildProcessError):
            waiter.observe_owned_exit(child.pid)

    def test_live_then_real_kill_remains_owned_until_reap(self):
        child = self.child("import time; time.sleep(30)")
        self.assertIsNone(waiter.observe_owned_exit(child.pid))
        child.kill()
        first = self.exited(child)
        self.assertEqual(waiter.observe_owned_exit(child.pid), first)
        self.assertIsNone(child.returncode)
        self.assertEqual(first.si_status, signal.SIGKILL)
        self.assertEqual(child.wait(timeout=3), -signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
