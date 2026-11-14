"""Original-Git-only static dependency proofs; no external project code executed."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from memory_original_crossfile_trace import (
    CASES,
    EXPECTED_ROOTS,
    _python_trace,
    _rust_trace,
    audit,
)
from real_source_reader_probe import SOURCE_SHA, REOPEN_SHA, real_source


class OriginalCrossfileTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        cls.reopen = os.environ.get("MEMORY_REOPEN_ZIP")
        if not cls.source or not cls.reopen:
            raise unittest.SkipTest("original exact-ZIP source and independent reopen required")
        cls.paths = (Path(cls.source), Path(cls.reopen))
        cls.files, cls.blobs = real_source(*cls.paths)

    def test_verified_actual_12_links_three_evaluation_roots(self):
        report = audit((self.files, self.blobs))
        self.assertEqual(report["original_source_derived_edges"], 12)
        self.assertEqual(report["root_counts"], EXPECTED_ROOTS)
        self.assertEqual(report["python_links"], 9)
        self.assertEqual(report["rust_literal_import_links"], 3)
        self.assertEqual(report["original_git_blob_count"], 32)
        self.assertFalse(report["independent_human_semantic_judgement"])
        self.assertFalse(report["real_project_tests_executed"])
        self.assertFalse(report["production_qualified"])
        self.assertIsNone(report["task_success_rate"])
        self.assertEqual(report["new_model_calls"], 0)

    def test_original_git_line_hash_and_different_implementation_file(self):
        rows = audit((self.files, self.blobs))["cases"]
        self.assertEqual(len({r["id"] for r in rows}), 12)
        for row in rows:
            with self.subTest(row=row["id"]):
                self.assertNotEqual(row["caller_file"], row["implementation_file"])
                self.assertEqual(len(row["call_site_sha256"]), 64)
                self.assertEqual(len(row["import_site_sha256"]), 64)
                self.assertEqual(len(row["definition_site_sha256"]), 64)
                self.assertTrue(row["syntax_link_proved"])
                self.assertFalse(row["executable_project_test_ran"])

    def test_original_outer_zip_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "corrupt.zip"
            path.write_bytes(self.paths[0].read_bytes() + b"BAD")
            with self.assertRaisesRegex(ValueError, "whole ZIP digest"):
                real_source(path, self.paths[1])

    def test_original_reopen_zip_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "corrupt.zip"
            path.write_bytes(self.paths[1].read_bytes() + b"BAD")
            with self.assertRaisesRegex(ValueError, "whole ZIP digest"):
                real_source(self.paths[0], path)

    def test_mutated_source_bytes_rejected(self):
        blobs = dict(self.blobs)
        key = ("python/cpython", "Lib/http/client.py")
        blobs[key] = blobs[key].replace(b"def putheader", b"def NO_HEADER", 1)
        with self.assertRaisesRegex(ValueError, "original Git file differs"):
            audit((self.files, blobs))

    def test_missing_or_duplicate_original_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "source census"):
            audit((self.files[:-1], self.blobs))
        copy = deepcopy(self.files)
        copy[1] = copy[0]
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            audit((copy, self.blobs))

    def test_train_partition_cannot_enter_evaluation(self):
        files = deepcopy(self.files)
        changed = next(x for x in files if x["repo"] == "python/cpython" and x["path"] == "Lib/http/client.py")
        changed["partition"] = "train"
        with self.assertRaisesRegex(ValueError, "cross-partition"):
            audit((files, self.blobs))

    def test_python_explicit_import_cannot_be_replaced(self):
        spec = next(x for x in CASES if x[0] == "sk-base-01")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = caller.replace("_preprocess_data,", "_something_else,", 1)
        self.assertNotEqual(caller, bad)
        with self.assertRaisesRegex(ValueError, "import/call/implementation"):
            _python_trace(spec, bad, callee)

    def test_python_original_callsite_cannot_be_removed(self):
        spec = next(x for x in CASES if x[0] == "sk-base-02")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        # Every call to the expected function must be erased, leaving intact
        # original imported names so 'import only' cannot score as linked.
        bad = caller.replace("= _rescale_data(X, y, sample_weight)", "= nonexistent_call(X, y, sample_weight)")
        self.assertNotEqual(caller, bad)
        with self.assertRaisesRegex(ValueError, "import/call/implementation"):
            _python_trace(spec, bad, callee)

    def test_python_shadowed_import_symbol_is_not_a_cross_file_call(self):
        spec = next(x for x in CASES if x[0] == "sk-base-01")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = caller.replace("def test_preprocess_data(global_random_seed):\n    rng =", "def test_preprocess_data(global_random_seed):\n    _preprocess_data = lambda *args: None\n    rng =", 1)
        self.assertNotEqual(caller, bad)
        with self.assertRaisesRegex(ValueError, "locally shadowed"):
            _python_trace(spec, bad, callee)

    def test_constructor_alias_rebinding_rejects_forged_method_call(self):
        spec = next(x for x in CASES if x[0] == "py-http-02")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        old = "        conn.putheader('Content-length', 42)"
        self.assertIn(old, caller)
        bad = caller.replace(old, "        conn = other_connection()\n" + old, 1)
        with self.assertRaisesRegex(ValueError, "rebound"):
            _python_trace(spec, bad, callee)

    def test_python_implementation_definition_cannot_be_removed(self):
        spec = next(x for x in CASES if x[0] == "sk-log-02")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = callee.replace("def _log_reg_scoring_path(", "def hidden_scoring_path(", 1)
        self.assertNotEqual(callee, bad)
        with self.assertRaisesRegex(ValueError, "import/call/implementation"):
            _python_trace(spec, caller, bad)

    def test_python_constructor_alias_required(self):
        spec = next(x for x in CASES if x[0] == "py-http-02")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = caller.replace("conn = client.HTTPConnection('example.com')", "conn = other_constructor('example.com')")
        self.assertNotEqual(caller, bad)
        with self.assertRaisesRegex(ValueError, "constructor-alias"):
            _python_trace(spec, bad, callee)

    def test_python_missing_actual_class_method_is_not_resolved(self):
        spec = next(x for x in CASES if x[0] == "py-http-03")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = callee.replace("    def send(", "    def NOT_SEND(", 1)
        self.assertNotEqual(callee, bad)
        with self.assertRaisesRegex(ValueError, "owner method missing"):
            _python_trace(spec, caller, bad)

    def test_rust_exact_import_is_required(self):
        spec = next(x for x in CASES if x[0] == "deno-01")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = caller.replace("use crate::cache::url_to_filename;", "use crate::cache::NOT_SAME_FUNCTION;")
        self.assertNotEqual(caller, bad)
        with self.assertRaisesRegex(ValueError, "Rust import/definition/reference"):
            _rust_trace(spec, bad, callee)

    def test_rust_line_use_is_required(self):
        spec = next(x for x in CASES if x[0] == "deno-02")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        lines = caller.splitlines(keepends=True)
        self.assertIn("NOT_FOUND_CACHE_HEADER", lines[729])
        lines[729] = lines[729].replace("NOT_FOUND_CACHE_HEADER", "OTHER_HEADER")
        with self.assertRaisesRegex(ValueError, "Rust import/definition/reference"):
            _rust_trace(spec, "".join(lines), callee)

    def test_rust_definition_is_required(self):
        spec = next(x for x in CASES if x[0] == "deno-03")
        caller = self.blobs[spec[1], spec[2]].decode()
        callee = self.blobs[spec[1], spec[5]].decode()
        bad = callee.replace("pub enum CacheReadFileError", "pub enum OTHER_ERROR", 1)
        self.assertNotEqual(callee, bad)
        with self.assertRaisesRegex(ValueError, "Rust import/definition/reference"):
            _rust_trace(spec, caller, bad)

    def test_cli_report_is_deterministic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "report.json"
            script = Path(__file__).with_name("memory_original_crossfile_trace.py")
            cmd = [sys.executable, str(script), "--source-zip", str(self.paths[0]),
                   "--reopen-zip", str(self.paths[1]), "--output", str(target)]
            first = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            self.assertEqual(first.returncode, 0, first.stderr)
            a = target.read_bytes()
            self.assertEqual(json.loads(a)["verified_cross_file_static_links"], 12)
            second = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(target.read_bytes(), a)


if __name__ == "__main__":
    unittest.main()
