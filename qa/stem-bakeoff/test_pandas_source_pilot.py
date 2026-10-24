"""Focused receipt and cap checks; no pandas source imports or benchmarks."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas_source_pilot as pilot


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.snapshot = {"source_bytes": 0, "runtime_build_bytes": 0,
            "free_disk_bytes": 4_000_000_000, "shared_cgroup_memory_current": 1}

    def test_failing_child_keeps_measured_receipt_and_logs(self):
        with patch.object(pilot, "resources", return_value=self.snapshot):
            with self.assertRaisesRegex(RuntimeError, "pilot command failed"):
                pilot.command(self.root, "fixture", [sys.executable, "-I", "-B", "-c",
                    "import sys; print('fixture'); print('failed',file=sys.stderr); sys.exit(3)"])
        receipt = json.loads((self.root / "commands/fixture/receipt.json").read_bytes())
        self.assertEqual(receipt["exit_code"], 3)
        self.assertGreater(receipt["child_cpu_ns"], 0)
        self.assertEqual((self.root / "commands/fixture/stdout.log").read_text(), "fixture\n")
        self.assertEqual((self.root / "commands/fixture/stderr.log").read_text(), "failed\n")
        with self.assertRaises(FileExistsError):
            pilot.command(self.root, "fixture", [sys.executable])

    def test_cap_rejects_before_any_child(self):
        over = dict(self.snapshot, runtime_build_bytes=pilot.BUILD_CAP + 1)
        with patch.object(pilot, "resources", return_value=over), patch.object(pilot.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "preflight resource cap"):
                pilot.command(self.root, "over", [sys.executable])
        popen.assert_not_called()
        receipt = json.loads((self.root / "commands/over/receipt.json").read_bytes())
        self.assertFalse(receipt["launched"])

    def test_protocol_and_interpreter_pins_cannot_drift(self):
        protocol, python = self.root / "protocol", self.root / "python"
        protocol.write_text("train, no benchmark outcomes")
        python.write_bytes(b"fixture interpreter")
        with patch.object(pilot, "PYTHON", str(python)), patch.object(pilot, "resources", return_value=self.snapshot):
            pilot.freeze(self.root, protocol)
            self.assertEqual(pilot.verify_plan(self.root)["role"], "train_build_qualification")
            protocol.write_text("changed")
            with self.assertRaisesRegex(ValueError, "identity changed"):
                pilot.verify_plan(self.root)


if __name__ == "__main__":
    unittest.main()
