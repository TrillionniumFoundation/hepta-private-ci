"""Behavioral checks for evidence/source boundaries, not static claim flags."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run, semantics
from .run import source_snapshot, validate_result


class SourceTests(unittest.TestCase):
    def test_altered_executed_bytes_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "study.py"
            path.write_bytes(b"print(1)\n")
            data = path.read_bytes()
            manifest = {
                "schema": "ndu.rl-audit.source.v1",
                "base_commit": "a" * 40,
                "files": {
                    "study.py": {
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "git_blob": hashlib.sha1(b"blob 9\0" + data).hexdigest(),
                        "bytes": len(data),
                    }
                },
            }
            registration = root / "SOURCE.json"
            registration.write_text(json.dumps(manifest))
            before = source_snapshot(root, registration)
            self.assertEqual(before["files"], manifest["files"])
            path.write_bytes(b"print(2)\n")
            with self.assertRaisesRegex(ValueError, "Source changed"):
                source_snapshot(root, registration)

    def test_manifest_cannot_read_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registration = root / "SOURCE.json"
            for name in ("../outside.py", str(root / "outside.py")):
                registration.write_text(
                    json.dumps({"schema": "ndu.rl-audit.source.v1", "base_commit": "a" * 40, "files": {name: {}}})
                )
                with self.assertRaisesRegex(ValueError, "escapes"):
                    source_snapshot(root, registration)

    def test_successful_exit_cannot_override_retained_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "PROTOCOL.json").write_text("{}")
            output = root / "child"
            binding = {"files": {"registered": "bytes"}}
            with patch.object(run, "DIRECTORY", root), patch.object(run, "source_snapshot", return_value=binding):
                with patch.object(semantics, "audit", side_effect=SystemExit(0)):
                    with self.assertRaises(SystemExit) as raised:
                        run.child("semantics", output)
            self.assertEqual(raised.exception.code, 0)
            with self.assertRaisesRegex(ValueError, "retained a failure"):
                validate_result(output, "semantics", binding)

    def test_missing_or_changed_physical_results_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            binding = {"files": {"registered": "bytes"}}
            (output / "START.json").write_text(json.dumps({"phase": "structure", "source_binding": binding}))
            settings = {"panels": [{"name": "p"}], "seeds": [1], "families": [], "targets": []}
            registration = {"structure": settings}
            with self.assertRaises(FileNotFoundError):
                validate_result(output, "structure", binding, registration)
            data = (
                json.dumps(
                    {
                        "panel": {"name": "p"},
                        "seed": 1,
                        "records": [
                            {"family": "reference", "kind": "exact"},
                            {"family": "reference", "kind": "fixed_known_model"},
                            {"family": "action_ablation", "kind": "frozen"},
                        ],
                    }
                )
                + "\n"
            ).encode()
            result = {
                "phase": "structure",
                "source_binding": binding,
                "data": {
                    "protocol": settings,
                    "case_files": [
                        {"path": "case.json", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    ],
                },
            }
            (output / "RESULT.json").write_text(json.dumps(result))
            (output / "case.json").write_bytes(data)
            self.assertTrue(validate_result(output, "structure", binding, registration))
            (output / "case.json").write_bytes(b'{"observed":2}\n')
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                validate_result(output, "structure", binding, registration)
            result["data"]["case_files"] = []
            (output / "RESULT.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "roster"):
                validate_result(output, "structure", binding, registration)


if __name__ == "__main__":
    unittest.main()
