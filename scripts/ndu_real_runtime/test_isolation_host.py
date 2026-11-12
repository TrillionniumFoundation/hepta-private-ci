"""Recorder failure accounting; namespace success is never inferred here."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from .isolation_host import MAX_FILE_BYTES, _kernel_audit, _read, record_host


class IsolationHostTests(unittest.TestCase):
    def test_missing_policy_is_unknown_with_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            observed = _read(Path(directory) / "missing")
        self.assertEqual(
            observed, {"state": "UNAVAILABLE", "error": "FileNotFoundError", "errno": 2}
        )

    def test_over_budget_policy_preserves_prefix_without_claiming_complete_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy"
            path.write_bytes(b"a" * MAX_FILE_BYTES + b"unobserved suffix")
            observed = _read(path)
        raw = base64.b64decode(observed["raw_base64"])
        self.assertEqual(observed["state"], "TRUNCATED")
        self.assertEqual(raw, b"a" * MAX_FILE_BYTES)
        self.assertEqual(observed["sha256"], hashlib.sha256(raw).hexdigest())

    def test_actual_missing_tool_retains_probe_failure_and_unknown_attribution(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("shutil.which", return_value=None),
        ):
            output = Path(directory) / "observation"
            report = record_host(output)
            retained = json.loads((output / "HOST.json").read_bytes())
            probe = (output / "probe" / "RECEIPT.json").read_bytes()
        self.assertEqual(retained, report)
        self.assertEqual(report["probe"]["status"], "SETUP_FAILED")
        self.assertEqual(
            report["probe"]["receipt"],
            {"bytes": len(probe), "sha256": hashlib.sha256(probe).hexdigest()},
        )
        self.assertEqual(report["apparmor_audit_attribution"], "UNKNOWN")
        self.assertFalse(report["kernel_audit_evidence_retained"])
        self.assertEqual(
            report["kernel_audit"],
            {"state": "UNAVAILABLE", "error": "FileNotFoundError", "errno": 2},
        )
        self.assertFalse(report["probe_counts_as_required_test"])

    def test_kernel_audit_is_time_scoped_bounded_and_never_a_test_pass(self):
        observed = subprocess.CompletedProcess(
            args=["journalctl"],
            returncode=0,
            stdout=b"apparmor=DENIED operation=userns\n",
            stderr=b"",
        )
        with (
            mock.patch("shutil.which", return_value="/usr/bin/journalctl"),
            mock.patch("subprocess.run", return_value=observed) as run,
        ):
            audit = _kernel_audit(2_000_000_000)
        command = run.call_args.args[0]
        self.assertEqual(audit["state"], "OBSERVED")
        self.assertEqual(audit["returncode"], 0)
        self.assertEqual(
            base64.b64decode(audit["stdout"]["raw_base64"]), observed.stdout
        )
        self.assertEqual(command[command.index("--since") + 1], "@1")
        self.assertEqual(command[command.index("--lines") + 1], "256")
        self.assertIn("--grep", command)

    def test_kernel_audit_timeout_remains_unknown(self):
        with (
            mock.patch("shutil.which", return_value="/usr/bin/journalctl"),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(["journalctl"], 5),
            ),
        ):
            audit = _kernel_audit(1)
        self.assertEqual(
            audit, {"state": "UNAVAILABLE", "error": "TimeoutExpired", "errno": None}
        )

    def test_existing_observation_cannot_launch_another_probe(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("ndu_real_runtime.isolation_host.run_isolated_actor") as run,
        ):
            with self.assertRaises(FileExistsError):
                record_host(directory)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
