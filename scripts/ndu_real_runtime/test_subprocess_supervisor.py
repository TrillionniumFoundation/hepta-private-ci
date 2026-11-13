"""Real POSIX children and retained raw logs; no model fit or owner authority."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time
import unittest

from .subprocess_supervisor import STREAM_LIMIT, run_logged


@unittest.skipUnless(
    os.name == "posix" and hasattr(os, "WNOWAIT"), "POSIX waitid required"
)
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sequence = 0

    def execute(self, source, *, timeout=5):
        self.sequence += 1
        directory = self.root / str(self.sequence)
        directory.mkdir()
        with (
            (directory / "stdout.log").open("xb", buffering=0) as stdout,
            (directory / "stderr.log").open("xb", buffering=0) as stderr,
        ):
            result = run_logged(
                [sys.executable, "-B", "-c", source],
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                env=dict(os.environ),
            )
        (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        (directory / "child.py").write_text(source)
        if qa_root := os.environ.get("HEPTA_SUPERVISOR_QA_ROOT"):
            shutil.copytree(
                directory, Path(qa_root) / f"{self._testMethodName}-{self.sequence}"
            )
        return result, directory

    def test_binary_stdout_stderr_and_nonzero_exit_keep_original_status(self):
        for code in (0, 7):
            with self.subTest(exit_code=code):
                result, directory = self.execute(
                    f"import os; os.write(1, b'out\\x00\\xff'); os.write(2, b'err\\xfe'); raise SystemExit({code})"
                )
                self.assertEqual(result["returncode"], code)
                self.assertIsNone(result["error"])
                self.assertTrue(result["cleanup_complete"])
                self.assertEqual(
                    (directory / "stdout.log").read_bytes(), b"out\x00\xff"
                )
                self.assertEqual((directory / "stderr.log").read_bytes(), b"err\xfe")

    def test_each_stream_limit_terminates_group_and_retains_bounded_prefix(self):
        for descriptor, name in ((1, "stdout"), (2, "stderr")):
            with self.subTest(stream=name):
                result, directory = self.execute(
                    f"import os,time; os.write({descriptor}, b'x' * {STREAM_LIMIT + 1024}); time.sleep(30)"
                )
                self.assertEqual(result["error"]["type"], "OutputLimitExceeded")
                self.assertEqual(result["returncode"], -signal.SIGKILL)
                self.assertTrue(result["cleanup_complete"])
                self.assertEqual(
                    (directory / (name + ".log")).stat().st_size, STREAM_LIMIT
                )
                self.assertTrue(result["streams"][name]["truncated"])
                self.assertGreater(
                    result["streams"][name]["observed_bytes"], STREAM_LIMIT
                )

    def test_exact_output_limit_is_accepted(self):
        result, directory = self.execute(
            f"import os; os.write(1, b'x' * {STREAM_LIMIT})"
        )
        self.assertEqual(result["returncode"], 0)
        self.assertIsNone(result["error"])
        self.assertEqual((directory / "stdout.log").stat().st_size, STREAM_LIMIT)
        self.assertFalse(result["streams"]["stdout"]["truncated"])

    def test_timeout_preserves_partial_output_and_reaps_original_child(self):
        result, directory = self.execute(
            "import os,time; os.write(1,b'before timeout'); os.write(2,b'error prefix'); time.sleep(30)",
            timeout=2,
        )
        self.assertEqual(result["error"]["type"], "TimeoutExpired")
        self.assertEqual(result["returncode"], -signal.SIGKILL)
        self.assertTrue(result["cleanup_complete"])
        self.assertEqual((directory / "stdout.log").read_bytes(), b"before timeout")
        self.assertEqual((directory / "stderr.log").read_bytes(), b"error prefix")
        self.assertLess(result["wall_seconds"], 2)

    def test_closed_pipes_do_not_hide_a_live_child(self):
        result, _ = self.execute(
            "import os,time; os.close(1); os.close(2); time.sleep(30)", timeout=2
        )
        self.assertEqual(result["error"]["type"], "TimeoutExpired")
        self.assertEqual(result["returncode"], -signal.SIGKILL)
        self.assertTrue(result["cleanup_complete"])

    @unittest.skipUnless(
        Path("/dev/full").exists(), "Linux ENOSPC fault device required"
    )
    def test_log_io_failure_during_cleanup_still_reaps_child(self):
        with (
            open("/dev/full", "wb", buffering=0) as stdout,
            (self.root / "stderr.log").open("xb", buffering=0) as stderr,
        ):
            result = run_logged(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import os,time; os.write(1,b'x' * 1048576); time.sleep(30)",
                ],
                stdout=stdout,
                stderr=stderr,
                timeout=5,
                env=dict(os.environ),
            )
        self.assertEqual(result["returncode"], -signal.SIGKILL)
        self.assertTrue(result["child_reaped"])
        self.assertEqual(result["error"]["type"], "OSError")
        self.assertTrue(result["cleanup_errors"])
        self.assertFalse(result["cleanup_complete"])
        if qa_root := os.environ.get("HEPTA_SUPERVISOR_QA_ROOT"):
            Path(qa_root).mkdir(parents=True, exist_ok=True)
            Path(qa_root, self._testMethodName + ".json").write_text(
                json.dumps(result, indent=2) + "\n"
            )

    def test_exited_leader_with_inherited_pipes_keeps_its_real_zero_exit(self):
        result, directory = self.execute(
            "import subprocess,sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print(child.pid, flush=True)\n"
        )
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["error"]["type"], "OutputDrainExpired")
        self.assertTrue(result["cleanup_complete"])
        self.assertLess(result["wall_seconds"], 2)
        pid = int((directory / "stdout.log").read_text())
        if sys.platform.startswith("linux"):
            status = Path(f"/proc/{pid}/stat")
            deadline = time.monotonic() + 1
            while True:
                try:
                    state = status.read_text().rsplit(")", 1)[1].split()[0]
                except FileNotFoundError:
                    break
                # File close may precede exit_notify; allow that bounded race.
                if state == "Z":
                    break
                self.assertLess(time.monotonic(), deadline, "Descendant remained live")
                time.sleep(0.01)

    def test_output_is_visible_on_disk_before_child_completes(self):
        marker = self.root / "finish"
        source = (
            "import time\nfrom pathlib import Path\nprint('started', flush=True)\n"
            f"while not Path({str(marker)!r}).exists(): time.sleep(0.01)\n"
            "print('finished', flush=True)\n"
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.execute, source)
            try:
                deadline = time.monotonic() + 2
                output = self.root / "1/stdout.log"
                while time.monotonic() < deadline:
                    if output.exists() and output.read_bytes() == b"started\n":
                        break
                    time.sleep(0.01)
                self.assertEqual(output.read_bytes(), b"started\n")
                self.assertFalse(future.done())
            finally:
                marker.touch()
            result, directory = future.result(timeout=5)
        self.assertEqual(result["returncode"], 0)
        self.assertIsNone(result["error"])
        self.assertEqual(
            (directory / "stdout.log").read_bytes(), b"started\nfinished\n"
        )


if __name__ == "__main__":
    unittest.main()
