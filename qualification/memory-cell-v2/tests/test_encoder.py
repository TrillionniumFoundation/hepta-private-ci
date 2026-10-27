"""Real native-batch contract checks; opt in with the checked MiniLM base."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from v2.encoder import MiniLMEncoder, canonical, sha


PACKAGE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    os.environ.get("MEMORY_CELL_BASE"), "set MEMORY_CELL_BASE for real encoder checks"
)
class EncoderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(os.environ["MEMORY_CELL_BASE"]).resolve(strict=True)
        cls.encoder = MiniLMEncoder(cls.base)
        cls.texts = [
            f"Memory type semantic. Key config.field:sample_{index}. "
            + "A deliberately varied length address description. " * (index % 11)
            + f"Revision {index % 3 + 1}."
            for index in range(37)
        ]

    def test_features_are_identical_across_batch_sizes_order_and_external_partition(
        self,
    ):
        one = self.encoder.encode(self.texts, batch_size=1)
        many = self.encoder.encode(self.texts, batch_size=32)
        reverse = self.encoder.encode(list(reversed(self.texts)), batch_size=128)[::-1]
        partitioned = np.concatenate(
            [
                self.encoder.encode(self.texts[:5]),
                self.encoder.encode(self.texts[5:19]),
                self.encoder.encode(self.texts[19:]),
            ]
        )
        np.testing.assert_array_equal(one, many)
        np.testing.assert_array_equal(one, reverse)
        np.testing.assert_array_equal(one, partitioned)
        self.assertEqual(self.encoder.manifest()["native_batch_size"], 1)
        self.assertIn(
            "per-text-tokenization", self.encoder.manifest()["inference_batch_contract"]
        )

    def test_new_process_has_identical_feature_bytes_and_encoder_identity(self):
        features = self.encoder.encode(self.texts, batch_size=1)
        script = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
from v2.encoder import MiniLMEncoder, sha
encoder = MiniLMEncoder(sys.argv[2])
features = encoder.encode(json.loads(sys.argv[3]), batch_size=32)
print(json.dumps({'pid': os.getpid(), 'digest': encoder.digest,
                  'shape': list(features.shape), 'features_sha256': sha(features.astype('<f8').tobytes())}))
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(PACKAGE),
                str(self.base),
                json.dumps(self.texts),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        actual = json.loads(result.stdout)
        self.assertNotEqual(actual["pid"], os.getpid())
        self.assertEqual(actual["digest"], self.encoder.digest)
        self.assertEqual(actual["shape"], list(features.shape))
        self.assertEqual(
            actual["features_sha256"], sha(features.astype("<f8").tobytes())
        )

    def test_file_size_binding_is_checked_before_reading_the_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {
                "schema": "memory-cell-v2.pretrained-source.v1",
                "dimension": 384,
                "base_is_frozen": True,
                "model_file": "model.onnx",
                "files": {
                    "tokenizer.json": {"bytes": 1, "sha256": "0" * 64},
                    "model.onnx": {"bytes": 1, "sha256": "0" * 64},
                },
            }
            (root / "source.json").write_bytes(canonical(source))
            (root / "tokenizer.json").write_bytes(b"larger-than-declared")
            (root / "model.onnx").write_bytes(b"larger-than-declared")
            original = Path.read_bytes
            reads = []

            def tracked(path):
                reads.append(path.name)
                if path.name != "source.json":
                    raise AssertionError(
                        "payload was read before its size binding was checked"
                    )
                return original(path)

            with (
                patch.object(Path, "read_bytes", tracked),
                self.assertRaisesRegex(ValueError, "size differs"),
            ):
                MiniLMEncoder(root)
            self.assertEqual(reads, ["source.json"])


if __name__ == "__main__":
    unittest.main()
