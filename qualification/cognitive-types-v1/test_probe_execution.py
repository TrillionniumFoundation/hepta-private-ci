"""Executable probe-boundary fixtures; no fixture claims a Rust qualification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import probe_execution as probe
import quality_checks as quality


class ProbeExecutionTests(unittest.TestCase):
    def command(self, data, code=0):
        return [sys.executable, "-S", "-c", f"import sys;sys.stdout.buffer.write({data!r});sys.exit({code})"]

    def invoke(self, data, code=0, expected=None):
        return probe.invoke_probe(self.command(data, code), b"fixture", expected)

    def test_strict_integer_identity_rejects_python_boolean_equivalence(self):
        expected = {"outcome": "accepted", "encoded_bytes": 1}
        result = self.invoke(b'{"outcome":"accepted","encoded_bytes":true}', expected=expected)
        self.assertIs(result["passed"], False)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(self.invoke(b'{"outcome":"accepted","encoded_bytes":1}', expected=expected)["passed"])

    def test_public_quality_entrypoint_uses_the_same_strict_executor(self):
        command = self.command(b'{"outcome":"accepted","encoded_bytes":true}')
        self.assertFalse(quality.invoke(command, b"fixture", {"outcome": "accepted", "encoded_bytes": 1})["passed"])

    def test_nested_type_equality_is_not_coerced(self):
        for value in (True, 1.0, "1", None):
            self.assertFalse(probe.same_typed_value({"a": [value]}, {"a": [1]}))
        self.assertTrue(probe.same_typed_value({"a": [2**64 - 1]}, {"a": [2**64 - 1]}))
        self.assertFalse(probe.same_typed_value({"a": 1, "extra": 2}, {"a": 1}))

    def test_ambiguous_or_malformed_json_is_infrastructure_invalid(self):
        for data in (b'[]', b'null', b'1', b'"accepted"', b'{}', b'\xff',
                     b'{"outcome":"accepted","outcome":"rejected"}',
                     b'{"outcome":"accepted","nested":{"x":1,"x":2}}',
                     b'{"outcome":"accepted","n":NaN}',
                     b'{"outcome":"accepted","n":Infinity}',
                     b'{"outcome":"accepted","n":1.0}',
                     b'{"outcome":"accepted","n":1e0}',
                     b'{"outcome":"accepted","n":' + b'9' * 40 + b'}',
                     b'{"outcome":"accepted"}{}'):
            with self.subTest(data=data):
                result = self.invoke(data, expected={"outcome": "accepted"})
                self.assertFalse(result["passed"])
                self.assertEqual(result["status"], "infrastructure_invalid")

    def test_complete_raw_hashes_preserve_all_observed_bytes(self):
        data = b'{"outcome":"accepted","encoded_bytes":18446744073709551615}\n'
        result = self.invoke(data, expected={"outcome": "accepted", "encoded_bytes": 2**64 - 1})
        self.assertTrue(result["passed"])
        self.assertEqual(result["stdout_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(result["stderr_sha256"], hashlib.sha256(b"").hexdigest())

    def test_semantic_rejection_requires_consistent_exit_code(self):
        self.assertTrue(self.invoke(b'{"outcome":"rejected"}', code=2)["passed"])
        for code, outcome in ((0, "rejected"), (2, "accepted"), (101, "rejected"), (1, "rejected")):
            with self.subTest(code=code, outcome=outcome):
                result = self.invoke(json.dumps({"outcome": outcome}).encode(), code=code)
                self.assertFalse(result["passed"])
                self.assertEqual(result["status"], "infrastructure_invalid")

    def test_wrong_semantic_result_is_failed_not_a_process_failure(self):
        result = self.invoke(b'{"outcome":"accepted"}')
        self.assertEqual(result["status"], "failed")
        result = self.invoke(b'{"outcome":"rejected"}', 2, {"outcome": "accepted"})
        self.assertEqual(result["status"], "failed")

    def test_stdout_limit_is_exact_and_never_a_truncated_success(self):
        data = b'{"outcome":"accepted"}'
        at_limit = data + b' ' * (probe.MAX_STDOUT_BYTES - len(data))
        self.assertTrue(self.invoke(at_limit, expected={"outcome": "accepted"})["passed"])
        result = self.invoke(at_limit + b' ', expected={"outcome": "accepted"})
        self.assertFalse(result["passed"])
        self.assertIn("byte limit", result["error"])
        self.assertNotIn("stdout_sha256", result)

    def test_stderr_flood_is_bounded(self):
        command = [sys.executable, "-S", "-c", "import sys;sys.stderr.buffer.write(b'x'*300000);print('{\"outcome\":\"accepted\"}')"]
        result = probe.invoke_probe(command, b"", {"outcome": "accepted"})
        self.assertFalse(result["passed"])
        self.assertIn("stderr byte limit", result["error"])

    def test_large_input_cannot_deadlock_with_simultaneous_output(self):
        data = b'x' * probe.MAX_INPUT_BYTES
        command = [sys.executable, "-S", "-c", "import sys,json;sys.stderr.buffer.write(b'x'*65536);sys.stderr.flush();n=len(sys.stdin.buffer.read());print(json.dumps({'outcome':'accepted','encoded_bytes':n}))"]
        result = probe.invoke_probe(command, data, {"outcome": "accepted", "encoded_bytes": len(data)})
        self.assertTrue(result["passed"], result)
        self.assertEqual(len(result["stderr"]), 4000)
        self.assertEqual(result["stderr_sha256"], hashlib.sha256(b'x' * 65536).hexdigest())
        result = probe.invoke_probe(command, data + b'x', {"outcome": "accepted"})
        self.assertFalse(result["passed"])
        self.assertIn("oversized", result["error"])

    def test_bad_command_or_deadline_is_not_a_semantic_rejection(self):
        for command, timeout in ((["/nonexistent/cognitive-probe"], 1), ([], 1), ([sys.executable], 0),
                                 ([sys.executable], float("nan")), ([sys.executable], True)):
            self.assertEqual(probe.invoke_probe(command, b"", timeout=timeout)["status"], "infrastructure_invalid")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs lifecycle assertion")
    def test_deadline_kills_grandchild_holding_inherited_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            child_path = Path(directory) / "child"
            script = ("import subprocess,sys,pathlib;"
                      "p=subprocess.Popen([sys.executable,'-S','-c','import time;time.sleep(30)']);"
                      f"pathlib.Path({str(child_path)!r}).write_text(str(p.pid));"
                      "print('{\"outcome\":\"accepted\"}',flush=True)")
            started = time.monotonic()
            result = probe.invoke_probe([sys.executable, "-S", "-c", script], b"", {"outcome": "accepted"}, timeout=0.4)
            self.assertEqual(result["status"], "infrastructure_invalid")
            self.assertIn("deadline", result["error"])
            self.assertLess(time.monotonic() - started, 5)
            pid = int(child_path.read_text())
            for _ in range(100):
                try:
                    state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0]
                except FileNotFoundError:
                    break
                if state == "Z":
                    break
                time.sleep(0.01)
            else:
                self.fail("grandchild remained live after bounded probe cleanup")


class PerformanceEvidenceTests(unittest.TestCase):
    def samples(self):
        rows = []
        for index in range(1, quality.PERFORMANCE_SAMPLES + 1):
            rows.append({"passed": True, "status": "passed", "exit_code": 0,
                         "case": "event:maximum-declared-collection-counts", "implementation": "rust",
                         "sample": index, "wire_sha256": "a" * 64,
                         "report": {"outcome": "accepted", "contract": "MemoryEventV1",
                                    "elapsed_ns": str(index * 2560), "repeat": quality.PERFORMANCE_REPEATS,
                                    "encoded_bytes": 4096, "wire_sha256": "a" * 64,
                                    "frozen_sha256": "b" * 64, "bound_sha256": "c" * 64}})
        return rows

    def test_valid_measurements_are_observations_not_threshold_or_allocation_claims(self):
        result = quality.performance_summary(self.samples())
        self.assertTrue(result["measurementValid"])
        self.assertEqual(result["nsPerDecodeValidateEncode"], {"minimum": 10, "median": 20, "maximum": 30})
        self.assertIsNone(result["allocationMeasurement"])
        self.assertIs(result["latencyThresholdEnforced"], False)

    def test_empty_partial_extra_or_reordered_samples_reject(self):
        rows = self.samples()
        for samples in ([], rows[:2], rows + [rows[0]], list(reversed(rows)), None):
            self.assertFalse(quality.performance_summary(samples)["measurementValid"])

    def test_numeric_fields_follow_the_actual_probe_profile_without_coercion(self):
        for field in ("repeat", "encoded_bytes"):
            for value in (True, False, 1.9, "256", None, 0, -1):
                with self.subTest(field=field, value=value):
                    rows = self.samples()
                    rows[0]["report"][field] = value
                    self.assertFalse(quality.performance_summary(rows)["measurementValid"])
        for value in (True, 256, 1.9, "1.9", "1e3", " 256", "+256", "0256", "0", "-1",
                      "", "１２３", None, str(2**128)):
            with self.subTest(elapsed=value):
                rows = self.samples()
                rows[0]["report"]["elapsed_ns"] = value
                self.assertFalse(quality.performance_summary(rows)["measurementValid"])
        rows = self.samples()
        rows[0]["report"]["elapsed_ns"] = str(2**128 - 1)
        self.assertTrue(quality.performance_summary(rows)["measurementValid"])

    def test_failed_samples_and_wrong_workload_cannot_produce_valid_statistics(self):
        for key, value in (("passed", False), ("passed", 1), ("exit_code", False), ("status", "pending"),
                           ("implementation", "node"), ("sample", True), ("case", "smaller-workload")):
            rows = self.samples()
            rows[0][key] = value
            self.assertFalse(quality.performance_summary(rows)["measurementValid"])
        for key, value in (("contract", "RecallPacketV1"), ("wire_sha256", "d" * 64),
                           ("frozen_sha256", "d" * 64), ("bound_sha256", "d" * 64),
                           ("encoded_bytes", 4095), ("repeat", 255)):
            rows = self.samples()
            rows[1]["report"][key] = value
            self.assertFalse(quality.performance_summary(rows)["measurementValid"])


if __name__ == "__main__":
    unittest.main()
