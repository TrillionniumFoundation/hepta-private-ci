#!/usr/bin/env python3
"""Regression tests for rejection classification; these do not run Rust."""
import json
from pathlib import Path
import tempfile
import unittest

from cognitive_store_api_probe import check_diagnostics, metadata_artifact


def diagnostic(code="E0432", text="no DurableCognitiveStore in root"):
    return json.dumps({"level": "error", "code": {"code": code}, "message": text, "spans": [{}]})


class ApiProbeTests(unittest.TestCase):
    def test_positive_control(self):
        check_diagnostics(0, "", None, "")

    def test_positive_control_rejects_build_failure(self):
        with self.assertRaises(ValueError):
            check_diagnostics(1, diagnostic(), None, "")

    def test_expected_denial_and_summary(self):
        summary = json.dumps({"level": "error", "message": "aborting due to 1 previous error", "spans": []})
        check_diagnostics(1, diagnostic() + "\n" + summary, "E0432", "DurableCognitiveStore")

    def test_success_is_not_denial(self):
        with self.assertRaises(ValueError):
            check_diagnostics(0, "", "E0432", "DurableCognitiveStore")

    def test_unrelated_missing_dependency_is_not_denial(self):
        with self.assertRaises(ValueError):
            check_diagnostics(1, diagnostic("E0463", "cannot find crate store"), "E0432", "DurableCognitiveStore")

    def test_wrong_symbol_is_not_denial(self):
        with self.assertRaises(ValueError):
            check_diagnostics(1, diagnostic(text="no SomethingElse in root"), "E0432", "DurableCognitiveStore")

    def test_additional_error_is_not_hidden(self):
        with self.assertRaises(ValueError):
            check_diagnostics(1, diagnostic() + "\n" + diagnostic("E0308", "type mismatch"), "E0432", "DurableCognitiveStore")

    def test_non_json_tool_failure_is_not_denial(self):
        with self.assertRaises(ValueError):
            check_diagnostics(1, "rustc: not found", "E0432", "DurableCognitiveStore")

    def test_ice_without_code_is_not_denial(self):
        error = json.dumps({"level": "error", "message": "internal compiler error", "spans": []})
        with self.assertRaises(ValueError):
            check_diagnostics(101, diagnostic() + "\n" + error, "E0432", "DurableCognitiveStore")

    def test_missing_artifact_rejects(self):
        with self.assertRaises(ValueError):
            metadata_artifact('{"reason":"build-finished","success":true}')

    def test_exact_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "libstore.rmeta"
            path.write_bytes(b"fixture metadata, not compiled Rust")
            event = {"reason": "compiler-artifact", "target": {"name": "codex_hepta_cognitive_store"}, "filenames": [str(path)]}
            self.assertEqual(metadata_artifact(json.dumps(event)), path.resolve())

    def test_ambiguous_artifact_rejects(self):
        event = {"reason": "compiler-artifact", "target": {"name": "codex_hepta_cognitive_store"}, "filenames": ["one.rmeta", "two.rmeta"]}
        with self.assertRaises(ValueError):
            metadata_artifact(json.dumps(event))


if __name__ == "__main__":
    unittest.main()
