"""Frozen model encodings of only the original public input and current outputs."""

import numpy as np
from PIL import Image
import torch
import hashlib
from pathlib import Path

from .real_predictor import ACTIONS, digest


def _public(value):
    if not isinstance(value, dict) or set(value) != {"text", "image_rgb"}:
        raise ValueError("only public text and RGB pixels are admitted")
    image = value["image_rgb"]
    if (
        not isinstance(value["text"], str)
        or not 1 <= len(value["text"]) <= 4096
        or not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or not 1 <= image.shape[0] * image.shape[1] <= 16000000
    ):
        raise ValueError("invalid bounded public input")


class FrozenSmolEncoder:
    """Frozen actual SmolVLM token/image features; no reference/quality input."""

    def __init__(self, backend):
        self.backend = backend

    def contract_digest(self):
        backend = self.backend.identity()
        return digest(
            {
                "schema": "frozen_smol_public_pooling.v1",
                "implementation_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "model": backend["reviewed_model_pins"]["vlm"],
                "preprocessing": backend["image_preprocessing"],
                "dtype": backend["dtype"],
                "device": backend["device"],
                "versions": backend["versions"],
            }
        )

    @torch.no_grad()
    def __call__(self, public, current):
        _public(public)
        if set(current) != {"plan", "text", "image_rgb", "critique", "history"}:
            raise ValueError(
                "current observation may contain only actual public outputs/history"
            )
        self.backend._activate("vlm")
        model, processor = self.backend.model, self.backend.processor
        prompt = (
            public["text"]
            + "\nCurrent plan: "
            + current["plan"]
            + "\nCurrent text: "
            + (current["text"] or "")
            + "\nPublic critique: "
            + current["critique"]
        )
        if len(prompt) > 8000:
            raise ValueError("public encoder prompt exceeds its declared bound")
        images = [Image.fromarray(public["image_rgb"])]
        if current["image_rgb"] is not None:
            images.append(Image.fromarray(current["image_rgb"]))
        visual, text = [], None
        for picture in images:
            picture.thumbnail((512, 512))
            rendered = processor.apply_chat_template(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image"},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                add_generation_prompt=True,
                tokenize=False,
            )
            inputs = processor(text=rendered, images=[picture], return_tensors="pt")
            anchor = next(model.parameters())
            inputs = {
                key: value.to(
                    device=anchor.device,
                    dtype=anchor.dtype if value.is_floating_point() else value.dtype,
                )
                for key, value in inputs.items()
            }
            embedded = model.get_input_embeddings()(inputs["input_ids"])
            mask = (inputs["input_ids"] != model.config.image_token_id) & inputs[
                "attention_mask"
            ].bool()
            if not bool(mask.any()):
                raise ValueError("empty public text encoding")
            text = embedded[mask].float().mean(0)
            pixels = model.model.get_image_features(
                inputs["pixel_values"], inputs.get("pixel_attention_mask")
            )
            visual.append(pixels.reshape(-1, pixels.shape[-1]).float().mean(0))
        current_image = visual[1] if len(visual) == 2 else torch.zeros_like(visual[0])
        history = [
            sum(action == name for action in current["history"]) / 32
            for name in ACTIONS
        ]
        values = torch.cat((text, visual[0], current_image)).cpu().tolist()
        return tuple(values + history)
