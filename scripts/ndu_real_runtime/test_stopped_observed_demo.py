"""Retain real subprocess failures in the collector's outer cost ledger."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .stopped_observed_demo import command


class ObservedCommandTests(unittest.TestCase):
    def test_failed_and_timed_out_commands_keep_logs_and_duration(self):
        cases = (
            (
                "failed",
                "import sys;sys.stderr.write('measured failure');sys.exit(3)",
                10,
                RuntimeError,
            ),
            ("timed_out", "import time;time.sleep(10)", 0.1, subprocess.TimeoutExpired),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, source, timeout, exception in cases:
                with self.assertRaises(exception):
                    command(
                        root,
                        label,
                        [sys.executable, "-c", source],
                        root,
                        timeout=timeout,
                    )
                folder = root / "commands" / label
                receipt = json.loads((folder / "receipt.json").read_text())
                self.assertEqual(receipt["status"], label)
                self.assertGreater(receipt["wall_seconds"], 0)
                self.assertEqual(len(receipt["stderr_sha256"]), 64)
            self.assertEqual(
                (root / "commands/failed/stderr.log").read_text(), "measured failure"
            )


if __name__ == "__main__":
    unittest.main()
