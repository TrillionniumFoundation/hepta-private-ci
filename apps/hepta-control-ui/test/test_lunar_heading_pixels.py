"""Behavioral unit coverage for the unnormalized Lunar screenshot regression."""
import importlib.util
from pathlib import Path
import unittest
from PIL import Image, ImageDraw

PATH = Path(__file__).parents[1] / 'tools/verify-lunar-heading-pixels.py'
spec = importlib.util.spec_from_file_location('lunar_pixels', PATH)
pixels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pixels)


class RawHeadingTests(unittest.TestCase):
    def image(self, ink, scale=1):
        image = Image.new('RGB', (640 * scale, 800 * scale), '#f9f8f4')
        draw = ImageDraw.Draw(image)
        # Simulates solid glyph stems without depending on an installed font.
        for x in range(35, 175, 10):
            draw.rectangle((x * scale, 60 * scale, (x + 2) * scale, 74 * scale), fill=ink)
        return image

    def test_faint_template_text_cannot_pass_on_pale_surface(self):
        result = pixels.inspect_region(self.image('#eeeeff'), pixels.regions(640)['heading'], 1)
        self.assertFalse(result['passed'])
        self.assertEqual(result['inkPixels'], 0)

    def test_actual_dark_text_passes_at_both_device_scales(self):
        for scale in (1, 2):
            result = pixels.inspect_region(self.image('#18232c', scale), pixels.regions(640)['heading'], scale)
            self.assertTrue(result['passed'])

    def test_blank_surface_and_dark_background_fail(self):
        for color in ('#f9f8f4', '#18232c'):
            image = Image.new('RGB', (640, 800), color)
            self.assertFalse(pixels.inspect_region(image, pixels.regions(640)['heading'], 1)['passed'])

    def test_unobserved_viewport_and_outside_region_fail(self):
        with self.assertRaises(ValueError):
            pixels.regions(360)
        with self.assertRaises(AssertionError):
            pixels.inspect_region(self.image('#18232c'), (-1, 0, 50, 20), 1)


if __name__ == '__main__':
    unittest.main()
