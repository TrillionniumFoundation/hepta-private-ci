"""Real process ownership regressions for the existing CI command owner.

The Linux process-state observations are not a sandbox or a physical cleanup
latency guarantee. Darwin census cases exercise its denial decision with an
actual unreaped child and supplied libproc responses, not an actual macOS host.
"""

import contextlib
import ctypes
import hashlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import hepta_ci_exec as executor


class CommandProcessOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "command.log"

    def execute(self, code, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            record = executor.execute_logged(
                [sys.executable, "-I", "-S", "-c", code],
                self.log,
                timeout_seconds=kwargs.pop("timeout_seconds", 3),
                **kwargs,
            )
        data = self.log.read_bytes()
        self.assertEqual(record["log_bytes"], len(data))
        self.assertEqual(record["log_sha256"], hashlib.sha256(data).hexdigest())
        return record

    def silent_descendant(self, exit_code):
        pid_file = self.root / "descendant.pid"
        code = f"""import os,time
from pathlib import Path
r,w=os.pipe()
if os.fork()==0:
    os.close(r)
    for fd in (0,1,2):
        try:os.close(fd)
        except OSError:pass
    Path({str(pid_file)!r}).write_text(str(os.getpid()))
    os.write(w,b'R');os.close(w)
    time.sleep(30)
    os._exit(0)
os.close(w)
assert os.read(r,1)==b'R'
os.close(r)
os._exit({exit_code})
"""
        try:
            record = self.execute(code)
            pid = int(pid_file.read_text())
            self.assertEqual(record["returncode"], exit_code)
            self.assertFalse(record["timed_out"])
            self.assertFalse(record["output_limit_exceeded"])
            for _ in range(100):
                try:
                    state = Path(f"/proc/{pid}/stat").read_text()
                except (FileNotFoundError, ProcessLookupError):
                    break
                if state.rsplit(")", 1)[1].split()[0] == "Z":
                    break
                time.sleep(0.01)
            else:
                self.fail("same-group descendant still runs after command return")
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    @unittest.skipUnless(sys.platform == "linux", "Linux process-state observation")
    def test_success_cleans_a_silent_same_group_descendant(self):
        self.silent_descendant(0)

    @unittest.skipUnless(sys.platform == "linux", "Linux process-state observation")
    def test_nonzero_cleans_a_silent_descendant_and_keeps_exit(self):
        self.silent_descendant(23)

    def test_group_signal_precedes_reaping_on_success_and_nonzero(self):
        killpg = os.killpg
        for exit_code in (0, 23):
            with self.subTest(exit_code=exit_code):
                self.log.unlink(missing_ok=True)
                observations = []

                def observe(pid, sig):
                    try:
                        status = os.waitid(
                            os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                        )
                    except ChildProcessError:
                        status = None
                    observations.append(status)
                    return killpg(pid, sig)

                with patch.object(executor.os, "killpg", side_effect=observe):
                    record = self.execute(f"raise SystemExit({exit_code})")
                self.assertEqual(record["returncode"], exit_code)
                self.assertEqual(len(observations), 1)
                self.assertIsNotNone(observations[0], "leader was not reserved")
                self.assertEqual(observations[0].si_status, exit_code)
                self.log.unlink()

    def test_unrelated_process_group_is_not_signalled(self):
        outsider = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            record = self.execute("print('owned command')")
            self.assertEqual(record["returncode"], 0)
            self.assertIsNone(outsider.poll())
        finally:
            outsider.kill()
            outsider.wait()

    def test_original_signal_exit_and_exact_output_are_retained(self):
        record = self.execute(
            "import os,signal; os.write(1,b'original output\\n'); "
            "os.kill(os.getpid(),signal.SIGTERM)"
        )
        self.assertEqual(record["returncode"], -signal.SIGTERM)
        self.assertEqual(self.log.read_bytes(), b"original output\n")
        self.assertFalse(record["timed_out"])

    def test_closed_stream_live_leader_keeps_original_timeout(self):
        record = self.execute(
            "import os,time; os.close(1); os.close(2); time.sleep(30)",
            timeout_seconds=0.75,
        )
        self.assertTrue(record["timed_out"])
        self.assertEqual(record["returncode"], -signal.SIGKILL)
        self.assertFalse(record["output_limit_exceeded"])

    def test_output_limit_remains_a_separate_failure(self):
        record = self.execute(
            "import os,time; os.write(1,b'x'*4096); time.sleep(30)",
            maximum_bytes=127,
        )
        self.assertEqual(self.log.read_bytes(), b"x" * 127)
        self.assertTrue(record["output_limit_exceeded"])
        self.assertFalse(record["timed_out"])
        self.assertEqual(record["returncode"], -signal.SIGKILL)

    def test_interrupted_nonreaping_observation_does_not_release_child(self):
        waitid = os.waitid
        interrupted = []

        def observe(*args):
            if not interrupted:
                interrupted.append(True)
                raise InterruptedError()
            return waitid(*args)

        with patch.object(executor.os, "waitid", side_effect=observe):
            record = self.execute("print('complete')")
        self.assertTrue(interrupted)
        self.assertEqual(record["returncode"], 0)
        self.assertFalse(record["timed_out"])

    def test_missing_nonreaping_platform_refuses_before_spawn(self):
        with (
            patch.object(executor, "os", SimpleNamespace(name="posix")),
            patch.object(executor.subprocess, "Popen") as popen,
        ):
            with self.assertRaises(ValueError):
                self.execute("raise SystemExit(0)")
        popen.assert_not_called()
        self.assertFalse(self.log.exists())

    def test_denied_cleanup_is_not_a_success_and_still_reaps(self):
        popen = subprocess.Popen
        children = []

        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        with (
            patch.object(executor.subprocess, "Popen", side_effect=spawn),
            patch.object(executor.os, "killpg", side_effect=PermissionError()),
            patch.object(executor, "_darwin_only_exited_leader", return_value=False),
        ):
            with self.assertRaises(PermissionError):
                self.execute("print('cannot waive cleanup')")
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].returncode, 0)
        with self.assertRaises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)
        self.assertTrue(children[0].stdout.closed)
        self.assertEqual(self.log.read_bytes(), b"cannot waive cleanup\n")


