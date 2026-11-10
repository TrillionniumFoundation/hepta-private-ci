"""Input-integrity protocol tests; actual Torch fitting is a separate native run."""

import json
from pathlib import Path
import tempfile
import unittest

from . import answer_repair_native as native


class NativeAnswerRepairTests(unittest.TestCase):
    def test_request_pin_rejects_before_creating_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text("{}")
            with self.assertRaisesRegex(ValueError, "identity differs"):
                native.execute(request, "0" * 64, root / "output")
            self.assertFalse((root / "output").exists())

    def test_runner_pin_rejects_before_reading_label_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({"native_runner_sha256": "0" * 64}))
            with self.assertRaisesRegex(ValueError, "runner source"):
                native.execute(
                    request, native.sha(request.read_bytes()), root / "output"
                )
            self.assertFalse((root / "output").exists())

    def test_create_once_retains_original_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = Path(temporary) / "RESULT.json"
            pin = native.write_once(result, {"status": "failed"})
            with self.assertRaises(FileExistsError):
                native.write_once(result, {"status": "completed"})
            self.assertEqual(native.read(result, pin), result.read_bytes())
            self.assertEqual(json.loads(result.read_bytes()), {"status": "failed"})


if __name__ == "__main__":
    unittest.main()
