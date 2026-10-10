"""Golden Python <-> native Rust Q24 encoding without model fetching."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from native_bridge import (
    Q24, round_q48, tensor_digest, bundle_digest, build_candidate,
    native_logits, write_candidate,
)


class Q24WireTests(unittest.TestCase):
    def test_golden_head_and_bundle_hashes_match_native_rust(self):
        tensors = ([Q24, 0, 0, Q24], [], [], [0, 0], [0, 0], [Q24, Q24])
        digest = tensor_digest(2, 2, tensors)
        self.assertEqual(
            digest,
            "3b7962a1f859f4e3a2594c37a3d3b99e6c6c6813102947f9ab3e68aa0cb22e82",
        )
        self.assertEqual(
            bundle_digest("a" * 64, digest),
            "277d9ebc5a6066bcf29e846081cd771578b05e570fd3dbad8785cc3ce05162df",
        )

    def test_q24_round_to_even_and_out_of_range(self):
        self.assertEqual(round_q48(Q24 // 2), 0)
        self.assertEqual(round_q48(3 * Q24 // 2), 2)
        self.assertEqual(round_q48(-3 * Q24 // 2), -2)
        with self.assertRaises(ValueError):
            round_q48(9 * Q24 * Q24)


@unittest.skipUnless(importlib.util.find_spec("torch") is not None, "torch optional")
class Q24TorchTests(unittest.TestCase):
    def test_exact_affine_logits_and_no_overwrite(self):
        import torch
        head = torch.nn.Linear(2, 2)
        with torch.no_grad():
            head.weight[:] = torch.tensor([[1.0, 0.0], [0.0, -0.5]])
            head.bias[:] = torch.tensor([0.25, 0.0])
        examples = [torch.tensor([0.5, 0.25]), torch.tensor([-0.2, 0.1])]
        artifact = build_candidate(torch, head, "linear", "a" * 64, examples)
        self.assertEqual(artifact["prediction_weights_q24"], [])
        self.assertEqual(artifact["gate_weights_q24"], [])
        self.assertEqual(artifact["native_stored_coefficients"], 10)
        self.assertEqual(native_logits(artifact, [0.5, 0.25]), [0.75, -0.125])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td, "head.q24.json")
            self.assertEqual(len(write_candidate(path, artifact)), 64)
            self.assertFalse(json.loads(path.read_text())["production_authorized"])
            with self.assertRaises(FileExistsError):
                write_candidate(path, artifact)

    def test_film_rank_affine_and_unsupported_profiles(self):
        import torch
        from model_runner import build_head
        film, _ = build_head(torch, 3, 2, "film", 2048)
        rank, _ = build_head(torch, 4, 2, "rank8", 2048)
        self.assertEqual(build_candidate(
            torch, film, "film", "b" * 64,
            [torch.zeros(3), torch.tensor([0.1, -0.2, 0.3])]
        )["calibration_argmax_mismatch_count"], 0)
        self.assertEqual(build_candidate(
            torch, rank, "rank8", "c" * 64,
            [torch.zeros(4), torch.tensor([0.1, -0.2, 0.3, -0.1])]
        )["output_width"], 2)
        with self.assertRaisesRegex(ValueError, "projection required"):
            build_candidate(torch, torch.nn.Linear(768, 2), "linear", "d" * 64,
                            [torch.zeros(768)])
        with self.assertRaisesRegex(ValueError, "nonaffine"):
            build_candidate(torch, film, "mlp", "e" * 64, [torch.zeros(3)])
        with self.assertRaisesRegex(ValueError, "representable"):
            build_candidate(torch, torch.nn.Linear(2, 2), "linear", "f" * 64,
                            [torch.tensor([9.0, 0.0])])


if __name__ == "__main__":
    unittest.main()
