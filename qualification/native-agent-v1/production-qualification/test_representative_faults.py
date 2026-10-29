"""Exercise actual process fixtures and reject unauthorized recovery transitions."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import representative_faults as faults
from protocol_driver import LaneAbort


class RepresentativeFaultTests(unittest.TestCase):
    def test_uninjected_eof_does_not_authorize_another_runner(self):
        runner = object.__new__(faults.ControlledRunner)
        runner.args = SimpleNamespace(case="recover_process")
        runner.restarts, runner.report, runner.watcher = 0, {}, None
        runner.child = SimpleNamespace(receive=Mock(side_effect=LaneAbort(str({"_eof": True}))),
            reader_failure=None, process=SimpleNamespace(returncode=-9))
        runner.spawn = Mock()
        with self.assertRaises(LaneAbort):
            runner.receive(time.monotonic() + 2)
        runner.spawn.assert_not_called()

    def test_cancel_reconciliation_rejects_a_lost_cancel_checkpoint(self):
        runner = object.__new__(faults.ControlledRunner)
        runner.args = SimpleNamespace(output=Path("/not-used"))
        runner.command = {"op": "run", "session": "original", "input": "original"}
        evidence = {key: {} for key in ("remote", "job", "binding", "child", "child_sha256",
            "manifest_sha256", "admission_sha256", "admission", "model_admissions")}
        evidence["state"] = {"pending_tool": {"submission_attempted": True, "cancel_requested": False}}
        runner.report = {"before": evidence}
        runner.child = SimpleNamespace(send=Mock())
        with patch.object(faults, "operation_evidence", return_value=evidence):
            with self.assertRaisesRegex(ValueError, "observation-only"):
                runner.reconcile_cancel(time.monotonic() + 2)
        runner.child.send.assert_not_called()

    def test_frozen_processes_emit_started_and_preserve_actual_process_lifecycle(self):
        corpus = json.loads((faults.HERE / "corpus.json").read_bytes())
        for case in corpus["cases"]:
            if case["id"] not in ("cancel", "recover_process"):
                continue
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                workspace, _, _ = faults.prepare(case, root)
                process = subprocess.Popen([sys.executable, "-I", "-B", "-S", str(faults.HERE / "workspace_tool.py"),
                    "hepta_fixture", "{}", str(root / "workspace.json")], cwd=workspace,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(process.stdout.readline(), b"STARTED\n")
                    self.assertIsNone(process.poll())
                    if case["id"] == "cancel":
                        # This unit test controls only its own Popen object;
                        # remote runtime cancellation is a separate experiment.
                        process.terminate()
                        self.assertNotEqual(process.wait(timeout=3), 0)
                    else:
                        self.assertEqual(process.wait(timeout=5), 0)
                        self.assertEqual((workspace / "done").read_bytes(), b"once\n")
                    self.assertEqual(process.stderr.read(), b"")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=3)
                    process.stdout.close()
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
