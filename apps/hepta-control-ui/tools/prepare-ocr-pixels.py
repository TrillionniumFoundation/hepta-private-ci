"""Fixed QA preprocessing of real PNG pixels; never generates or replaces text."""

import sys
from pathlib import Path

from PIL import Image, ImageOps

raw = sys.argv[-1] == "--raw"
navigation_binary = sys.argv[-1] == "--navigation-binary"
arguments = sys.argv[:-1] if raw or navigation_binary else sys.argv
source, destination = map(Path, arguments[1:3])
with Image.open(source) as image:
    if image.format != "PNG" or image.width * image.height > 8_000_000:
        raise ValueError("Expected a bounded actual host PNG")
    if len(arguments) == 7:
        left, top, width, height = map(int, arguments[3:])
        if not (
            0 <= left < image.width
            and 0 <= top < image.height
            and 0 < width <= image.width - left
            and 0 < height <= image.height - top
        ):
            raise ValueError("Observed OCR region must be fully inside the real PNG")
        image = image.crop((left, top, left + width, top + height))
    elif len(arguments) != 3:
        raise ValueError("Expected one image and optionally one observed region")
    if raw:
        image.save(destination, format="PNG")
    elif navigation_binary:
        # A single fixed additional observation for light navigation glyphs.
        # No adaptive thresholds, OCR confidence selection, or generated text.
        pixels = ImageOps.invert(ImageOps.grayscale(image)).point(
            lambda value: 255 if value > 100 else 0
        )
        pixels.resize(
            (pixels.width * 3, pixels.height * 3), Image.Resampling.NEAREST
        ).save(destination, format="PNG")
    else:
        pixels = ImageOps.autocontrast(ImageOps.invert(ImageOps.grayscale(image)))
        pixels.resize(
            (pixels.width * 3, pixels.height * 3), Image.Resampling.BICUBIC
        ).save(destination, format="PNG")
