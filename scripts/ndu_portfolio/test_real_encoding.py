"""Test the frozen encoder API with a tiny explicit fixture, not a pretrained model."""

from types import SimpleNamespace
import unittest

import numpy as np
import torch
from torch import nn

from .real_encoding import FrozenSmolEncoder, _public


class ProcessorFixture:
    def apply_chat_template(self, messages, **kwargs):
        return messages[0]["content"][1]["text"]

    def __call__(self, text, images, **kwargs):
        return {
            "input_ids": torch.tensor([[2, 3]]),
            "attention_mask": torch.ones(1, 2),
            "pixel_values": torch.tensor(np.asarray(images[0]).copy())
            .float()
            .mean((0, 1))[None, None]
            / 255,
        }


class ModelFixture(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(4, 3)
        self.config = SimpleNamespace(image_token_id=1)
        self.model = SimpleNamespace(get_image_features=lambda pixels, mask: pixels)

    def get_input_embeddings(self):
        return self.embedding


class EncodingContracts(unittest.TestCase):
    def test_original_pixels_and_current_pixels_remain_distinct(self):
        activated = []
        backend = SimpleNamespace(
            model=ModelFixture(),
            processor=ProcessorFixture(),
            _activate=activated.append,
        )
        encoder = FrozenSmolEncoder(backend)
        original = np.zeros((8, 8, 3), dtype=np.uint8)
        current = np.full_like(original, 255)
        features = encoder(
            {"text": "public request", "image_rgb": original},
            {
                "plan": "public plan",
                "text": "current output",
                "image_rgb": current,
                "critique": "public critique",
                "history": ("text",),
            },
        )
        self.assertEqual(features[3:6], (0.0, 0.0, 0.0))
        self.assertEqual(features[6:9], (1.0, 1.0, 1.0))
        self.assertEqual(activated, ["vlm"])
        self.assertTrue(np.all(original == 0))
        self.assertTrue(np.all(current == 255))

    def test_hidden_fields_fail_before_model_activation(self):
        public = {
            "text": "public request",
            "image_rgb": np.zeros((8, 8, 3), dtype=np.uint8),
        }
        with self.assertRaises(ValueError):
            _public({**public, "target": "hidden"})
        encoder = FrozenSmolEncoder(None)
        with self.assertRaises(ValueError):
            encoder(
                public,
                {
                    "plan": "public",
                    "text": None,
                    "image_rgb": None,
                    "critique": "",
                    "history": (),
                    "future": "hidden",
                },
            )


if __name__ == "__main__":
    unittest.main()
