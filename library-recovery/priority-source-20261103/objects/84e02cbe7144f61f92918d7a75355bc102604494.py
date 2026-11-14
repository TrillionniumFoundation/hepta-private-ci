import json
import tempfile
import unittest
from pathlib import Path

from native_bridge import (
    Q24,
    _native_logits,
    _round_q48,
    build_q24_head_candidate,
    write_q24_head_candidate,
)


class NativeQ24BridgeTests(unittest.TestCase):
    def setUp(self):
        try:
            import torch
        except ImportError:
            self.skipTest('torch not installed; native bridge requires torch')
        self.torch = torch

    def test_linear_export_pins_exact_zero_tensors_and_parity(self):
        torch = self.torch
        head = torch.nn.Linear(2, 2)
        with torch.no_grad():
            head.weight[:] = torch.tensor([[1., 0.], [0., -0.5]])
            head.bias[:] = torch.tensor([0.25, 0.0])
        samples = [torch.tensor([0.5, 0.25]), torch.tensor([-0.2, 0.1])]
        art = build_q24_head_candidate(torch, head, 'linear', 'a' * 64, samples)
        self.assertEqual((art['input_width'], art['output_width']), (2, 2))
        self.assertEqual(art['prediction_weights_q24'], [])
        self.assertEqual(art['gate_weights_q24'], [])
        self.assertEqual(art['gate_bias_q24'], [Q24, Q24])
        self.assertEqual(art['native_stored_coefficients'], 10)
        self.assertEqual(_native_logits(art, [0.5, 0.25]), [0.75, -0.125])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'head.q24.json'
            output_digest = write_q24_head_candidate(path, art)
            self.assertEqual(json.loads(path.read_text())['head_digest'], art['head_digest'])
            self.assertEqual(len(output_digest), 64)
            with self.assertRaises(FileExistsError):
                write_q24_head_candidate(path, art)

    def test_film_affine_folds_without_changed_predictions(self):
        torch = self.torch
        from model_runner import build_head
        head, _ = build_head(torch, 3, 2, 'film', 2048)
        with torch.no_grad():
            head.gamma[:] = torch.tensor([1.1, 0.7, 0.9])
            head.beta[:] = torch.tensor([0.1, 0.0, -0.1])
        features = [torch.tensor([0.1, 0.25, -0.5]), torch.tensor([0.4, -0.2, 0.1])]
        art = build_q24_head_candidate(torch, head, 'film', 'b' * 64, features)
        self.assertEqual(art['calibration_argmax_mismatch_count'], 0)

    def test_rank8_can_be_folded_to_affine_with_capacity_gate(self):
        torch = self.torch
        from model_runner import build_head
        head, _ = build_head(torch, 4, 2, 'rank8', 2048)
        features = [torch.rand(4) * 0.5, torch.zeros(4)]
        art = build_q24_head_candidate(torch, head, 'rank8', 'c' * 64, features)
        self.assertEqual(art['output_width'], 2)
        self.assertEqual(art['native_stored_coefficients'], 14)

    def test_refuses_overwide_embedding_without_projection(self):
        torch = self.torch
        head = torch.nn.Linear(768, 2)
        with self.assertRaisesRegex(ValueError, 'projection required'):
            build_q24_head_candidate(torch, head, 'linear', 'd' * 64, [torch.zeros(768)])

    def test_refuses_feature_overflow_and_unregistered_nonlinear_head(self):
        torch = self.torch
        head = torch.nn.Linear(2, 2)
        with self.assertRaisesRegex(ValueError, 'representable'):
            build_q24_head_candidate(torch, head, 'linear', 'e' * 64, [torch.tensor([9.0, 0.0])])
        with self.assertRaisesRegex(ValueError, 'nonaffine'):
            build_q24_head_candidate(torch, head, 'mlp', 'e' * 64, [torch.zeros(2)])

    def test_ties_to_even_and_out_of_range_rejected(self):
        self.assertEqual(_round_q48(Q24 // 2), 0)
        self.assertEqual(_round_q48(3 * Q24 // 2), 2)
        self.assertEqual(_round_q48(-3 * Q24 // 2), -2)
        with self.assertRaises(ValueError):
            _round_q48(9 * Q24 * Q24)


if __name__ == '__main__':
    unittest.main()
