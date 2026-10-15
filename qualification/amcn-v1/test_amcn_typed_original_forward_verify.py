"""Original six-Head replay tests: physical math and withheld original audit."""
import os
from pathlib import Path
import unittest

import torch
from amcn_core import Refused, digest
from experiments.shared_stem_cell.execution import Head
from amcn_typed_original_forward_verify_v2 import (
    _head, _tensor_hash, replay_original_head_forwards)


class OriginalForwardReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_independent_gated_math_matches_actual_head_forward(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(43)
            head = Head(384, 2, kind="gated", rank=8).eval()
            x = torch.randn(7, 384)
        weights = {k: v.detach().clone() for k, v in head.state_dict().items()}
        with torch.no_grad():
            for i in range(len(x)):
                reference = float(head(x[i:i + 1]).softmax(-1)[0, 1])
                actual = float(_head(weights, x[i:i + 1]))
                self.assertAlmostEqual(reference, actual, delta=1e-7)

    def test_mutated_head_tensor_alters_actual_answer(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(8)
            head = Head(384, 2, kind="gated", rank=8).eval()
            x = torch.randn(1, 384)
        weights = {k: v.detach().clone() for k, v in head.state_dict().items()}
        before = _head(weights, x)
        weights["base.bias"][1] += 2
        self.assertGreater(abs(before - _head(weights, x)), 0.02)

    def test_tensor_digest_rejects_parameter_mutation(self):
        original = torch.zeros(2, 384, dtype=torch.float32)
        changed = original.clone()
        changed[0, 0] = 0.001
        self.assertNotEqual(_tensor_hash(original), _tensor_hash(changed))
        self.assertEqual(_tensor_hash(original), _tensor_hash(original.clone()))

    def test_absent_original_material_must_not_use_synthetic_fallback(self):
        missing = "/definitely-unavailable/hepta-original-archived-source.zip"
        with self.assertRaises(Refused):
            replay_original_head_forwards(*(missing,) * 10)

    def test_refuse_widened_numerical_tolerance(self):
        missing = "/definitely-unavailable/hepta-original-archived-source.zip"
        with self.assertRaises(Refused):
            replay_original_head_forwards(*(missing,) * 10, tolerance=0.001)

    def test_source_digest_semantics_preserved(self):
        self.assertEqual(digest(["a", "b"]),
                         __import__('hashlib').sha256(b'["a","b"]').hexdigest())

    @unittest.skipUnless(os.getenv("HEPTA_AMCN_ORIGINAL_ROOT"),
                         "Original 376MB artifact not staged on test host; no fake physical replay")
    def test_exact_archived_six_heads_replay_when_original_material_staged(self):
        r = Path(os.environ["HEPTA_AMCN_ORIGINAL_ROOT"])
        base = r / "mini-real-forward-20261014"
        trained = base / "trained-typed-heads"
        receipt = replay_original_head_forwards(
            r / "hepta-original-locomo-hf-archive.zip",
            r / "amcn-locomo-original.json",
            r / "amcn-work/real_mini/model.safetensors",
            r / "amcn-work/real_mini/vocab.txt",
            base / "features-1472.safetensors",
            base / "features-1472-manifest.json",
            trained / "sealed.json",
            trained / "bank",
            trained / "question-level-eval.json",
            r / "locomo-typed-actual-prepare/public.json")
        m = receipt["metrics"]
        self.assertEqual(m["actual_forward_calls"], 3520)
        self.assertEqual(m["original_predictions_verified"], 704)
        self.assertEqual(m["physically_reloaded_head_count"], 6)
        self.assertLess(m["max_abs_probability_error"], 2e-6)
        self.assertFalse(receipt["production_accepted"])
        self.assertFalse(m["hf_model_tokenizer_operator_parity_qualified"])
        self.assertFalse(m["publication_authorized"])


if __name__ == "__main__":
    unittest.main()
