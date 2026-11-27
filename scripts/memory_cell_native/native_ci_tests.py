"""Evidence-retention regression tests; no pretrained model is imported."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_ci_support import command, validate_inputs


class NativeEvidenceTests(unittest.TestCase):
    def test_nonzero_command_keeps_original_streams_and_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            code = "import sys; print('raw output', flush=True); print('raw error', file=sys.stderr, flush=True); sys.exit(7)"
            with self.assertRaises(RuntimeError):
                command(
                    output,
                    "failed",
                    [sys.executable, "-I", "-B", "-c", code],
                    cwd=output,
                    timeout=10,
                )
            directory = output / "commands/failed"
            self.assertEqual((directory / "stdout.log").read_text(), "raw output\n")
            self.assertEqual((directory / "stderr.log").read_text(), "raw error\n")
            receipt = json.loads((directory / "receipt.json").read_text())
            self.assertEqual(
                (receipt["exit_code"], receipt["timed_out"], receipt["attempts"]),
                (7, False, 1),
            )

    def test_timeout_keeps_partial_stream_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            code = "import time; print('before timeout', flush=True); time.sleep(30)"
            with self.assertRaises(RuntimeError):
                command(
                    output,
                    "timeout",
                    [sys.executable, "-I", "-B", "-c", code],
                    cwd=output,
                    timeout=1,
                )
            directory = output / "commands/timeout"
            self.assertEqual((directory / "stdout.log").read_text(), "before timeout\n")
            receipt = json.loads((directory / "receipt.json").read_text())
            self.assertEqual(
                (receipt["exit_code"], receipt["timed_out"], receipt["attempts"]),
                (-9, True, 1),
            )

    def test_retained_input_mismatch_is_rejected_before_execution(self):
        fixtures = Path(__file__).resolve().parent / "fixtures"
        original, _ = validate_inputs(fixtures)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source-inputs.json").write_text(json.dumps(original))
            (root / original["archive"]).write_bytes(b"different source bytes")
            with self.assertRaises(ValueError):
                validate_inputs(root)


if __name__ == "__main__":
    unittest.main()