class DarwinOwnedExitDecisionTests(unittest.TestCase):
    def setUp(self):
        self.child = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", "raise SystemExit(7)"]
        )
        self.addCleanup(self.child.wait)
        deadline = time.monotonic() + 3
        while (
            os.waitid(os.P_PID, self.child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            is None
        ):
            if time.monotonic() >= deadline:
                self.child.kill()
                self.fail("fixture child did not exit")
            time.sleep(0.005)

    def test_only_exact_complete_owned_census_can_disambiguate_eperm(self):
        width = ctypes.sizeof(ctypes.c_int)
        for count, entries, error, accepted in (
            (width, [self.child.pid], 0, True),
            (0, [], 0, False),
            (-1, [], 0, False),
            (width, [self.child.pid + 1], 0, False),
            (2 * width, [self.child.pid, self.child.pid + 1], 0, False),
            (width, [self.child.pid], 1, False),
            (3 * width, [self.child.pid, self.child.pid + 1], 0, False),
        ):
            with self.subTest(count=count, entries=entries, error=error):

                def census(kind, pid, buffer, capacity):
                    self.assertEqual(kind, 2)
                    self.assertEqual(pid, self.child.pid)
                    self.assertEqual(capacity, 2 * width)
                    for index, value in enumerate(entries):
                        buffer[index] = value
                    ctypes.set_errno(error)
                    return count

                library = SimpleNamespace(proc_listpids=Mock(side_effect=census))
                with (
                    patch.object(executor.sys, "platform", "darwin"),
                    patch.object(ctypes, "CDLL", return_value=library),
                ):
                    self.assertEqual(
                        executor._darwin_only_exited_leader(self.child), accepted
                    )
                self.assertIsNone(self.child.returncode)

    def test_reaped_or_non_darwin_leader_cannot_waive_denial(self):
        with patch.object(executor.sys, "platform", "linux"):
            self.assertFalse(executor._darwin_only_exited_leader(self.child))
        self.child.wait()
        with patch.object(executor.sys, "platform", "darwin"):
            self.assertFalse(executor._darwin_only_exited_leader(self.child))


if __name__ == "__main__":
    unittest.main()
