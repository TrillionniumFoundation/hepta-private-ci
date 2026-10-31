"""Boundary tests for actual input tensors and learned ingress, no task claims."""

import unittest

import torch

from ...v7.model import SlotPortfolio
from .network import VideoInput, ingress_state


class IngressTests(unittest.TestCase):
    def test_actual_video_order_and_input_values_affect_predictions(self):
        torch.manual_seed(1729)
        torch.set_num_threads(1)
        model = VideoInput().eval()
        pixels = torch.rand(2, 20, 1, 28, 28)
        prediction = model(pixels)
        self.assertEqual(tuple(prediction.shape), (2, 2, 10))
        self.assertFalse(torch.equal(prediction, model(pixels.flip(1))))
        for invalid in (pixels[:, :19], pixels + 1, pixels * float("nan")):
            with self.assertRaises(ValueError):
                model(invalid)

    def test_observed_neural_posteriors_enter_the_shared_content_state(self):
        torch.manual_seed(29)
        model = SlotPortfolio()
        probabilities = torch.nn.functional.one_hot(torch.tensor([[1, 8], [2, 9]]), 10).float()
        state = ingress_state(model, probabilities)
        self.assertEqual(tuple(state.h.shape), (2, 96))
        self.assertFalse(torch.equal(state.h[0], state.h[1]))
        self.assertEqual(state.source_digest, "")
        with self.assertRaises(ValueError):
            ingress_state(model, probabilities * 2)


if __name__ == "__main__":
    unittest.main()
