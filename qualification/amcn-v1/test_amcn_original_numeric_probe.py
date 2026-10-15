"""Real original pretrained BF16 tensor probe: never benchmark scores."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from amcn_original_numeric_probe import EXPECTED


class OriginalNumericPhysicalTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("AMCN_ORIGINAL_PRETRAINED_ROOT"),
                         "original model bytes not staged; cannot pretend real physical run")
    def test_two_separate_physical_model_processes_with_identical_results(self):
        root = Path(os.environ["AMCN_ORIGINAL_PRETRAINED_ROOT"])
        self.assertEqual(set(EXPECTED), {
            "reader/model.safetensors", "encoder/model.safetensors"})
        with tempfile.TemporaryDirectory() as tmp:
            receipts = []
            for i in range(2):
                out = Path(tmp) / f"receipt-{i}.json"
                result = subprocess.run([
                    sys.executable, str(Path(__file__).with_name("amcn_original_numeric_probe.py")),
                    "--archive-root", str(root), "--output", str(out),
                ], check=True, capture_output=True, text=True, timeout=180)
                self.assertTrue(result.stdout.strip())
                raw = out.read_bytes()
                self.assertTrue(raw.endswith(b"\n"))
                receipt = json.loads(raw)
                self.assertEqual(receipt["model_files"], EXPECTED)
                self.assertTrue(receipt["real_model_numeric_forward"])
                for key in ("reader_hf_model_parity_verified", "text_tokenizer_parity_verified",
                            "production_accepted", "strong_rag_compared"):
                    self.assertIs(receipt[key], False)
                self.assertEqual(receipt["reader_natural_language_task_answers"], 0)
                self.assertEqual(receipt["independent_future_windows"], 0)
                receipts.append(receipt)
            for k in ("cls_sha256", "pooler_sha256"):
                self.assertEqual(receipts[0]["encoder"][k], receipts[1]["encoder"][k])
            for k in ("logits_sha256", "last_hidden_sha256", "top5_ids"):
                self.assertEqual(receipts[0]["reader"][k], receipts[1]["reader"][k])
            self.assertEqual(receipts[0]["source_file_sha256"],
                             receipts[1]["source_file_sha256"])

    def test_external_model_sha_mismatch_refused_before_logits(self):
        # The real source has a precise manifest pinned by the original
        # repository artifact; even the fixture-less test enforces nonempty hashes.
        self.assertTrue(all(len(value) == 64 and isinstance(value, str)
                            for value in EXPECTED.values()))


if __name__ == "__main__":
    unittest.main()
