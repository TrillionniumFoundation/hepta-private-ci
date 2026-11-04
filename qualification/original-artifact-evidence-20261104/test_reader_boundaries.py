#!/usr/bin/env python3
"""Only parser/binding controls; these do not execute any original product."""
import json
import unittest

from verify import sha, verify_outputs
from verify_memory_current import parse_cargo_metadata_log


class MetadataLogControls(unittest.TestCase):
    document = b'{"packages":[],"workspace_members":[],"version":1}\n'

    def test_plain_metadata(self):
        value, prefix = parse_cargo_metadata_log(self.document)
        self.assertEqual(value["packages"], [])
        self.assertEqual(prefix["bytes"], 0)

    def test_diagnostic_prefix_is_retained(self):
        raw = b" Downloading crates ...\n  Downloaded example v1.0.0\n"
        value, prefix = parse_cargo_metadata_log(raw + self.document)
        self.assertEqual(value["version"], 1)
        self.assertEqual(prefix["bytes"], len(raw))
        self.assertEqual(prefix["sha256"], sha(raw))
        self.assertEqual(prefix["preview_utf8"].encode(), raw)

    def test_missing_document_is_rejected(self):
        with self.assertRaises(RuntimeError):
            parse_cargo_metadata_log(b"error: no metadata\n")

    def test_two_documents_are_rejected(self):
        with self.assertRaises(RuntimeError):
            parse_cargo_metadata_log(self.document + self.document)

    def test_trailing_output_is_rejected(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_cargo_metadata_log(self.document + b"unbound trailing text")

    def test_duplicate_json_key_is_rejected(self):
        with self.assertRaises(RuntimeError):
            parse_cargo_metadata_log(b'{"packages":[],"packages":[],"workspace_members":[],"version":1}\n')

    def test_wrong_metadata_shape_is_rejected(self):
        with self.assertRaises(RuntimeError):
            parse_cargo_metadata_log(b'{"packages":[],"workspace_members":[],"version":2}\n')


class CommandLogControls(unittest.TestCase):
    def test_original_single_unnamed_command(self):
        raw = b"original process output"
        result = verify_outputs({"commands": [{"log_sha256": sha(raw)}]},
                                {"original-process-suites.log": raw})
        self.assertEqual(result["command_logs"], 1)

    def test_two_explicit_command_logs(self):
        rows = [{"log_sha256": sha(b"original")}, {"log_sha256": sha(b"controls")}]
        result = verify_outputs({"commands": rows}, {"main.log": b"original", "controls.log": b"controls"},
                                ["main.log", "controls.log"])
        self.assertEqual(result["command_logs"], 2)

    def test_secondary_log_cannot_reuse_first_digest(self):
        rows = [{"log_sha256": sha(b"original")}, {"log_sha256": sha(b"original")}]
        with self.assertRaises(RuntimeError):
            verify_outputs({"commands": rows}, {"main.log": b"original", "controls.log": b"controls"},
                           ["main.log", "controls.log"])

    def test_missing_or_duplicate_mapping_is_rejected(self):
        rows = [{"log_sha256": sha(b"one")}, {"log_sha256": sha(b"two")}]
        for paths in (["a.log"], ["a.log", "a.log"]):
            with self.subTest(paths=paths), self.assertRaises(RuntimeError):
                verify_outputs({"commands": rows}, {"a.log": b"one", "b.log": b"two"}, paths)

    def test_named_command_mapping_cannot_change(self):
        with self.assertRaises(RuntimeError):
            verify_outputs({"commands": [{"name": "actual", "log_sha256": sha(b"one")}]},
                           {"other.log": b"one"}, ["other.log"])


if __name__ == "__main__":
    unittest.main()
