"""Actual process failures must survive diagnostic collection."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "cargo_deny_diagnostics", Path(__file__).with_name("cargo_deny_diagnostics.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DiagnosticStatusTests(unittest.TestCase):
    def test_failure_and_both_output_streams_are_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "codex-rs").mkdir()
            (root / "codex-rs/Cargo.lock").write_text("version = 4\n")
            output = root / "diagnostic"
            output.mkdir()
            command = [
                sys.executable,
                "-c",
                "import sys; print('graph failure'); print('details', file=sys.stderr); sys.exit(7)",
            ]
            status = MODULE.run_and_record(command, root, output)
            self.assertEqual(status, 7)
            record = json.loads((output / "RESULT.json").read_text())
            self.assertEqual(record["exit_code"], 7)
            self.assertEqual(
                record["cargo_lock_sha256_before"], record["cargo_lock_sha256_after"]
            )
            self.assertEqual(
                set((output / "cargo-deny.log").read_text().splitlines()),
                {"graph failure", "details"},
            )


if __name__ == "__main__":
    unittest.main()
