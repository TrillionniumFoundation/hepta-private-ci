"""Development-only checks: gradients, adapter intervention, and identity binding."""

import hashlib
import json
from collections import UserDict
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from diagnostics import geometry, solve_affine
from models import FeatureMemory, TransformerAdapter, fit, grouped_loss, load, predict, save, verify_base


class MemoryModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_affine_positive_control_distinguishes_rank_and_optimization(self):
        rng = np.random.default_rng(99411001)
        x, target = rng.normal(size=(20, 28)), rng.normal(size=(20, 5))
        arrays = solve_affine(x, target)
        np.testing.assert_allclose(x @ arrays["head.weight"].T + arrays["head.bias"], target, atol=1e-10)
        self.assertEqual(geometry(x)["with_bias"]["rank"], 20)
        x[1] = x[0]
        arrays = solve_affine(x, target)
        self.assertGreater(np.linalg.norm(x @ arrays["head.weight"].T + arrays["head.bias"] - target), .01)
        self.assertEqual(geometry(x)["duplicate_rows"], 1)

    def test_torch_group_loss_matches_independent_numpy_gradient(self):
        from cells import objective
        rng = np.random.default_rng(99411002)
        raw = rng.normal(size=(7, 7)).astype(np.float32)
        target = np.c_[rng.integers(0, 2, size=(7, 4)), np.eye(3)[rng.integers(0, 3, size=7)]].astype(np.float32)
        outputs = (("binary", 4), ("multiclass", 3))
        expected_loss, expected_gradient = objective(raw, target, outputs)
        variable = torch.tensor(raw, requires_grad=True)
        loss = grouped_loss(variable, torch.tensor(target), outputs)
        loss.backward()
        self.assertAlmostEqual(float(loss.detach()), expected_loss, places=6)
        np.testing.assert_allclose(variable.grad.numpy(), expected_gradient, atol=1e-7)

    def test_feature_learning_and_checkpoint_corruption(self):
        rng = np.random.default_rng(99411003)
        x = np.eye(8, dtype=np.float32)
        target = rng.integers(0, 2, (8, 4)).astype(np.float32)
        schedule = np.tile(np.arange(8), (100, 1))
        for kind in ("linear", "mlp", "associative"):
            model = FeatureMemory(kind, 8, 4, seed=99411003, hidden=16, slots=8)
            receipt = fit(model, x, target, (("binary", 4),), schedule, lr=.03)
            self.assertNotEqual(receipt["initial_parameter_sha256"], receipt["final_parameter_sha256"])
            self.assertLess(receipt["final_minibatch_loss"], receipt["initial_minibatch_loss"])
            with tempfile.TemporaryDirectory() as root:
                path = Path(root) / "checkpoint"
                save(model, path)
                np.testing.assert_array_equal(predict(model, x), predict(load(path), x))
                with (path / "weights.pt").open("ab") as handle:
                    handle.write(b"corruption")
                with self.assertRaisesRegex(ValueError, "corruption"):
                    load(path)

    def test_internal_transformer_adapter_receives_gradient_and_changes_behavior(self):
        from transformers import BertConfig, BertModel
        with torch.random.fork_rng():
            torch.manual_seed(99411004)
            encoder = BertModel(BertConfig(vocab_size=32, hidden_size=24, num_hidden_layers=2,
                num_attention_heads=4, intermediate_size=32, hidden_dropout_prob=0,
                attention_probs_dropout_prob=0, max_position_embeddings=32))
        model = TransformerAdapter("development-only-random-bert", 4, rank=2, seed=99411004,
                                   encoder=encoder)
        frozen = {k: p.detach().clone() for k, p in model.named_parameters() if not p.requires_grad}
        inputs = {"input_ids": torch.tensor([[1, 2, 3, 4], [1, 5, 6, 4], [1, 7, 8, 4], [1, 9, 10, 4]]),
                  "attention_mask": torch.ones((4, 4), dtype=torch.long)}
        y = np.eye(4, dtype=np.float32)
        receipt = fit(model, inputs, y, (("multiclass", 4),), np.tile(np.arange(4), (8, 1)), lr=.02)
        adapter_names = [k for k in receipt["max_gradient_norm"] if k.endswith((".A", ".B"))]
        self.assertTrue(adapter_names)
        self.assertTrue(all(receipt["max_gradient_norm"][k] > 0 for k in adapter_names))
        self.assertTrue(all(receipt["parameter_change_norm"][k] > 0 for k in adapter_names))
        for name, parameter in model.named_parameters():
            if name in frozen:
                torch.testing.assert_close(parameter, frozen[name], rtol=0, atol=0)
        trained = predict(model, inputs)
        with model.disabled_adapters():
            ablated = predict(model, inputs)
        self.assertGreater(float(np.abs(trained - ablated).max()), 1e-6)
        np.testing.assert_array_equal(trained, predict(model, inputs))
        # HF BatchEncoding is mapping-like, not a dict; text batches must still slice by row.
        model.tokenizer = lambda texts, **kwargs: UserDict(inputs)
        np.testing.assert_array_equal(trained, predict(model, ["one", "two", "three", "four"]))

    def test_base_manifest_rejects_changed_or_unlisted_assets(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            payload = b'{"model_type":"bert"}'
            (root / "config.json").write_bytes(payload)
            manifest = dict(schema="hepta.memory.v11.base-model.v1", files=[dict(path="config.json",
                bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())])
            (root / "MODEL_IDENTITY.json").write_text(json.dumps(manifest))
            identity = verify_base(root)
            self.assertEqual(identity, verify_base(root, identity))
            (root / "added_tokens.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "omits"):
                verify_base(root)
            (root / "added_tokens.json").unlink()
            (root / "config.json").write_bytes(payload + b" ")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify_base(root)


if __name__ == "__main__":
    unittest.main()
