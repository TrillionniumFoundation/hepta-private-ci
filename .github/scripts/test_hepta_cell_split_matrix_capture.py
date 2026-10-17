"""Fail-closed tests for the exact 16-case target-host capture adapter.

The subprocess fixture below emits synthetic observations solely to verify the
diagnostic file protocol; it is not deployment evidence.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from hepta_cell_split_matrix_capture import (
    MAX_HOST_RESULT_BYTES,
    MEASUREMENT_SCHEMA,
    SCHEMA,
    execute_matrix,
    read_bounded_json,
    validate_manifest,
    validate_measurement,
)
from hepta_cell_split_perf_gate import InvalidEvidence, MODES, SCOPES


def manifest():
    return {
        "schema": SCHEMA,
        "source_sha": "a" * 40,
        "hardware_id": "unattested-unit-host",
        "model_digest": "test-model",
        "workload_digest": "frozen-unit-workload",
        "runs": [
            {
                "scopes": scope,
                "mode": mode,
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
            }
            for scope in SCOPES
            for mode in MODES
        ],
    }


def observed(packet, scope=64, mode="no_split"):
    return {
        "schema": MEASUREMENT_SCHEMA,
        "source_sha": packet["source_sha"],
        "hardware_id": packet["hardware_id"],
        "model_digest": packet["model_digest"],
        "workload_digest": packet["workload_digest"],
        "scopes": scope,
        "mode": mode,
        "measurement_source": "unit-test:process-counters",
        "attempted_request_trace_sha256": "b" * 64,
        "attempted": 100,
        "completed": 100,
        "elapsed_seconds": 1,
        "p50_ms": 1,
        "p95_ms": 2,
        "p99_ms": 3,
        "cpu_seconds": 1,
        "rss_peak_bytes": 4096,
        "communication_bytes": 10,
        "native_backend_calls": 100,
        "native_batch_requests": 0,
        "fsync_count": 100,
        "lock_wait_ms": 2,
        "recovery_ms": 3,
        "failed_requests": 0,
        "negative_transfer_rate": 0,
    }


class CellSplitMatrixCaptureTests(unittest.TestCase):
    def test_requires_exact_sixteen_unique_commands(self):
        packet = manifest()
        assert len(validate_manifest(packet)) == 16
        packet["runs"].pop()
        with self.assertRaises(InvalidEvidence):
            validate_manifest(packet)
        packet = manifest()
        packet["runs"][-1] = packet["runs"][0]
        with self.assertRaises(InvalidEvidence):
            validate_manifest(packet)
        packet = manifest()
        packet["runs"][0]["argv"] = ["sh", "-c", ""]
        with self.assertRaises(InvalidEvidence):
            validate_manifest(packet)

    def test_rejects_claims_instead_of_filling_missing_counters(self):
        packet = manifest()
        sample = observed(packet)
        self.assertEqual(
            validate_measurement(sample, packet, 64, "no_split")["p99_ms"], 3
        )
        sample["measurement_source"] = "synthetic-fixture"
        with self.assertRaises(InvalidEvidence):
            validate_measurement(sample, packet, 64, "no_split")
        sample = observed(packet)
        sample.pop("cpu_seconds")
        with self.assertRaises(InvalidEvidence):
            validate_measurement(sample, packet, 64, "no_split")
        sample = observed(packet)
        sample.pop("attempted_request_trace_sha256")
        with self.assertRaises(InvalidEvidence):
            validate_measurement(sample, packet, 64, "no_split")
        sample = observed(packet)
        sample["workload_digest"] = "different"
        with self.assertRaises(InvalidEvidence):
            validate_measurement(sample, packet, 64, "no_split")

    def test_single_host_row_rejects_fractional_rss_and_u64_overflow(self):
        packet = manifest()
        for field, invalid in (("rss_peak_bytes", 100.5), ("fsync_count", 1 << 64)):
            with self.subTest(field=field):
                row = observed(packet)
                row[field] = invalid
                with self.assertRaisesRegex(InvalidEvidence, "exact unsigned 64-bit"):
                    validate_measurement(row, packet, 64, "no_split")

    def test_external_result_reader_is_bounded_and_requires_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            valid.write_text('{"ok":true}', encoding="utf-8")
            self.assertEqual(
                read_bounded_json(valid, MAX_HOST_RESULT_BYTES, "host result"),
                {"ok": True},
            )
            oversized = root / "oversized.json"
            oversized.write_bytes(b" " * (MAX_HOST_RESULT_BYTES + 1))
            with self.assertRaisesRegex(InvalidEvidence, "exceeds"):
                read_bounded_json(oversized, MAX_HOST_RESULT_BYTES, "host result")
            with self.assertRaises(InvalidEvidence):
                read_bounded_json(root, MAX_HOST_RESULT_BYTES, "host result")

    def test_rejects_ambiguous_json_and_nonfinite_literals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "measurement.json"
            for raw, message in (
                ('{"source_sha":"a","source_sha":"b"}', "duplicate JSON field"),
                ('{"nested":{"attempted":1,"attempted":2}}', "duplicate JSON field"),
                ('{"attempted":NaN}', "non-finite JSON literal"),
                ('{"attempted":Infinity}', "non-finite JSON literal"),
            ):
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaisesRegex(InvalidEvidence, message):
                        read_bounded_json(path, MAX_HOST_RESULT_BYTES, "host result")

    def test_prior_case_cannot_preplant_later_result_or_logs(self):
        packet = manifest()
        script = """
