"""Fixed QA preprocessing of real PNG pixels; never generates or replaces text."""

import sys
from pathlib import Path

from PIL import Image, ImageOps

source, destination = map(Path, sys.argv[1:])
with Image.open(source) as image:
    if image.format != "PNG" or image.width * image.height > 8_000_000:
        raise ValueError("Expected a bounded actual host PNG")
    pixels = ImageOps.autocontrast(ImageOps.invert(ImageOps.grayscale(image)))
    pixels.resize(
        (pixels.width * 3, pixels.height * 3), Image.Resampling.BICUBIC
    ).save(destination, format="PNG")
