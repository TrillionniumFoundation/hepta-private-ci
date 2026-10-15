"""Original byte-bound CPython HTTP runtime witnesses, not upstream tests."""

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

from memory_original_http_runtime import (
    EXPECTED,
    ORIGINAL_SHA256,
    WORKER_SHA256,
    offline_original_execution,
    strict_json,
    verify_worker_payload,
)
from real_source_reader_probe import real_source


class RuntimeWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = os.getenv("MEMORY_REAL_SOURCE_ZIP")
        reopen = os.getenv("MEMORY_REOPEN_ZIP")
        if not src or not reopen:
            raise unittest.SkipTest("both historical original ZIPs required")
        cls.paths = (Path(src), Path(reopen))
        cls.sources = real_source(*cls.paths)

    @staticmethod
    def fake_receipt():
        import base64

        return dict(
            schema="hepta.original-cpython-http-execution-worker.v1",
            original_module_sha256=ORIGINAL_SHA256,
            isolated=True,
            network_calls_allowed=False,
            upstream_project_suite_executed=False,
            interpreter="3.13.5",
            cases=[
                dict(
                    id=name,
                    captured_base64=base64.b64encode(value).decode("ascii"),
                    captured_sha256=hashlib.sha256(value).hexdigest(),
                    captured_bytes=len(value),
                )
                for name, value in EXPECTED.items()
            ],
        )

    def test_original_module_actually_executes_all_three_byte_effects(self):
        report = offline_original_execution(self.sources)
        self.assertEqual(report["original_cpython_crossfile_edges"], 3)
        self.assertEqual(report["original_crossfile_static_link_count"], 12)
        self.assertEqual(report["actual_original_module_offline_behaviors"], 3)
        self.assertEqual(report["original_worker_code_sha256"], WORKER_SHA256)
        self.assertTrue(all(r["exact_http_behavior_passed"] for r in report["verified_behavior_receipts"]))
        self.assertEqual({r["id"] for r in report["verified_behavior_receipts"]}, set(EXPECTED))
        self.assertFalse(report["upstream_cpython_test_suite_executed"])
        self.assertFalse(report["original_external_project_tests_executed"])
        self.assertFalse(report["network_calls_allowed"])
        self.assertFalse(report["independent_host_execution_authenticated"])
        self.assertFalse(report["production_qualified"])

    def test_protocol_outputs_are_not_merely_self_reported_hashes(self):
        item = self.fake_receipt()
        item["cases"][0]["captured_base64"] = "YWJj"
        with self.assertRaisesRegex(ValueError, "HTTP bytes differ"):
            verify_worker_payload(item)

    def test_changed_stdout_digest_rejected(self):
        item = self.fake_receipt()
        item["cases"][2]["captured_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "HTTP bytes differ"):
            verify_worker_payload(item)

    def test_reordered_executable_cases_rejected(self):
        item = self.fake_receipt()
        item["cases"].reverse()
        with self.assertRaisesRegex(ValueError, "reordered"):
            verify_worker_payload(item)

    def test_worker_isolation_must_be_explicit(self):
        item = self.fake_receipt()
        item["isolated"] = False
        with self.assertRaisesRegex(ValueError, "worker execution"):
            verify_worker_payload(item)

    def test_upstream_suite_may_not_be_claimed(self):
        item = self.fake_receipt()
        item["upstream_project_suite_executed"] = True
        with self.assertRaisesRegex(ValueError, "worker execution"):
            verify_worker_payload(item)

    def test_worker_source_drift_rejected_before_execution(self):
        original_worker = Path(__file__).with_name("memory_original_http_worker.py")
        with tempfile.TemporaryDirectory() as tmp:
            altered = Path(tmp) / "tampered_worker.py"
            altered.write_bytes(original_worker.read_bytes() + b"# changed\n")
            with self.assertRaisesRegex(ValueError, "worker code changed"):
                offline_original_execution(self.sources, worker_path=altered)

    def test_changed_original_cpython_module_is_rejected(self):
        files, original_blobs = self.sources
        blobs = dict(original_blobs)
        key = ("python/cpython", "Lib/http/client.py")
        blobs[key] = blobs[key].replace(b"    def putheader(", b"    def NOTHEADER(", 1)
        with self.assertRaisesRegex(ValueError, "original Git file differs"):
            offline_original_execution((files, blobs))

    def test_changed_original_caller_is_rejected(self):
        files, original_blobs = self.sources
        blobs = dict(original_blobs)
        key = ("python/cpython", "Lib/test/test_httplib.py")
        blobs[key] = blobs[key].replace(b"conn.putheader", b"conn.fakehead", 1)
        with self.assertRaisesRegex(ValueError, "original Git file differs"):
            offline_original_execution((files, blobs))

    def test_outer_zip_and_binary_reopen_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            altered = Path(tmp) / "wrong-outer.zip"
            altered.write_bytes(self.paths[0].read_bytes() + b"x")
            with self.assertRaisesRegex(ValueError, "whole ZIP digest"):
                real_source(altered, self.paths[1])
            altered.write_bytes(self.paths[1].read_bytes() + b"x")
            with self.assertRaisesRegex(ValueError, "whole ZIP digest"):
                real_source(self.paths[0], altered)

    def test_duplicate_worker_json_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate worker JSON field"):
            strict_json(b'{"schema":"a","schema":"b"}')

    def test_cli_output_is_immutable_and_replay_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audited-runtime.json"
            program = Path(__file__).with_name("memory_original_http_runtime.py")
            cmd = [sys.executable, str(program), "--source-zip", str(self.paths[0]),
                   "--reopen-zip", str(self.paths[1]), "--output", str(path)]
            initial = subprocess.run(cmd, text=True, capture_output=True, timeout=50)
            self.assertEqual(initial.returncode, 0, initial.stderr)
            first = path.read_bytes()
            self.assertEqual(json.loads(first)["execution_subprocess_exit_code"], 0)
            second = subprocess.run(cmd, text=True, capture_output=True, timeout=50)
            self.assertNotEqual(second.returncode, 0, "output overwrite must fail")
            self.assertEqual(path.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