import json
import os
from pathlib import Path

row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
row["mode"] = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
current = Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"])
current.write_text(json.dumps(row), encoding="utf-8")
next_case = current.parent / os.environ["HEPTA_TEST_PLANTED_FILE"]
next_case.write_text(json.dumps(row), encoding="utf-8")
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", script]
        for planted in (
            "64-logical_split.json",
            "64-logical_split.stdout.log",
            "64-logical_split.stderr.log",
        ):
            with (
                self.subTest(planted=planted),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "matrix"
                with (
                    patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                    patch.dict(
                        os.environ,
                        {
                            "HEPTA_TEST_MEASUREMENT": json.dumps(observed(packet)),
                            "HEPTA_TEST_PLANTED_FILE": planted,
                        },
                    ),
                    self.assertRaisesRegex(InvalidEvidence, "pre-existing"),
                ):
                    execute_matrix(packet, ROOT, output, 30)
                self.assertTrue((output / "64-no_split.stdout.log").exists())
                self.assertFalse((output / "measured-matrix.json").exists())
                self.assertFalse((output / "diagnostic-comparison.json").exists())
                if planted != "64-logical_split.stdout.log":
                    self.assertFalse((output / "64-logical_split.stdout.log").exists())

    def test_oversized_first_result_aborts_before_other_fifteen_runs(self):
        packet = manifest()
        fixture_script = """
import os
from pathlib import Path
Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"]).write_bytes(
    b" " * (int(os.environ["HEPTA_TEST_RESULT_LIMIT"]) + 1)
)
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matrix"
            with (
                patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                patch.dict(
                    os.environ,
                    {"HEPTA_TEST_RESULT_LIMIT": str(MAX_HOST_RESULT_BYTES)},
                ),
                self.assertRaisesRegex(InvalidEvidence, "exceeds"),
            ):
                execute_matrix(packet, ROOT, output, 30)
            self.assertTrue((output / "64-no_split.stdout.log").exists())
            self.assertFalse((output / "64-logical_split.stdout.log").exists())
            self.assertFalse((output / "measured-matrix.json").exists())

    def test_first_malformed_host_row_aborts_before_other_fifteen_runs(self):
        packet = manifest()
        fixture_script = """
import json
import os
from pathlib import Path
row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
row["mode"] = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"]).write_text(json.dumps(row))
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        row = observed(packet)
        row["attempted"] = (1 << 53) + 1
        row["completed"] = 1 << 53
        row["failed_requests"] = 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matrix"
            with (
                patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                patch.dict(os.environ, {"HEPTA_TEST_MEASUREMENT": json.dumps(row)}),
                self.assertRaisesRegex(
                    InvalidEvidence, "inconsistent terminal request"
                ),
            ):
                execute_matrix(packet, ROOT, output, 30)
            self.assertTrue((output / "64-no_split.stdout.log").exists())
            self.assertFalse((output / "64-logical_split.stdout.log").exists())
            self.assertFalse((output / "measured-matrix.json").exists())

    def test_executes_all_16_commands_but_cannot_attest_itself(self):
        packet = manifest()
        fixture_script = """
import json
import os
from pathlib import Path
scope = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
mode = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
packet = json.loads(os.environ["HEPTA_TEST_PACKET"])
row = packet["measurement"]
row["scopes"] = scope
row["mode"] = mode
Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"]).write_text(json.dumps(row))
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matrix"
            # Injecting fixture counters is acceptable only within this
            # source-only unit test; they never authorize production.
            data = {"measurement": observed(packet)}
            with (
                patch(
                    "hepta_cell_split_matrix_capture.verify_exact_source"
                ) as source_check,
                patch.dict(os.environ, {"HEPTA_TEST_PACKET": json.dumps(data)}),
            ):
                result = execute_matrix(packet, ROOT, output, 30)
            # One matrix preflight, two checks per workload and one final check.
            self.assertEqual(source_check.call_count, 34)
            self.assertTrue(result["comparative_gate_passed"])
            self.assertFalse(result["production_evidence_verified"])
            self.assertFalse(result["production_activation_authorized"])
            self.assertEqual(
                len(json.loads((output / "measured-matrix.json").read_text())["runs"]),
                16,
            )
            with (
                patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                self.assertRaises(FileExistsError),
            ):
                execute_matrix(packet, ROOT, output, 30)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_workload_mutating_tracked_source_aborts_before_second_run(self):
        packet = manifest()
        script = """
import json
import os
from pathlib import Path

Path("tracked.txt").write_text("changed by workload", encoding="utf-8")
row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
row["mode"] = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"]).write_text(
    json.dumps(row), encoding="utf-8"
)
"""
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            checkout.mkdir()
            (checkout / "tracked.txt").write_text("frozen", encoding="utf-8")
            subprocess.run(
                ["git", "init", "-q"], cwd=checkout, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "add", "tracked.txt"],
                cwd=checkout,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Hepta Test",
                    "-c",
                    "user.email=hepta-test@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "freeze",
                ],
                cwd=checkout,
                check=True,
                capture_output=True,
            )
            packet["source_sha"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
            ).strip()
            packet["runs"][0]["argv"] = [sys.executable, "-c", script]
            output = Path(directory) / "matrix"
            with patch.dict(
                os.environ,
                {"HEPTA_TEST_MEASUREMENT": json.dumps(observed(packet))},
            ):
                with self.assertRaisesRegex(InvalidEvidence, "source checkout"):
                    execute_matrix(packet, checkout, output, 30)
            self.assertTrue((output / "64-no_split.stdout.log").exists())
            self.assertFalse((output / "64-logical_split.stdout.log").exists())
            self.assertFalse((output / "measured-matrix.json").exists())


    def test_later_workload_cannot_rewrite_previous_original_bytes(self):
        """A valid numeric aggregate is not proof the original bytes survived."""
        packet = manifest()
        fixture_script = """
