"""Actual child lifetimes and cancellation at the terminal-observation boundary."""

import contextlib
import ctypes
import errno
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import hepta_ci_exec as executor


class ObservationCancelled(BaseException):
    pass


@unittest.skipUnless(
    sys.platform == "linux" and hasattr(os, "WNOWAIT"),
    "Linux child-state and WNOWAIT observations",
)
class CommandOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "command.log"

    def test_cancellation_after_terminal_observation_keeps_signal_ownership(self):
        real_poll, real_waitid, real_killpg = (
            subprocess.Popen.poll,
            os.waitid,
            os.killpg,
        )
        cancelled = False
        signals = []

        def cancel_once():
            nonlocal cancelled
            if not cancelled:
                cancelled = True
                raise ObservationCancelled

        def observe_poll(process, *args, **kwargs):
            status = real_poll(process, *args, **kwargs)
            if status is not None:
                cancel_once()
            return status

        def observe_waitid(*args, **kwargs):
            status = real_waitid(*args, **kwargs)
            if status is not None and status.si_code in (
                os.CLD_EXITED,
                os.CLD_KILLED,
                os.CLD_DUMPED,
            ):
                cancel_once()
            return status

        def guarded_signal(group, signum):
            try:
                status = real_waitid(
                    os.P_PID, group, os.WEXITED | os.WNOHANG | os.WNOWAIT
                )
                owned = status is not None and status.si_pid == group
            except ChildProcessError:
                owned = False
            signals.append((signum, owned))
            # Never actually signal a numeric group after the old implementation
            # has lost its wait ownership; recording that attempt is sufficient.
            if owned:
                real_killpg(group, signum)

        with (
            patch.object(subprocess.Popen, "poll", observe_poll),
            patch.object(os, "waitid", observe_waitid),
            patch.object(os, "killpg", guarded_signal),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(ObservationCancelled),
        ):
            executor.execute_logged(
                [sys.executable, "-c", "print('terminal observation', flush=True)"],
                self.log,
                timeout_seconds=2,
            )
        self.assertTrue(cancelled)
        self.assertEqual(signals, [(signal.SIGKILL, True)])

    def test_successful_leader_cannot_leave_a_silent_group_descendant(self):
        ready, stop = self.root / "ready", self.root / "stop"
        descendant = (
            "import time\nfrom pathlib import Path\n"
            f"Path({str(ready)!r}).touch()\n"
            f"while not Path({str(stop)!r}).exists(): time.sleep(.01)\n"
        )
        leader = (
            "import subprocess,sys,time\nfrom pathlib import Path\n"
            f"child=subprocess.Popen([sys.executable,'-c',{descendant!r}],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            f"while not Path({str(ready)!r}).exists(): time.sleep(.01)\n"
            "print(child.pid,flush=True)\n"
        )
        descendant_pid = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                record = executor.execute_logged(
                    [sys.executable, "-c", leader], self.log, timeout_seconds=2
                )
            descendant_pid = int(self.log.read_text().strip())
            self.assertEqual(record["returncode"], 0)
            self.assertFalse(record["timed_out"])
            until = time.monotonic() + 0.5
            while self.live(descendant_pid) and time.monotonic() < until:
                time.sleep(0.01)
            self.assertFalse(
                self.live(descendant_pid),
                "silent descendant survived successful cleanup",
            )
        finally:
            # On the pre-fix source the controlled descendant exits by its own
            # private stop file, without signalling an unowned or recycled PID.
            stop.touch()
            if descendant_pid is not None:
                until = time.monotonic() + 1
                while self.live(descendant_pid) and time.monotonic() < until:
                    time.sleep(0.01)

    def test_denied_signal_retains_unresolved_cleanup_without_unbounded_wait(self):
        stop = self.root / "denied-signal-stop"
        code = (
            "import time\nfrom pathlib import Path\n"
            "print('live controlled child',flush=True)\n"
            f"while not Path({str(stop)!r}).exists(): time.sleep(.01)\n"
        )
        real_spawn = subprocess.Popen
        children, waits = [], []

        def spawn(*args, **kwargs):
            child = real_spawn(*args, **kwargs)
            children.append((child, child.wait))
            child.wait = unittest.mock.Mock(wraps=child.wait)
            waits.append(child.wait)
            return child

        # The pre-fix owner eventually returns only because this private test
        # child voluntarily exits. The repaired owner must refuse much earlier.
        release = threading.Timer(3, stop.touch)
        release.start()
        began = time.monotonic()
        try:
            with (
                patch.object(subprocess, "Popen", spawn),
                patch.object(
                    os,
                    "killpg",
                    side_effect=PermissionError(
                        errno.EPERM, "controlled signal refusal"
                    ),
                ) as signals,
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(
                    (OSError, ValueError, subprocess.SubprocessError)
                ) as failure,
            ):
                executor.execute_logged(
                    [sys.executable, "-c", code], self.log, timeout_seconds=0.1
                )
            self.assertLess(time.monotonic() - began, 2)
            self.assertIn("cleanup unresolved", str(failure.exception))
            self.assertIn("PermissionError", str(failure.exception))
            self.assertEqual(signals.call_count, 1)
            self.assertEqual(waits[0].call_count, 1)
            self.assertIsNone(children[0][0].returncode)
        finally:
            release.cancel()
            stop.touch()
            for _, original_wait in children:
                original_wait(timeout=2)
            release.join(timeout=1)

    @staticmethod
    def live(pid):
        try:
            return (
                Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                != "Z"
            )
        except FileNotFoundError:
            return False


