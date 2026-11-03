"""Reader mechanics plus opt-in real MiniLM training/read checks.

Set MEMORY_CELL_BASE to the checked base directory to run the pretrained tests.
The numerical adapter tests remain independent of ONNX/tokenizers and this cache.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
READER = PACKAGE / "read_parameters.py"
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))
sys.path.insert(0, str(PACKAGE))
from memory_cells.model import MemoryCell  # noqa: E402
from v2.adapter import save_cell  # noqa: E402
from v2.encoder import MiniLMEncoder, canonical, sha  # noqa: E402


def call_reader(request_path):
    return subprocess.run(
        [sys.executable, "-I", str(READER), str(request_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )


class ReaderRequestTests(unittest.TestCase):
    def test_unknown_fields_are_rejected_before_model_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_path = Path(tmp) / "request.json"
            for field in ("targets", "source", "history", "samples"):
                request = {
                    "schema": "memory-cell-v2.read.v1",
                    "artifact": "unused",
                    "base_path": "unused",
                    "texts": ["query"],
                    "expected_encoder_digest": "0" * 64,
                    field: [],
                }
                request_path.write_text(json.dumps(request), encoding="utf-8")
                result = call_reader(request_path)
                with self.subTest(field=field):
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(
                        "request allows only", json.loads(result.stderr)["message"]
                    )

    def test_incomplete_artifact_rejected_without_optional_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cell").mkdir()
            (root / "base").mkdir()
            (root / "cell" / "manifest.json").write_text("{}", encoding="utf-8")
            request = {
                "schema": "memory-cell-v2.read.v1",
                "artifact": "cell",
                "base_path": "base",
                "texts": ["query"],
                "expected_encoder_digest": "0" * 64,
            }
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            result = call_reader(request_path)
            self.assertEqual(result.returncode, 2)
            self.assertIn("model file is missing", json.loads(result.stderr)["message"])


@unittest.skipUnless(
    os.environ.get("MEMORY_CELL_BASE"),
    "set MEMORY_CELL_BASE for real pretrained checks",
)
class PretrainedReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.base = Path(os.environ["MEMORY_CELL_BASE"]).resolve(strict=True)
        cls.encoder = MiniLMEncoder(cls.base)
        rng = np.random.default_rng(8001)
        cls.texts = [
            f"Read the development memory for item {int(value):016x}."
            for value in rng.integers(0, 2**63 - 1, size=24)
        ]
        cls.targets = np.random.default_rng(8003).integers(0, 8, size=24)
        cls.features = cls.encoder.encode(cls.texts)
        cls.cell = MemoryCell(384, 24, 8, seed=8001)
        cls.receipt = cls.cell.fit(cls.features, cls.targets, steps=600, lr=0.03)
        cls.manifest = save_cell(
            cls.cell,
            cls.root / "cell",
            cls.encoder.manifest(),
            source_commit="a" * 40,
            support_digest=sha(
                canonical({"texts": cls.texts, "targets": cls.targets.tolist()})
            ),
        )
        cls.request = {
            "schema": "memory-cell-v2.read.v1",
            "artifact": "cell",
            "base_path": str(cls.base),
            "texts": cls.texts,
            "expected_encoder_digest": cls.encoder.digest,
        }
        cls.request_path = cls.root / "request.json"
        cls.request_path.write_bytes(canonical(cls.request))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_fresh_process_reads_real_trained_parameters_and_reports_opened_files(self):
        result = call_reader(self.request_path)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        fresh = json.loads(result.stdout)
        self.assertNotEqual(fresh["pid"], os.getpid())
        self.assertEqual(fresh["predictions"], self.targets.tolist())
        self.assertEqual(
            fresh["predictions"], self.cell.predict(self.features).tolist()
        )
        self.assertEqual(fresh["artifact_digest"], self.manifest["manifest_sha256"])
        self.assertEqual(fresh["encoder_digest"], self.encoder.digest)
        self.assertEqual(fresh["parameter_bytes"], self.cell.parameter_bytes)
        self.assertEqual(fresh["base_bytes"], self.encoder.base_bytes)
        self.assertEqual(
            fresh["opened_artifact_files"], ["manifest.json", "tensors.npz"]
        )
        self.assertEqual(
            fresh["opened_base_files"],
            sorted(["source.json", *self.encoder.source["files"]]),
        )
        self.assertEqual(fresh["scope"], "research")
        self.assertEqual(fresh["confidence_kind"], "raw_softmax_not_calibrated")
        self.assertIn("not-an-OS-sandbox", fresh["audit_scope"])
        self.assertGreater(fresh["load_seconds"], 0)
        self.assertGreater(fresh["read_seconds"], 0)
        self.assertLess(self.receipt["final_loss"], self.receipt["initial_loss"] / 20)

    def test_audit_rejects_an_injected_training_file_read(self):
        forbidden = self.root / "training-source.json"
        forbidden.write_text('{"unavailable_training_payload": true}', encoding="utf-8")
        script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import read_parameters
original = read_parameters.MiniLMEncoder.encode
def injected(self, texts, *args, **kwargs):
    with open(sys.argv[3], encoding='utf-8') as stream:
        stream.read()
    return original(self, texts, *args, **kwargs)
read_parameters.MiniLMEncoder.encode = injected
try:
    read_parameters.read_parameters(sys.argv[2])
except PermissionError as error:
    print(json.dumps({'blocked': True, 'message': str(error)}))
else:
    raise SystemExit('unexpected outside read')
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(PACKAGE),
                str(self.request_path),
                str(forbidden),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(json.loads(result.stdout)["blocked"])
        self.assertIn(
            "outside the pinned adapter/base files",
            json.loads(result.stdout)["message"],
        )


if __name__ == "__main__":
    unittest.main()
