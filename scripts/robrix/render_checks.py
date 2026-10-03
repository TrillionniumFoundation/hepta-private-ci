"""Pixel regressions for opaque, legible login surfaces and centered actual text."""

from statistics import median


def luminance(rgb):
    linear = [
        c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4
        for c in rgb
    ]
    return sum(c * w for c, w in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def login_pixels(image):
    image = image.convert("RGB")
    width, height = image.size
    # Fixture login uses the default Prism palette. Require the actual opaque
    # surface, not transparency exposing a dark HTML canvas underneath.
    expected = (23, 19, 41)
    background = tuple(
        median(image.getpixel((x, height - 10))[c] for x in range(width // 2, width))
        for c in range(3)
    )
    assert max(abs(a - b) for a, b in zip(background, expected)) <= 3, (
        f"Non-opaque/unexpected login footer: {background}"
    )
    footer = [
        image.getpixel((x, y))
        for x in range(7, 89)
        for y in range(height - 22, height - 7)
    ]
    readable = [pixel for pixel in footer if contrast(pixel, background) >= 4.5]
    assert len(readable) >= 20, "No readable Console footer glyphs"
    ink = sorted(readable, key=luminance)[len(readable) // 2]
    footer_contrast = contrast(ink, background)
    # Locate the three actual input surfaces by their paint role. This retains
    # the baseline centering gate without treating a light background as correct.
    left = width // 2 - 137
    rows = []
    for y in range(140, min(390, height - 45)):
        samples = [image.getpixel((x, y)) for x in range(left + 175, left + 230)]
        if (
            sum(
                max(abs(a - b) for a, b in zip(pixel, expected)) <= 3
                for pixel in samples
            )
            >= 50
        ):
            rows.append(y)
    groups = []
    for y in rows:
        if not groups or y > groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(y)
    groups = [group for group in groups if len(group) >= 15]
    assert len(groups) == 3, f"Expected three real login input surfaces: {groups}"
    offsets = []
    for group in groups:
        top, bottom = group[0], group[-1]
        glyph_rows = []
        for y in range(top + 3, bottom - 2):
            if any(
                contrast(image.getpixel((x, y)), expected) >= 4.5
                for x in range(left + 10, left + 150)
            ):
                glyph_rows.append(y)
        assert glyph_rows, "No readable placeholder glyphs"
        offset = (min(glyph_rows) + max(glyph_rows) - top - bottom) / 2
        offsets.append(offset)
        assert abs(offset) <= 3, f"Placeholder is not vertically centered: {offset}"
    return {
        "footerContrast": footer_contrast,
        "footerRgb": background,
        "inputCenterOffsets": offsets,
    }
