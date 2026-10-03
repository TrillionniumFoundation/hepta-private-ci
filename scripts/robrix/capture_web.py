#!/usr/bin/env python3
"""Run only the actual packaged Makepad canvas in disposable browser contexts."""
import functools
import http.server
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright
from qualify import APP, OUT, digest
from package_resources import package_inventory
from render_checks import login_pixels
from web_usability import capture_login_usability
from chat_usability import capture_theme_switches


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()


def main():
    package = APP / 'target/makepad-wasm-app/release/robrix'
    inventory = package_inventory(package)
    resources = json.loads((OUT / 'web-package-resource-identity.json').read_text())
    for relative, expected in resources['verifiedResources'].items():
        assert inventory.get(relative) == expected, f'Packaged resource drift: {relative}'
    OUT.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(package)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    records = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            try:
                for scene in ('login', 'console', 'chat-titanium', 'chat-prism', 'chat-ceramic'):
                    for label, width, height in [('wide', 1180, 760), ('narrow', 520, 760), ('short', 800, 560)]:
                        context = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
                        failures, messages, wasm, responses = [], [], [], []
                        delayed_fonts = []
                        def route(request_route):
                            url = request_route.request.url
                            if urlsplit(url).path == '/$report_error':
                                failures.append('Automatic panic telemetry was attempted')
                                request_route.abort()
                            elif url.startswith(origin + '/') or url.startswith(('data:', 'blob:')):
                                if scene == 'login' and label == 'wide' and url.endswith(('.ttf', '.otf')):
                                    delayed_fonts.append(urlsplit(url).path)
                                    time.sleep(0.15)
                                request_route.continue_()
                            else:
                                failures.append('Forbidden external request: ' + urlsplit(url).netloc)
                                request_route.abort()
                        context.route('**/*', route)
                        page = context.new_page()
                        page.on('pageerror', lambda error: failures.append(getattr(error, 'stack', str(error))))
                        page.on('console', lambda message: messages.append(f'{message.type}: {message.text}'))
                        def response_received(response):
                            responses.append({'url': response.url, 'status': response.status})
                            if not response.ok:
                                failures.append(f'HTTP {response.status}: {response.url}')
                            if response.url.endswith('.wasm') and response.ok:
                                wasm.append(response.url)
                        page.on('response', response_received)
                        page.on('requestfailed', lambda request: failures.append('Request failed: ' + request.url))
                        try:
                            page.goto(origin + '/?hepta-ui-fixture=' + scene, wait_until='networkidle')
                            page.locator('canvas').first.wait_for(state='visible', timeout=60000)
                            deadline = time.monotonic() + 60
                            while page.locator('.canvas_loader').is_visible():
                                assert not failures, failures
                                assert time.monotonic() < deadline, 'Makepad loader did not finish within60s'
                                page.wait_for_timeout(100)
                            page.wait_for_timeout(5000)
                            assert wasm, 'No actual WASM module fetched'
                            assert page.locator('canvas').first.evaluate('(c) => c.width > 0 && c.height > 0')
                            png = OUT / f'web-{scene}-{label}.png'
                            page.screenshot(path=str(png))
                            with Image.open(png) as image:
                                assert image.size == (width, height)
                                assert len(image.convert('RGB').getcolors(width * height)) > 32, 'Blank canvas screenshot'
                                if scene == 'login':
                                    (OUT / f'web-login-{label}-pixels.json').write_text(json.dumps(login_pixels(image), indent=2))
                            log = '\n'.join(messages)
                            (OUT / f'web-{scene}-{label}.log').write_text(log)
                            assert not failures, failures
                            assert not any(message.startswith('error:') for message in messages), log
                            records.append({'scene': scene, 'viewport': [width, height], 'png': png.name,
                                            'sha256': digest(png), 'wasmFetched': True, 'fixture': True,
                                            'visualReview': 'pending human or image inspection; pixels alone are not layout acceptance'})
                            if scene == "login" and label == "wide":
                                assert len(delayed_fonts) >= 7, (
                                    "Delayed-font exercise did not load the actual font resources"
                                )
                                page.mouse.click(width // 2 - 80, 215)
                                page.keyboard.type("pixel-fixture")
                                page.wait_for_timeout(250)
                                typed = OUT / "web-login-wide-typed.png"
                                page.screenshot(path=str(typed))
                                from PIL import ImageChops

                                with (
                                    Image.open(png) as before,
                                    Image.open(typed) as after,
                                ):
                                    diff = ImageChops.difference(
                                        before.convert("RGB"), after.convert("RGB")
                                    )
                                    crop = diff.crop(
                                        (width // 2 - 127, 200, width // 2 + 115, 230)
                                    )
                                    assert (
                                        sum(max(pixel) > 25 for pixel in crop.getdata())
                                        > 120
                                    ), "Typing did not visibly change the actual input"
                                page.keyboard.press("ControlOrMeta+A")
                                page.keyboard.press("Backspace")
                                page.wait_for_timeout(250)
                                cleared = OUT / "web-login-wide-cleared.png"
                                page.screenshot(path=str(cleared))
                                with Image.open(cleared) as image:
                                    pixels = login_pixels(image)
                                (OUT / "web-login-font-input-exercise.json").write_text(
                                    json.dumps(
                                        {
                                            "delayedFontResponses": delayed_fonts,
                                            "submissionKeysSent": False,
                                            "typedSha256": digest(typed),
                                            "clearedSha256": digest(cleared),
                                            "clearedPixels": pixels,
                                        },
                                        indent=2,
                                    )
                                )
                                for font_url in delayed_fonts:
                                    assert (
                                        sum(
                                            urlsplit(response["url"]).path == font_url
                                            for response in responses
                                        )
                                        == 1
                                    ), "Repeated font request during input redraw"
                            if scene == 'chat-prism' and label == 'wide':
                                capture_theme_switches(page, messages, OUT)
                            assert not failures, failures
                            assert not any(
                                message.startswith("error:") for message in messages
                            ), "\n".join(messages)
                        finally:
                            (OUT / f'web-{scene}-{label}.log').write_text('\n'.join(messages))
                            (OUT / f'web-{scene}-{label}-runtime.json').write_text(json.dumps(
                                {'failures': failures, 'responses': responses, 'wasm': wasm}, indent=2))
                        context.close()
                    if scene == 'login':
                        usability = capture_login_usability(browser, origin, OUT)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (OUT / 'web-capture-passed.json').write_text(json.dumps(records, indent=2) + '\n')
    assert usability['passed'], 'Actual short-window usability checks failed; inspect web-login-short-usability.json'


if __name__ == '__main__':
    main()
