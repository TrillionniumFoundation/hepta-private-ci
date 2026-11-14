"""Local fail-closed tests; never claim physical performance or signing."""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hepta_cell_split_capture_integrity import (  # noqa: E402
    CaptureIntegrityError,
    capture_run_files,
    require_absent,
    write_new_durable,
)


class CaptureIntegrityTests(unittest.TestCase):
    def test_unseen_result_is_admissible_preflight(self):
        with tempfile.TemporaryDirectory() as root:
            require_absent(Path(root) / "next.json")

    def test_prepopulated_result_is_rejected_even_if_correctly_named(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "256-physical_split.json"
            path.write_text('{"schema":"hepta.cell-split.host-measurement.v1"}')
            with self.assertRaisesRegex(CaptureIntegrityError, "preexisting"):
                require_absent(path)

    def test_dangling_symlink_cannot_bypass_exclusive_preflight(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "future.json"
            try:
                path.symlink_to(Path(root) / "not-created")
            except (NotImplementedError, OSError):
                self.skipTest("symlinks unavailable")
            self.assertFalse(path.exists())
            with self.assertRaises(CaptureIntegrityError):
                require_absent(path)

    def test_preserves_raw_bytes_and_all_lineage_digests(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            raw = b'{ "scopes": 64, "mode": "no_split" }\n'
            paths = [base / "result.json", base / "stdout.log", base / "stderr.log"]
            for path, body in zip(paths, (raw, b"started\n", b""), strict=True):
                path.write_bytes(body)
            actual, proof = capture_run_files(*paths, ["./hepta-worker", "--batch=off"])
            self.assertEqual(actual, raw)
            self.assertEqual(proof["raw_measurement_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(proof["stdout_sha256"], hashlib.sha256(b"started\n").hexdigest())
            self.assertEqual(proof["stderr_sha256"], hashlib.sha256(b"").hexdigest())
            self.assertEqual(len(proof["argv_sha256"]), 64)

    def test_symlink_result_fails_before_capture(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            target = base / "actual.json"
            target.write_text("{}")
            result = base / "result.json"
            try:
                result.symlink_to(target)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks unavailable")
            stdout, stderr = base / "stdout", base / "stderr"
            stdout.write_bytes(b"")
            stderr.write_bytes(b"")
            with self.assertRaises(CaptureIntegrityError):
                capture_run_files(result, stdout, stderr, ["python"])

    def test_hardlink_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            target = base / "same-physical-file"
            target.write_text("{}")
            result = base / "result.json"
            try:
                os.link(target, result)
            except OSError:
                self.skipTest("hardlinks unavailable")
            stdout, stderr = base / "stdout", base / "stderr"
            stdout.write_bytes(b"")
            stderr.write_bytes(b"")
            with self.assertRaises(CaptureIntegrityError):
                capture_run_files(result, stdout, stderr, ["python"])

    def test_durable_new_output_cannot_replace_existing(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "published.json"
            write_new_durable(path, b"first")
            with self.assertRaises(CaptureIntegrityError):
                write_new_durable(path, b"forged")
            self.assertEqual(path.read_bytes(), b"first")

    def test_missing_result_or_invalid_argv_fails(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            stdout, stderr = base / "stdout", base / "stderr"
            stdout.write_bytes(b"")
            stderr.write_bytes(b"")
            with self.assertRaises(CaptureIntegrityError):
                capture_run_files(base / "missing.json", stdout, stderr, ["worker"])
            result = base / "result.json"
            result.write_bytes(b"{}")
            with self.assertRaises(CaptureIntegrityError):
                capture_run_files(result, stdout, stderr, [])


if __name__ == "__main__":
    unittest.main()