import json
import os
from pathlib import Path

result = Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"])
scope = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
mode = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = scope
row["mode"] = mode
result.write_text(json.dumps(row), encoding="utf-8")
if scope == 64 and mode == "logical_split":
    path = result.parent / os.environ["HEPTA_TEST_TAMPER_TARGET"]
    with path.open("ab") as handle:
        handle.write(b" ")
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        for previous in (
            "manifest.json",
            "64-no_split.json",
            "64-no_split.stdout.log",
            "64-no_split.stderr.log",
        ):
            with (
                self.subTest(previous=previous),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "matrix"
                with (
                    patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                    patch.dict(
                        os.environ,
                        {
                            "HEPTA_TEST_MEASUREMENT": json.dumps(observed(packet)),
                            "HEPTA_TEST_TAMPER_TARGET": previous,
                        },
                    ),
                    self.assertRaisesRegex(
                        InvalidEvidence, "original host evidence changed"
                    ),
                ):
                    execute_matrix(packet, ROOT, output, 30)
                self.assertFalse((output / "measured-matrix.json").exists())
                self.assertFalse((output / "diagnostic-comparison.json").exists())


    def test_replaced_inode_with_identical_bytes_cannot_survive_matrix_capture(self):
        """SHA equality alone must not launder replacement of an original inode."""
        packet = manifest()
        fixture_script = """
import json
import os
from pathlib import Path

result = Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"])
scope = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
mode = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = scope
row["mode"] = mode
result.write_text(json.dumps(row), encoding="utf-8")
if scope == 64 and mode == "logical_split":
    original = result.parent / os.environ["HEPTA_TEST_REPLACE_TARGET"]
    # Keep the original file descriptor open so the filesystem cannot reuse
    # the retired inode number for the identical-byte replacement.
    with original.open("rb") as predecessor:
        original_bytes = predecessor.read()
        original.unlink()
        original.write_bytes(original_bytes)
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        for previous in (
            "manifest.json",
            "64-no_split.json",
            "64-no_split.stdout.log",
        ):
            with (
                self.subTest(previous=previous),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "matrix"
                with (
                    patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                    patch.dict(
                        os.environ,
                        {
                            "HEPTA_TEST_MEASUREMENT": json.dumps(observed(packet)),
                            "HEPTA_TEST_REPLACE_TARGET": previous,
                        },
                    ),
                    self.assertRaisesRegex(
                        InvalidEvidence, "original host evidence changed"
                    ),
                ):
                    execute_matrix(packet, ROOT, output, 30)
                self.assertFalse((output / "measured-matrix.json").exists())
                self.assertFalse((output / "diagnostic-comparison.json").exists())

    def test_oversized_host_log_aborts_before_later_cases(self):
        packet = manifest()
        fixture_script = """
import json
import os
from pathlib import Path
row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
row["mode"] = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"]).write_text(json.dumps(row))
print("x" * (2 * 1024 * 1024 + 1))
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matrix"
            with (
                patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                patch.dict(
                    os.environ,
                    {"HEPTA_TEST_MEASUREMENT": json.dumps(observed(packet))},
                ),
                self.assertRaisesRegex(InvalidEvidence, "exceeds"),
            ):
                execute_matrix(packet, ROOT, output, 30)
            self.assertTrue((output / "64-no_split.stdout.log").exists())
            self.assertFalse((output / "64-logical_split.stdout.log").exists())
            self.assertFalse((output / "measured-matrix.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink required")
    def test_later_workload_cannot_substitute_prior_result_symlink(self):
        packet = manifest()
        fixture_script = """
import json
import os
from pathlib import Path
result = Path(os.environ["HEPTA_CELL_SPLIT_RESULT_PATH"])
scope = int(os.environ["HEPTA_CELL_SPLIT_EXPECTED_SCOPE"])
mode = os.environ["HEPTA_CELL_SPLIT_EXPECTED_MODE"]
row = json.loads(os.environ["HEPTA_TEST_MEASUREMENT"])
row["scopes"] = scope
row["mode"] = mode
result.write_text(json.dumps(row))
if scope == 64 and mode == "logical_split":
    earlier = result.parent / "64-no_split.json"
    earlier.unlink()
    earlier.symlink_to(result)
"""
        for run in packet["runs"]:
            run["argv"] = [sys.executable, "-c", fixture_script]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matrix"
            with (
                patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                patch.dict(
                    os.environ,
                    {"HEPTA_TEST_MEASUREMENT": json.dumps(observed(packet))},
                ),
                self.assertRaises(InvalidEvidence),
            ):
                execute_matrix(packet, ROOT, output, 30)
            self.assertFalse((output / "measured-matrix.json").exists())


if __name__ == "__main__":
    unittest.main()
