"""Subprocess regression fixtures only. No genuine host or production claims."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# This stub is intentionally test-only. It is not the shipped performance gate;
# the regression tests focus on runner file provenance and process isolation.
fake_gate = types.ModuleType("hepta_cell_split_perf_gate")
fake_gate.SCOPES = (64, 256, 1024, 4096)
fake_gate.MODES = (
    "no_split",
    "logical_split",
    "optimized_logical_split",
    "physical_split",
)
fake_gate.TRACE_FIELD = "attempted_request_trace_sha256"
fake_gate.FIELDS = (
    "attempted", "completed", "elapsed_seconds", "p50_ms", "p95_ms", "p99_ms",
    "cpu_seconds", "rss_peak_bytes", "communication_bytes", "native_backend_calls",
    "native_batch_requests", "fsync_count", "lock_wait_ms", "recovery_ms",
    "failed_requests", "negative_transfer_rate",
)
fake_gate.InvalidEvidence = type("InvalidEvidence", (ValueError,), {})
fake_gate.validate_run_numbers = lambda entry, scope, mode: None


def fake_analyze(packet):
    assert len(packet["runs"]) == 16
    return {
        "comparative_gate_passed": True,
        "violations": [],
        "production_evidence_verified": False,
        "production_activation_authorized": False,
    }


fake_gate.analyze = fake_analyze
with patch.dict(sys.modules, {"hepta_cell_split_perf_gate": fake_gate}):
    spec = importlib.util.spec_from_file_location(
        "local_matrix_capture_under_test", ROOT / "scripts" / "hepta_cell_split_matrix_capture.py"
    )
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)


WORKER_SCRIPT = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path

scope = int(os.environ['HEPTA_CELL_SPLIT_EXPECTED_SCOPE'])
mode = os.environ['HEPTA_CELL_SPLIT_EXPECTED_MODE']
result_path = Path(os.environ['HEPTA_CELL_SPLIT_RESULT_PATH'])
manifest = json.loads(Path(os.environ['HEPTA_TEST_MANIFEST']).read_text())
base = {
    'schema': 'hepta.cell-split.host-measurement.v1',
    'source_sha': manifest['source_sha'],
    'hardware_id': manifest['hardware_id'],
    'model_digest': manifest['model_digest'],
    'workload_digest': manifest['workload_digest'],
    'scopes': scope,
    'mode': mode,
    'measurement_source': 'local_subprocess_test_only',
    'attempted_request_trace_sha256': 'ab' * 32,
    'attempted': 100,
    'completed': 100,
    'elapsed_seconds': 1.0,
    'p50_ms': 1.0,
    'p95_ms': 2.0,
    'p99_ms': 3.0,
    'cpu_seconds': 0.25,
    'rss_peak_bytes': 4096,
    'communication_bytes': 512,
    'native_backend_calls': 4,
    'native_batch_requests': 100,
    'fsync_count': 2,
    'lock_wait_ms': 0.1,
    'recovery_ms': 1.0,
    'failed_requests': 0,
    'negative_transfer_rate': 0.0,
}
if os.environ.get('HEPTA_TEST_PRESEED_NEXT') == '1' and scope == 64 and mode == 'no_split':
    poisoned = dict(base, mode='logical_split')
    result_path.with_name('64-logical_split.json').write_text(json.dumps(poisoned))
result_path.write_text(json.dumps(base, sort_keys=True) + '\n')
'''


class MatrixIntegrationTests(unittest.TestCase):
    def make_run(self, root: Path):
        repo = root / "repo"
        repo.mkdir()
        (repo / "worker.py").write_text(WORKER_SCRIPT)
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
        git("init", "-q")
        git("-c", "user.email=runner@local.invalid", "-c", "user.name=Test", "add", "worker.py")
        git("-c", "user.email=runner@local.invalid", "-c", "user.name=Test", "commit", "-q", "-m", "test-only worker")
        sha = git("rev-parse", "HEAD")
        manifest = {
            "schema": "hepta.cell-split.execution-matrix.v1",
            "source_sha": sha,
            "hardware_id": "fixture-host-only",
            "model_digest": "fixture-model-only",
            "workload_digest": "fixture-workload-only",
            "runs": [
                {"scopes": scope, "mode": mode, "argv": [sys.executable, "worker.py"]}
                for scope in fake_gate.SCOPES
                for mode in fake_gate.MODES
            ],
        }
        manifest_path = root / "manifest-input.json"
        manifest_path.write_text(json.dumps(manifest))
        return repo, manifest, manifest_path

    def test_fresh_result_has_durable_16_run_raw_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, manifest, manifest_path = self.make_run(root)
            output = root / "capture"
            with patch.dict(os.environ, {"HEPTA_TEST_MANIFEST": str(manifest_path)}):
                comparison = runner.execute_matrix(manifest, repo, output, timeout_seconds=20)
            self.assertFalse(comparison["production_activation_authorized"])
            packet = json.loads((output / "measured-matrix.json").read_text())
            self.assertEqual(len(packet["runs"]), 16)
            manifest_raw = (output / "manifest.json").read_bytes()
            self.assertEqual(packet["manifest_sha256"], hashlib.sha256(manifest_raw).hexdigest())
            for row in packet["runs"]:
                self.assertEqual(row["measurement_source"], "local_subprocess_test_only")
                filename = f"{row['scopes']}-{row['mode']}.json"
                self.assertEqual(
                    row["raw_measurement_sha256"],
                    hashlib.sha256((output / filename).read_bytes()).hexdigest(),
                )
                self.assertEqual(len(row["stdout_sha256"]), 64)
                self.assertEqual(len(row["stderr_sha256"]), 64)
                self.assertEqual(len(row["argv_sha256"]), 64)
            self.assertTrue((output / "diagnostic-comparison.json").is_file())

    def test_previous_workload_poisoning_future_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, manifest, manifest_path = self.make_run(root)
            output = root / "capture"
            with patch.dict(os.environ, {
                "HEPTA_TEST_MANIFEST": str(manifest_path),
                "HEPTA_TEST_PRESEED_NEXT": "1",
            }):
                with self.assertRaisesRegex(ValueError, "preexisting measurement"):
                    runner.execute_matrix(manifest, repo, output, timeout_seconds=20)
            self.assertTrue((output / "64-logical_split.json").is_file())
            self.assertFalse((output / "measured-matrix.json").exists())
            self.assertFalse((output / "diagnostic-comparison.json").exists())


if __name__ == "__main__":
    unittest.main()
