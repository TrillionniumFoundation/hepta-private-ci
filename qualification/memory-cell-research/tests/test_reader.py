"""Fresh-process evidence for parameter-only reads and rejected request channels."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from memory_cells.encoding import FrozenEncoder
from memory_cells.model import MemoryCell


READER = Path(__file__).resolve().parents[1] / "read_parameters.py"


class ParameterReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.encoder = FrozenEncoder(64, 7)
        self.keys = [f"record:xt-{index:03d}" for index in range(24)]
        self.targets = np.random.default_rng(903).integers(0, 8, len(self.keys))
        self.cell = MemoryCell(64, 12, 8, seed=19)
        self.cell.fit(self.encoder.encode(self.keys), self.targets, steps=220, lr=0.04)
        self.artifact = self.root / "artifact"
        self.manifest = self.cell.save(
            self.artifact, encoder_manifest=self.encoder.manifest()
        )

    def run_reader(self, changes=None):
        request = {
            "schema": "memory-cell-read.v1",
            "artifact": str(self.artifact),
            "keys": self.keys,
            "expected_encoder_digest": self.encoder.digest,
        }
        request.update({} if changes is None else changes)
        path = self.root / "request.json"
        path.write_text(json.dumps(request))
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        return subprocess.run(
            [sys.executable, "-I", str(READER), str(path)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_fresh_process_recovers_random_associations_without_training_files(self):
        result = self.run_reader()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertNotEqual(receipt["pid"], os.getpid())
        np.testing.assert_array_equal(receipt["predictions"], self.targets)
        np.testing.assert_array_equal(
            receipt["predictions"], self.cell.predict(self.encoder.encode(self.keys))
        )
        self.assertEqual(
            receipt["opened_artifact_files"], ["manifest.json", "tensors.npz"]
        )
        self.assertEqual(receipt["artifact_digest"], self.manifest["manifest_sha256"])
        self.assertEqual(receipt["parameter_bytes"], self.cell.parameter_bytes)
        self.assertEqual(receipt["confidence_kind"], "raw_softmax_not_calibrated")
        self.assertGreater(receipt["load_seconds"], 0)
        self.assertGreater(receipt["read_seconds"], 0)

    def test_rejects_targets_as_an_unknown_request_channel(self):
        result = self.run_reader({"targets": self.targets.tolist()})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("only schema", json.loads(result.stderr)["message"])

    def test_rejects_incomplete_artifact(self):
        (self.artifact / "tensors.npz").unlink()
        result = self.run_reader()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("present regular files", json.loads(result.stderr)["message"])

    def test_rejects_wrong_encoder_identity(self):
        result = self.run_reader({"expected_encoder_digest": "0" * 64})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("encoder digest", json.loads(result.stderr)["message"])

    def test_audit_rejects_a_deliberate_extra_training_file_read(self):
        request = {
            "schema": "memory-cell-read.v1",
            "artifact": str(self.artifact),
            "keys": self.keys,
            "expected_encoder_digest": self.encoder.digest,
        }
        request_path = self.root / "audit_request.json"
        request_path.write_text(json.dumps(request))
        forbidden = self.root / "training_targets.json"
        forbidden.write_text(json.dumps(self.targets.tolist()))
        program = """
import sys
sys.path.insert(0, sys.argv[1])
import read_parameters
def injected_load(*args, **kwargs):
    with open(sys.argv[3]) as source:
        return source.read()
read_parameters.MemoryCell.load = injected_load
try:
    read_parameters.read_parameters(sys.argv[2])
except PermissionError:
    print('extra read rejected')
else:
    raise SystemExit('audit unexpectedly allowed a training file')
"""
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                program,
                str(READER.parent),
                str(request_path),
                str(forbidden),
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "extra read rejected")


if __name__ == "__main__":
    unittest.main()
