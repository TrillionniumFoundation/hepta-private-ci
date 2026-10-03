"""Fixed QA preprocessing of real PNG pixels; never generates or replaces text."""

import sys
from pathlib import Path

from PIL import Image, ImageOps

source, destination = map(Path, sys.argv[1:3])
with Image.open(source) as image:
    if image.format != "PNG" or image.width * image.height > 8_000_000:
        raise ValueError("Expected a bounded actual host PNG")
    if len(sys.argv) == 7:
        left, top, width, height = map(int, sys.argv[3:])
        if not (
            0 <= left < image.width
            and 0 <= top < image.height
            and 0 < width <= image.width - left
            and 0 < height <= image.height - top
        ):
            raise ValueError("Observed OCR region must be fully inside the real PNG")
        image = image.crop((left, top, left + width, top + height))
    elif len(sys.argv) != 3:
        raise ValueError("Expected one image and optionally one observed region")
    pixels = ImageOps.autocontrast(ImageOps.invert(ImageOps.grayscale(image)))
    pixels.resize((pixels.width * 3, pixels.height * 3), Image.Resampling.BICUBIC).save(
        destination, format="PNG"
    )
