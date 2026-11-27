"""Actual subprocess lifecycle checks; no PERC task-efficacy claim."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import perc1_process_meter as meter_module
from perc1_process_meter import run


@unittest.skipUnless(sys.platform == "linux", "Linux process-envelope tests")
class ProcessMeterTests(unittest.TestCase):
    def test_cpu_descendants_streams_and_fresh_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "run"
            code = (
                "import subprocess,sys; subprocess.run([sys.executable,'-c',"
                "'sum(i*i for i in range(1000000))'],check=True); "
                "sys.stdout.buffer.write(b'x'*1200000);sys.stderr.write('retained error')"
            )
            result = run([sys.executable, "-c", code], output)
            self.assertEqual(
                (result["outcome"], result["returncode"], result["measurement_valid"]),
                ("succeeded", 0, True),
            )
            self.assertGreater(result["waited_cpu_ns"], 10_000_000)
            self.assertGreater(result["largest_waited_process_rss_bytes"], 0)
            self.assertEqual(
                result["streams"]["stdout"],
                {
                    "path": "stdout.bin",
                    "bytes": 1200000,
                    "sha256": hashlib.sha256(b"x" * 1200000).hexdigest(),
                },
            )
            original = (output / "receipt.json").read_bytes()
            with self.assertRaises(FileExistsError):
                run([sys.executable, "-c", "raise SystemExit(9)"], output)
            self.assertEqual((output / "receipt.json").read_bytes(), original)

    def test_nonzero_and_launch_failure_retain_cost_and_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run(
                [sys.executable, "-c", "import sys;print('failure');sys.exit(7)"],
                Path(folder) / "failed",
            )
            self.assertEqual((result["outcome"], result["returncode"]), ("failed", 7))
            self.assertGreater(result["command_wall_ns"], 0)
            self.assertEqual(
                (Path(folder) / "failed/stdout.bin").read_bytes(), b"failure\n"
            )
            missing = run(
                [str(Path(folder) / "absent-program")], Path(folder) / "missing"
            )
            self.assertEqual(missing["outcome"], "launch_failed")
            self.assertFalse(missing["measurement_valid"])
            self.assertGreater(missing["command_wall_ns"], 0)

    def test_timeout_reaps_owned_process_group(self):
        with tempfile.TemporaryDirectory() as folder:
            code = "import signal,time;signal.signal(signal.SIGTERM,lambda *a:None);time.sleep(20)"
            result = run(
                [sys.executable, "-c", code],
                Path(folder) / "timeout",
                timeout_seconds=0.15,
                grace_seconds=0.02,
            )
            self.assertEqual(
                (result["outcome"], result["returncode"]),
                ("timed_out", -signal.SIGKILL),
            )
            self.assertTrue(result["measurement_valid"])
            with self.assertRaises(ProcessLookupError):
                os.kill(result["pid"], 0)

    def test_changed_source_is_reported_as_invalid_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.txt"
            source.write_text("before")
            result = run(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path;"
                    "import sys;Path(sys.argv[1]).write_text('after')",
                    str(source),
                ],
                Path(folder) / "changed",
                source_paths=[source],
            )
            self.assertEqual(result["outcome"], "succeeded")
            self.assertFalse(result["sources_unchanged"])
            self.assertFalse(result["measurement_valid"])

    def test_cancel_after_reap_retains_usage_without_signalling_old_pid(self):
        real_wait, real_killpg = meter_module._wait, os.killpg

        def after_reap(pid, deadline, state):
            real_wait(pid, deadline, state)
            raise meter_module._Cancelled(signal.SIGTERM)

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(meter_module, "_wait", side_effect=after_reap),
            patch.object(os, "killpg", wraps=real_killpg) as signals,
        ):
            result = run(
                [sys.executable, "-c", "print('completed')"], Path(folder) / "race"
            )
        self.assertEqual((result["outcome"], result["returncode"]), ("cancelled", 0))
        self.assertIsNotNone(result["waited_cpu_ns"])
        self.assertTrue(all(call.args[1] == 0 for call in signals.call_args_list))

    def test_cli_cancellation_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            ready, output = Path(folder) / "ready", Path(folder) / "cancelled"
            code = "from pathlib import Path;import sys,time;Path(sys.argv[1]).touch();time.sleep(20)"
            meter = Path(__file__).with_name("perc1_process_meter.py")
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(meter),
                    "--output",
                    str(output),
                    "--grace",
                    "0.2",
                    "--",
                    sys.executable,
                    "-c",
                    code,
                    str(ready),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    self.assertIsNone(process.poll())
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                process.send_signal(signal.SIGTERM)
                time.sleep(0.02)
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            self.assertEqual((process.returncode, stderr), (1, b""))
            result = json.loads(stdout)
            self.assertEqual(
                (result["outcome"], result["cancellation"]),
                ("cancelled", signal.SIGTERM),
            )
            self.assertEqual(json.loads((output / "receipt.json").read_bytes()), result)


if __name__ == "__main__":
    unittest.main()
