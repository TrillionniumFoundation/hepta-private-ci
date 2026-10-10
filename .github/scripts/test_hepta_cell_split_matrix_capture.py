"""Fail-closed tests for the exact 16-case target-host capture adapter.

The subprocess fixture below emits synthetic observations solely to verify the
diagnostic file protocol; it is not deployment evidence.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from hepta_cell_split_matrix_capture import (
    MEASUREMENT_SCHEMA,
    SCHEMA,
    execute_matrix,
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
        sample["workload_digest"] = "different"
        with self.assertRaises(InvalidEvidence):
            validate_measurement(sample, packet, 64, "no_split")

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
            import os

            data = {"measurement": observed(packet)}
            with (
                patch("hepta_cell_split_matrix_capture.verify_exact_source"),
                patch.dict(os.environ, {"HEPTA_TEST_PACKET": json.dumps(data)}),
            ):
                result = execute_matrix(packet, ROOT, output, 30)
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


if __name__ == "__main__":
    unittest.main()
