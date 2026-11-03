"""Frozen, separately trained handwritten-image observer and raw-output scoring.

The recognizer is an imperfect domain-specific observer, not a human or an
authenticated production outcome owner. It never enters the inference backend.
Caption truth and original target pixels remain on this side of the boundary.
"""

import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.nn import functional as F


METRIC = {
    "schema": "hepta.ndu-v6.joint-observation.v1",
    "weights": {"text_fact": .30, "relation": .15, "image_fact": .35,
                "crossmodal_disagreement": .10, "pixel_mse": .10},
    "utility": "1 - 2 * joint_loss",
    "image_observer": "separate_source_pool_frozen_mnist_classifier",
    "raw_modalities": ["text/utf-8", "image/png;grayscale;56x28"],
    "unsupported": ["natural_language_generalization", "audio", "video",
                    "human_verified_semantics", "authenticated_outcome_owner"],
}
METRIC_DIGEST = hashlib.sha256(json.dumps(
    METRIC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
CAPTION = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")


class Recognizer(nn.Module):
    """A small independent image classifier; shares no generator parameters."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Flatten(), nn.Linear(32 * 7 * 7, 64), nn.ReLU(), nn.Linear(64, 10),
        )

    def forward(self, pixels):
        return self.net(pixels)


def fit_observer(source, steps=240, seed=314159):
    """Use only the reserved evaluator pool; retain a separate calibration tail."""
    if len(source) < 100:
        raise ValueError("Independent observer pool is too small")
    torch.manual_seed(seed)
    model = Recognizer()
    optimizer = torch.optim.Adam(model.parameters(), lr=.002)
    boundary = len(source) * 4 // 5
    pixels = source.images.float() / 255
    rng = torch.Generator().manual_seed(seed)
    started = time.perf_counter_ns()
    for _ in range(steps):
        ids = torch.randint(boundary, (min(128, boundary),), generator=rng)
        optimizer.zero_grad(set_to_none=True)
        F.cross_entropy(model(pixels[ids]), source.labels[ids]).backward()
        optimizer.step()
    model.eval().requires_grad_(False)
    with torch.inference_mode():
        predicted = torch.cat([model(block).argmax(1)
                               for block in pixels[boundary:].split(256)])
        accuracy = (predicted == source.labels[boundary:]).float().mean().item()
    return model, {
        "seed": seed, "steps": steps, "wall_ns": time.perf_counter_ns() - started,
        "train_sources": boundary, "calibration_sources": len(source) - boundary,
        "calibration_accuracy": accuracy,
        "source_ids_sha256": hashlib.sha256("\n".join(source.ids).encode()).hexdigest(),
        "independence": "disjoint source pool and parameters; same local host",
    }


def observe_tensors(model, pixels, captions, target_pixels, labels):
    """Score decoded pixels/strings; callable for offline critic labels only."""
    if pixels.shape != target_pixels.shape or pixels.shape[1:] != (1, 28, 56):
        raise ValueError("Joint image dimensions do not match the contract")
    if len(captions) != len(pixels) or labels.shape != (len(pixels), 2):
        raise ValueError("Joint caption/label cardinality mismatch")
    if not torch.isfinite(pixels).all() or pixels.min() < 0 or pixels.max() > 1:
        raise ValueError("Decoded image values outside [0,1]")
    with torch.inference_mode():
        left = model(pixels[:, :, :, :28]).argmax(1)
        right = model(pixels[:, :, :, 28:]).argmax(1)
        image_labels = torch.stack((left, right), dim=1)
        mse = (pixels - target_pixels).square().flatten(1).mean(1)
    result = []
    for index, caption in enumerate(captions):
        match = CAPTION.fullmatch(caption.strip())
        expected = labels[index].tolist()
        expected_relation = ("less" if expected[0] < expected[1] else
                             "greater" if expected[0] > expected[1] else "equal")
        image_digits = image_labels[index].tolist()
        parsed = [int(match[1]), int(match[2])] if match else None
        text_error = sum(a != b for a, b in zip(parsed, expected)) / 2 if match else 1.
        relation_error = float(match[3] != expected_relation) if match else 1.
        disagreement = sum(a != b for a, b in zip(parsed, image_digits)) / 2 if match else 1.
        fields = {
            "text_fact": text_error, "relation": relation_error,
            "image_fact": sum(a != b for a, b in zip(image_digits, expected)) / 2,
            "crossmodal_disagreement": disagreement, "pixel_mse": float(mse[index]),
        }
        joint = sum(METRIC["weights"][key] * value for key, value in fields.items())
        result.append({**fields, "joint_loss": joint, "utility": 1 - 2 * joint,
                       "caption_valid": match is not None,
                       "image_digits": image_digits, "caption_digits": parsed,
                       "caption_relation": match[3] if match else None})
    return result


def write_bundle(directory, caption, pixels):
    """Write the neural decoder's original output; do not repair its content."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    image_path, text_path = directory / "image.png", directory / "caption.txt"
    array = (pixels.detach().cpu().squeeze().numpy() * 255).round()
    if array.shape != (28, 56) or not np.isfinite(array).all():
        raise ValueError("Invalid neural decoder image")
    if array.min() < 0 or array.max() > 255:
        raise ValueError("Unbounded neural decoder image")
    Image.fromarray(array.astype(np.uint8)).save(image_path, format="PNG")
    text_path.write_text(caption, encoding="utf-8")
    return {"image": str(image_path), "text": str(text_path)}


def read_bundle(paths):
    """Reopen actual UTF-8 and PNG bytes, rather than trusting declared scores."""
    hashes = {}
    for kind in ("image", "text"):
        path = Path(paths[kind])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("Invalid or oversized raw output")
        hashes[kind] = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = Path(paths["image"]).read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Image is not PNG")
    with Image.open(paths["image"]) as image:
        if image.format != "PNG" or image.mode != "L" or image.size != (56, 28):
            raise ValueError("PNG profile mismatch")
        pixels = torch.from_numpy(np.array(image, copy=True)).float()[None, None] / 255
    caption = Path(paths["text"]).read_text(encoding="utf-8")
    if len(caption) > 4096:
        raise ValueError("Caption exceeds output bound")
    return pixels, caption, hashes


def upper_tail(values, fraction=.1):
    """Exact fractional empirical upper-tail mean, including boundary mass."""
    if not values or not 0 < fraction <= 1 or not np.isfinite(values).all():
        raise ValueError("Invalid empirical tail sample")
    ordered = sorted(map(float, values), reverse=True)
    mass = len(ordered) * fraction
    whole = int(mass)
    partial = mass - whole
    total = sum(ordered[:whole])
    if partial:
        total += partial * ordered[whole]
    return total / mass
