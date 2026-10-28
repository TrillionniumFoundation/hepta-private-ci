"""Validate bounded evidence capture without downloading crates or compiling."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import capture_cargo_deny_diagnostic as diagnostic


@unittest.skipUnless(sys.platform == "linux", "the diagnostic runs on Ubuntu")
class CaptureTests(unittest.TestCase):
    def test_truncation_preserves_actual_exit_and_full_stream_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = diagnostic.capture(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'x'*10000); sys.stderr.buffer.write(b'y'*7000); sys.exit(17)",
                ],
                root,
                root,
                "failure",
                timeout=5,
                limit=101,
            )
            self.assertEqual(result["exit_code"], 17)
            self.assertFalse(result["timed_out"])
            for name, data in (("stdout", b"x" * 10000), ("stderr", b"y" * 7000)):
                self.assertEqual(
                    result["streams"][name],
                    {
                        "path": f"failure.{name}.log",
                        "observed_bytes": len(data),
                        "observed_sha256": hashlib.sha256(data).hexdigest(),
                        "retained_bytes": 101,
                        "truncated": True,
                        "complete": False,
                        "retained_sha256": hashlib.sha256(data[:101]).hexdigest(),
                    },
                )
                self.assertEqual(
                    (root / f"failure.{name}.log").read_bytes(), data[:101]
                )

    def test_small_output_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = diagnostic.capture(
                [sys.executable, "-c", "print('complete')"],
                root,
                root,
                "small",
                timeout=5,
            )
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(result["timed_out"])
            self.assertTrue(
                all(not stream["truncated"] for stream in result["streams"].values())
            )
            self.assertTrue(
                all(stream["complete"] for stream in result["streams"].values())
            )
            self.assertEqual((root / "small.stdout.log").read_bytes(), b"complete\n")

    def test_timeout_is_not_reported_as_normal_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = diagnostic.capture(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                root,
                root,
                "timeout",
                timeout=0.1,
            )
            self.assertTrue(result["timed_out"])
            self.assertLess(result["exit_code"], 0)

    def test_closed_pipes_do_not_bypass_the_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = diagnostic.capture(
                [
                    sys.executable,
                    "-c",
                    "import os, time; os.close(1); os.close(2); time.sleep(10)",
                ],
                root,
                root,
                "closed",
                timeout=0.1,
            )
            self.assertTrue(result["timed_out"])
            self.assertLess(result["exit_code"], 0)

    def test_unverified_archive_is_not_extracted_or_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar.gz"
            archive.write_bytes(b"untrusted archive")
            with self.assertRaisesRegex(ValueError, "archive identity mismatch"):
                diagnostic.unpack_verified(archive, root)
            self.assertFalse((root / "cargo-deny").exists())


class CheckpointTests(unittest.TestCase):
    def test_failed_atomic_replace_preserves_previous_complete_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = {"qualification": False}
            diagnostic.checkpoint(root, receipt, "downloading_tool")
            before = (root / "receipt.json").read_bytes()
            with patch.object(
                diagnostic.os, "replace", side_effect=OSError("write interrupted")
            ):
                with self.assertRaisesRegex(OSError, "write interrupted"):
                    diagnostic.checkpoint(root, receipt, "finished", "completed")
            self.assertEqual((root / "receipt.json").read_bytes(), before)
            self.assertFalse((root / "receipt.json.tmp").exists())
            saved = json.loads(before)
            self.assertEqual(
                (saved["status"], saved["phase"]), ("in_progress", "downloading_tool")
            )
            self.assertFalse(saved["qualification"])

    def test_interrupted_and_completed_capture_keep_identity_and_worktree_states(self):
        for interrupted in (True, False):
            with (
                self.subTest(interrupted=interrupted),
                tempfile.TemporaryDirectory() as directory,
            ):
                temporary = Path(directory)
                root, output = temporary / "repository", temporary / "output"
                for name in diagnostic.INPUTS:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture\n")

                def captured(_command, _root, destination, label, **_kwargs):
                    contents = {
                        "source": f"{'a' * 40}\n{'b' * 40}\n",
                        "worktree_before": "?? newly-created-file\n",
                        "cargo_version": "cargo 1.95.0 (fixture)\n",
                        "rustc_version": "rustc 1.95.0 (fixture)\n",
                        "cargo_deny": "fixture finding\n",
                        "worktree_after": "",
                    }[label]
                    if label == "cargo_deny":
                        running = json.loads((output / "receipt.json").read_text())
                        self.assertEqual(
                            (running["status"], running["phase"]),
                            ("in_progress", "running_diagnostic"),
                        )
                    (destination / f"{label}.stdout.log").write_text(contents)
                    return {
                        "exit_code": 23 if label == "cargo_deny" else 0,
                        "timed_out": False,
                        "streams": {
                            "stdout": {"observed_bytes": len(contents.encode())}
                        },
                    }

                def downloaded(directory):
                    if interrupted:
                        raise KeyboardInterrupt
                    binary = directory / "test-binary-never-executed"
                    binary.write_bytes(b"fixture")
                    return binary

                with (
                    patch.object(
                        diagnostic,
                        "__file__",
                        str(root / "scripts" / "capture_cargo_deny_diagnostic.py"),
                    ),
                    patch.object(
                        diagnostic.sys,
                        "argv",
                        ["diagnostic", "--output-dir", str(output)],
                    ),
                    patch.object(diagnostic.sys, "platform", "linux"),
                    patch.object(diagnostic.platform, "machine", return_value="x86_64"),
                    patch.object(diagnostic, "capture", side_effect=captured),
                    patch.object(diagnostic, "download_tool", side_effect=downloaded),
                ):
                    if interrupted:
                        with self.assertRaises(KeyboardInterrupt):
                            diagnostic.main()
                    else:
                        self.assertEqual(diagnostic.main(), 0)
                saved = json.loads((output / "receipt.json").read_text())
                self.assertEqual(saved["source_commit"], "a" * 40)
                self.assertEqual(set(saved["inputs_before"]), set(diagnostic.INPUTS))
                self.assertFalse(saved["worktree_clean_before"])
                self.assertFalse(saved["qualification"])
                if interrupted:
                    self.assertEqual(
                        (saved["status"], saved["phase"]),
                        ("in_progress", "downloading_tool"),
                    )
                    self.assertIsNone(saved["worktree_clean_after"])
                else:
                    self.assertEqual(
                        (saved["status"], saved["phase"]), ("completed", "finished")
                    )
                    self.assertTrue(saved["worktree_clean_after"])
                    self.assertTrue(saved["inputs_unchanged"])
                    self.assertEqual(saved["runs"]["diagnostic"]["exit_code"], 23)

    def test_non_x86_64_platform_records_error_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            with (
                patch.object(
                    diagnostic.sys, "argv", ["diagnostic", "--output-dir", str(output)]
                ),
                patch.object(diagnostic.sys, "platform", "linux"),
                patch.object(diagnostic.platform, "machine", return_value="aarch64"),
                patch.object(diagnostic, "capture") as capture,
                patch.object(diagnostic, "download_tool") as download,
            ):
                self.assertEqual(diagnostic.main(), 1)
            capture.assert_not_called()
            download.assert_not_called()
            saved = json.loads((output / "receipt.json").read_text())
            self.assertEqual(saved["status"], "capture_error")
            self.assertIn("Linux x86_64", saved["capture_error"])
            self.assertIsNone(saved["worktree_clean_before"])
            self.assertIsNone(saved["worktree_clean_after"])
            self.assertFalse(saved["qualification"])


if __name__ == "__main__":
    unittest.main()
