"""Independent decoded-byte checks for the explicit colour-card task.

No training labels, model states or teacher-forced losses enter this evaluator.
Its narrow vocabulary and pixel criterion do not assess general semantics.
"""

import hashlib
import io

import numpy as np
from PIL import Image


COLOURS = ("red", "green", "blue")
PROMPT = "Name the colour and reproduce the image."
SEMANTIC_PROFILE = "colour-card-caption-reconstruction-v1"
MAX_IMAGE_MSE = 0.025
MIN_COLOUR_MARGIN = 0.35


def _pixels(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 1_048_576:
        raise ValueError("Bounded image bytes required")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in {"PNG", "PPM"} or image.size != (16, 16):
            raise ValueError("Expected a 16x16 colour-card image")
        return np.asarray(image.convert("RGB"), dtype=np.float64).copy() / 255


def expected_caption(source):
    """Derive the task label from observed pixels independently of data seed."""
    means = _pixels(source).mean(axis=(0, 1))
    order = np.argsort(means)
    if means[order[-1]] - means[order[-2]] < MIN_COLOUR_MARGIN:
        raise ValueError("Source is outside the registered colour-card domain")
    return f"This image is {COLOURS[int(order[-1])]}."


def assess(source, text, generated):
    """Require meaningful text and reconstructed image correctness separately."""
    expected = expected_caption(source)
    text_valid = type(text) is str and len(text) == 128
    text_correct = text_valid and text.strip() == expected
    image_mse, image_correct, output_colour = None, False, None
    try:
        pixels = _pixels(generated)
        image_mse = float(np.square(pixels - _pixels(source)).mean())
        means = pixels.mean(axis=(0, 1))
        order = np.argsort(means)
        output_colour = COLOURS[int(order[-1])]
        image_correct = bool(
            expected == f"This image is {output_colour}."
            and means[order[-1]] - means[order[-2]] >= MIN_COLOUR_MARGIN
            and image_mse <= MAX_IMAGE_MSE
        )
    except (ValueError, OSError):
        pass
    return {
        "profile": SEMANTIC_PROFILE,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "expected_caption": expected,
        "text_valid": text_valid,
        "text_correct": text_correct,
        "image_mse": image_mse,
        "output_colour": output_colour,
        "image_correct": image_correct,
        "both_correct": bool(text_correct and image_correct),
    }
