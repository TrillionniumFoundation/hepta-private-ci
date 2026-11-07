"""Autograd qualification only; fixture tensors are not natural-task evidence."""

import importlib.util
import unittest

from .test_state import metadata


@unittest.skipUnless(importlib.util.find_spec("torch") is not None, "Torch unavailable; autograd execution remains unqualified")
class TorchFeatureTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.shared = torch.tensor([[0.2, 0.3]], dtype=torch.float64, requires_grad=True)
        self.text = torch.tensor([[0.2, 0.5, 0.7]], dtype=torch.float64, requires_grad=True)
        self.image = torch.tensor([[0.4, 0.8, 0.2, 0.3]], dtype=torch.float64, requires_grad=True)
        self.encoders = {"text": torch.nn.Linear(3, 2, bias=False, dtype=torch.float64),
                         "image": torch.nn.Linear(4, 2, bias=False, dtype=torch.float64)}
        with torch.no_grad():
            self.encoders["text"].weight.fill_(0.25)
            self.encoders["image"].weight.fill_(0.4)

    def evaluate(self, text):
        from ndu_semantic_state.torch_adapter import encode_public_outputs_torch
        features, state, binding = encode_public_outputs_torch(self.shared,
            {"text": text, "image": self.image}, self.encoders, metadata())
        return features.tanh().square().sum(), features, state, binding

    def test_task_loss_reaches_public_outputs_encoders_and_shared_content(self):
        loss, features, state, _ = self.evaluate(self.text)
        loss.backward()
        import numpy as np
        np.testing.assert_allclose(features.detach().numpy(), state.features(), rtol=1e-14, atol=1e-14)
        for tensor in (self.shared, self.text, self.image,
                       self.encoders["text"].weight, self.encoders["image"].weight):
            self.assertIsNotNone(tensor.grad)
            self.assertTrue(self.torch.isfinite(tensor.grad).all().item())
            self.assertGreater(tensor.grad.abs().sum().item(), 0)

    def test_independent_centered_difference_matches_content_gradient(self):
        loss, _, _, _ = self.evaluate(self.text)
        loss.backward()
        analytic = self.text.grad[0, 1].item()
        with self.torch.no_grad():
            plus, minus = self.text.clone(), self.text.clone()
            plus[0, 1] += 1e-6; minus[0, 1] -= 1e-6
            numeric = (self.evaluate(plus)[0].item() - self.evaluate(minus)[0].item()) / 2e-6
        self.assertAlmostEqual(analytic, numeric, places=8)

    def test_frozen_content_and_extra_target_rejection(self):
        from ndu_semantic_state.torch_adapter import encode_public_outputs_torch, features_torch
        from ndu_semantic_state.state import from_public_encodings, actor_binding
        for encoder in self.encoders.values():
            encoder.requires_grad_(False)
        features, _, _ = encode_public_outputs_torch(self.shared.detach(),
            {"text": self.text.detach(), "image": self.image.detach()}, self.encoders, metadata())
        self.assertFalse(features.requires_grad)
        with self.assertRaises(ValueError):
            encode_public_outputs_torch(self.shared,
                {"text": self.text, "image": self.image, "targets": self.text}, self.encoders, metadata())
        snapshot = from_public_encodings([[0.2, 0.3]], {"text": [[1.0, 2.0]], "image": [[3.0, 4.0]]}, metadata())
        with self.assertRaises(ValueError):
            features_torch(self.shared, {"text": self.shared, "image": self.shared}, snapshot, actor_binding(snapshot))


if __name__ == "__main__":
    unittest.main()
