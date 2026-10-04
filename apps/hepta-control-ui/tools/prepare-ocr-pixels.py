"""Fixed QA preprocessing of real PNG pixels; never generates or replaces text."""

import sys
from pathlib import Path

from PIL import Image, ImageOps

raw = sys.argv[-1] == "--raw"
navigation_neutral = sys.argv[-1] == "--navigation-neutral"
arguments = sys.argv[:-1] if raw or navigation_neutral else sys.argv
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
    elif navigation_neutral:
        # One fixed per-pixel projection suppresses chromatic decoration around
        # neutral text. No expected word, glyph mask, target or OCR confidence.
        rgb = image.convert("RGB")
        neutral = Image.new("L", rgb.size)
        neutral.putdata([max(0, 2 * min(pixel) - max(pixel)) for pixel in rgb.getdata()])
        pixels = ImageOps.autocontrast(ImageOps.invert(neutral))
        pixels.resize(
            (pixels.width * 3, pixels.height * 3), Image.Resampling.BICUBIC
        ).save(destination, format="PNG")
    else:
        pixels = ImageOps.autocontrast(ImageOps.invert(ImageOps.grayscale(image)))
        pixels.resize(
            (pixels.width * 3, pixels.height * 3), Image.Resampling.BICUBIC
        ).save(destination, format="PNG")
