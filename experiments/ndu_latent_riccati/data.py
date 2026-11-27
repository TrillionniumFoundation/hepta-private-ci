"""Continuous synthetic facts rendered through four complementary raw modalities.

Coordinates are fixed observable task units, not learned latent variance. Styles
are equally lawful and independent of facts; these are tones, not natural speech.
"""

import math

import torch
import torch.nn.functional as F


MODALITIES = ("text", "audio", "image", "video")
FACT_NAMES = ("x", "y", "vx", "vy", "color", "frequency")
SHAPES = {"text": (6, 16), "audio": (64,), "image": (3, 16, 16),
          "video": (4, 3, 16, 16)}
BIN_CENTERS = torch.linspace(-0.75 + 0.75 / 16, 0.75 - 0.75 / 16, 16)


def render(facts, style):
    """Render target tensors from six facts and a signed style coordinate."""
    dtype, device = facts.dtype, facts.device
    style = style.reshape(-1, 1)
    bins = ((facts + 0.75) / 1.5 * 16).long().clamp(0, 15)
    text = F.one_hot(bins, 16).to(dtype)
    time = torch.arange(64, dtype=dtype, device=device) / 64
    frequency = 5 + 2.5 * facts[:, 5:6]
    audio = 0.8 * torch.sin(2 * math.pi * frequency * time + 0.45 * style)
    grid = torch.linspace(0, 1, 16, dtype=dtype, device=device)
    yy, xx = torch.meshgrid(grid, grid, indexing="ij")
    color = torch.stack((0.35 + 0.20 * facts[:, 4],
                         0.35 - 0.20 * facts[:, 4],
                         torch.full_like(facts[:, 4], 0.30)), dim=1)
    sigma = (0.08 + 0.015 * style).reshape(-1, 1, 1)

    def frame(t):
        cx = (0.5 + 0.24 * facts[:, 0] + 0.10 * t * facts[:, 2])[:, None, None]
        cy = (0.5 + 0.24 * facts[:, 1] + 0.10 * t * facts[:, 3])[:, None, None]
        blob = torch.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
        return color[:, :, None, None] * blob[:, None]

    return {"text": text, "audio": audio, "image": frame(0),
            "video": torch.stack([frame(t) for t in (-1, -1/3, 1/3, 1)], dim=1),
            "style_index": (style[:, 0] > 0).long()}


def make_worlds(n, seed, scenario="iid"):
    """Return facts, style, raw inputs/masks, and targets in disjoint namespaces.

    Policies receive only ``inputs`` and ``masks``. Shared-corruption truth and
    the sampled target style must never enter an inference controller.
    """
    if scenario not in ("iid", "ood_missing", "ood_correlated"):
        raise ValueError(f"Unknown scenario: {scenario}")
    rng = torch.Generator().manual_seed(int(seed))
    facts = 1.5 * torch.rand(n, 6, generator=rng) - 0.75
    style = 2 * torch.randint(2, (n, 1), generator=rng).float() - 1
    observed_facts = facts.clone()
    if scenario == "ood_correlated":
        sign = 2 * torch.randint(2, (n, 1), generator=rng).float() - 1
        observed_facts = (facts + sign * torch.tensor(
            [0.22, -0.18, 0.15, -0.15, 0.20, 0.18])).clamp(-0.75, 0.75)
    input_style = 2 * torch.randint(2, (n, 1), generator=rng).float() - 1
    inputs = {k: v for k, v in render(observed_facts, input_style).items()
              if k in MODALITIES}
    inputs["text"][:, :4] = 0  # Text only discloses color and frequency bins.
    for modality in ("audio", "image", "video"):
        noise = 0.020 if modality == "audio" else 0.004
        inputs[modality] = inputs[modality] + noise * torch.randn(
            inputs[modality].shape, generator=rng)
    masks = torch.ones(n, 4)
    if scenario == "ood_missing":
        missing = torch.randint(4, (n,), generator=rng)
        masks[torch.arange(n), missing] = 0
        for j, modality in enumerate(MODALITIES):
            inputs[modality] *= masks[:, j].reshape(n, *([1] * len(SHAPES[modality])))
    return {"facts": facts, "style": style, "inputs": inputs, "masks": masks,
            "targets": render(facts, style)}


def public_inputs(worlds):
    """Strictly expose observed tensors, never supervised target fields."""
    return {"inputs": worlds["inputs"], "masks": worlds["masks"]}


def subset(worlds, indices):
    """Index the nested tensor structure without changing its meaning."""
    return {k: ({m: x[indices] for m, x in v.items()} if isinstance(v, dict)
                else v[indices]) for k, v in worlds.items()}


def text_description(bins, style_index):
    """Readable serialization of the generated structured numeric text."""
    fields = [f"{name}={float(BIN_CENTERS[int(b)]):+.3f}"
              for name, b in zip(FACT_NAMES, bins)]
    return "; ".join(fields if int(style_index) else list(reversed(fields)))
