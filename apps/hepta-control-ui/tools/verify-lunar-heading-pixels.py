"""Source-bound raw-pixel regression for the default Lunar responsive heading.

This is a narrow renderer regression, not screen-reader or WCAG acceptance.
Coordinates bind the existing 640/1280 default smoke layout and exclude emoji.
No brightness normalization, retries, or screenshot replacement is performed.
"""
from pathlib import Path
import argparse
import hashlib
import json
from PIL import Image


def regions(width):
    if width == 640:
        return {'heading': (30, 54, 210, 84), 'brand': (50, 10, 132, 35)}
    if width == 1280:
        return {'heading': (374, 86, 620, 126), 'brand': (96, 16, 222, 55)}
    raise ValueError('Only exact default 640/1280 viewport evidence is supported')


def inspect_region(image, bounds, scale):
    box = tuple(round(value * scale) for value in bounds)
    assert 0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height
    pixels = list(image.crop(box).convert('RGB').getdata())
    # Final Lunar foreground token is #18232c. Anti-aliased edge pixels are
    # excluded: solid interior ink must actually be present on the raw surface.
    ink = sum(all(abs(value - want) <= 8 for value, want in zip(pixel, (24, 35, 44))) for pixel in pixels)
    light_surface = sum(min(pixel) >= 220 for pixel in pixels)
    return {'inkPixels': ink, 'lightSurfacePixels': light_surface,
            'requiredInkPixels': round(20 * scale * scale),
            'passed': ink >= round(20 * scale * scale) and light_surface >= len(pixels) // 2}


def verify(root, source_sha):
    records = []
    for path in sorted(root.glob('*/pixel-plan.json')):
        plan = json.loads(path.read_text())
        assert plan['sourceSha'] == source_sha and plan['fixtures'] is False
        capture = next(item for item in plan['captures'] if item['name'] == 'robrix-Lunar-after-resize')
        assert capture['theme'] == 'Lunar'
        png = path.with_name(capture['name'] + '.png')
        assert hashlib.sha256(png.read_bytes()).hexdigest() == capture['pngSha256']
        image = Image.open(png)
        width = capture['viewport']['width']
        scale = image.width / width
        assert image.height == round(800 * scale) and capture['viewport']['height'] == 800
        checks = {name: inspect_region(image, bounds, scale) for name, bounds in regions(width).items()}
        records.append({'browser': plan['browser'], 'initialWidth': plan['initialWidth'],
                        'viewport': capture['viewport'], 'pngSha256': capture['pngSha256'], 'checks': checks,
                        'passed': all(check['passed'] for check in checks.values())})
    subjects = {(row['browser'], row['initialWidth']) for row in records}
    expected = {(browser, width) for browser in ('chromium', 'firefox', 'webkit') for width in (640, 1280)}
    return {'sourceSha': source_sha, 'scope': 'Raw default Lunar heading/brand ink after responsive resize only',
            'records': records, 'passed': len(records) == 6 and subjects == expected and all(row['passed'] for row in records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('source_sha')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root, args.source_sha)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