@unittest.skipUnless(
    os.name == "posix", "The CI command owner is explicitly POSIX-only"
)
class CommandPlatformTests(unittest.TestCase):
    def test_missing_wait_primitive_or_other_sigchld_owner_dispatches_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "unused.log"
            with (
                patch.dict(os.__dict__),
                patch.object(executor.subprocess, "Popen") as spawn,
            ):
                os.__dict__.pop("WNOWAIT", None)
                with self.assertRaisesRegex(ValueError, "WNOWAIT"):
                    executor.execute_logged(["not-dispatched"], log)
                spawn.assert_not_called()
            with (
                patch.object(signal, "getsignal", return_value=signal.SIG_IGN),
                patch.object(executor.subprocess, "Popen") as spawn,
                self.assertRaisesRegex(ValueError, "SIGCHLD"),
            ):
                executor.execute_logged(["not-dispatched"], log)
            spawn.assert_not_called()
            self.assertFalse(log.exists())

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "WNOWAIT"), "POSIX wait ownership"
    )
    def test_darwin_permission_failure_requires_exact_exited_singleton(self):
        # Real child and WNOWAIT status, with only Darwin's libproc census API
        # controlled here. This does not claim execution on a macOS kernel.
        class Census:
            def __init__(self, kind):
                self.kind = kind

            def __call__(self, selector, group, members, capacity):
                if selector != 2 or capacity != 2 * ctypes.sizeof(ctypes.c_int):
                    raise AssertionError("unexpected census scope or capacity")
                members[0] = group + (1 if self.kind == "foreign" else 0)
                members[1] = group + 1
                if self.kind == "errno":
                    ctypes.set_errno(errno.EPERM)
                return {"empty": 0, "multiple": capacity}.get(
                    self.kind, ctypes.sizeof(ctypes.c_int)
                )

        with tempfile.TemporaryDirectory() as temporary:
            for kind in (
                "singleton",
                "empty",
                "multiple",
                "foreign",
                "errno",
                "unavailable",
            ):
                with self.subTest(kind=kind):
                    loader = (
                        {"side_effect": OSError("libproc unavailable")}
                        if kind == "unavailable"
                        else {
                            "return_value": SimpleNamespace(proc_listpids=Census(kind))
                        }
                    )
                    with (
                        patch.object(sys, "platform", "darwin"),
                        patch.object(ctypes, "CDLL", **loader) as library,
                        patch.object(
                            os,
                            "killpg",
                            side_effect=PermissionError("Darwin group EPERM"),
                        ),
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        if kind == "singleton":
                            record = executor.execute_logged(
                                [sys.executable, "-c", "print('exit')"],
                                Path(temporary) / kind,
                                timeout_seconds=2,
                            )
                            self.assertEqual(record["returncode"], 0)
                        else:
                            with self.assertRaises(PermissionError):
                                executor.execute_logged(
                                    [sys.executable, "-c", "print('exit')"],
                                    Path(temporary) / kind,
                                    timeout_seconds=2,
                                )
                        library.assert_called_once_with(
                            "/usr/lib/libproc.dylib", use_errno=True
                        )

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "WNOWAIT"), "POSIX wait ownership"
    )
    def test_live_darwin_leader_never_uses_the_zombie_permission_exception(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True
        )
        try:
            with (
                patch.object(sys, "platform", "darwin"),
                patch.object(ctypes, "CDLL") as library,
            ):
                self.assertFalse(executor._darwin_exited_leader_only(child))
                library.assert_not_called()
        finally:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


if __name__ == "__main__":
    unittest.main()
