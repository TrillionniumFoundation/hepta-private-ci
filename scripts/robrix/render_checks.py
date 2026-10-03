"""Narrow pixel regressions for the existing account-free login, not design acceptance."""

from statistics import median


def login_pixels(image):
    image = image.convert("RGB")
    width, height = image.size
    # The footer's right-hand empty surface must be the same opaque light surface
    # as native, rather than the HTML page shining through the transparent pass.
    background = median(
        image.getpixel((x, height - 10))[0] for x in range(width // 2, width)
    )
    ink = min(
        image.getpixel((x, y))[0]
        for x in range(7, 89)
        for y in range(height - 22, height - 7)
    )

    def luminance(channel):
        s = channel / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    contrast = (luminance(background) + 0.05) / (luminance(ink) + 0.05)
    assert background >= 245 and contrast >= 4.5, (
        f"Unreadable Console footer: {background=}, {contrast=}"
    )
    # Locate the actual white input surfaces, independent of platform glyph AA.
    left = width // 2 - 137
    rows = []
    for y in range(175, min(360, height)):
        whites = sum(
            min(image.getpixel((x, y))) >= 245 for x in range(left + 175, left + 230)
        )
        if whites >= 50:
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
            for x in range(left + 10, left + 150):
                pixel = image.getpixel((x, y))
                if (
                    130 <= min(pixel) <= max(pixel) <= 205
                    and max(pixel) - min(pixel) <= 3
                ):
                    glyph_rows.append(y)
                    break
        assert glyph_rows, "No readable placeholder glyphs"
        offset = (min(glyph_rows) + max(glyph_rows) - top - bottom) / 2
        offsets.append(offset)
        assert abs(offset) <= 3, f"Placeholder is not vertically centered: {offset=}"
    return {"footerContrast": contrast, "inputCenterOffsets": offsets}
