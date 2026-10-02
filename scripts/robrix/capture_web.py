#!/usr/bin/env python3
"""Run only the actual packaged Makepad canvas in disposable browser contexts."""
import functools
import http.server
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright
from qualify import APP, OUT, digest


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()


def main():
    package = APP / 'target/makepad-wasm-app/release/robrix'
    assert (package / 'index.html').is_file(), 'Actual Makepad package missing'
    OUT.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(package)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    records = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            try:
                for scene in ('login', 'console'):
                    for label, width, height in [('wide', 1180, 760), ('narrow', 520, 760), ('short', 800, 560)]:
                        context = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
                        failures, messages, wasm = [], [], []
                        def route(request_route):
                            url = request_route.request.url
                            if url.startswith(origin + '/') or url.startswith(('data:', 'blob:')):
                                request_route.continue_()
                            else:
                                failures.append('Forbidden external request: ' + urlsplit(url).netloc)
                                request_route.abort()
                        context.route('**/*', route)
                        page = context.new_page()
                        page.on('pageerror', lambda error: failures.append(str(error)))
                        page.on('console', lambda message: messages.append(f'{message.type}: {message.text}'))
                        page.on('response', lambda response: wasm.append(response.url) if response.url.endswith('.wasm') and response.ok else None)
                        page.on('requestfailed', lambda request: failures.append('Request failed: ' + request.url))
                        page.goto(origin + '/?hepta-ui-fixture=' + scene, wait_until='networkidle')
                        page.locator('canvas').first.wait_for(state='visible', timeout=60000)
                        page.locator('.canvas_loader').wait_for(state='hidden', timeout=60000)
                        page.wait_for_timeout(5000)
                        assert wasm, 'No actual WASM module fetched'
                        assert page.locator('canvas').first.evaluate('(c) => c.width > 0 && c.height > 0')
                        png = OUT / f'web-{scene}-{label}.png'
                        page.screenshot(path=str(png))
                        with Image.open(png) as image:
                            assert image.size == (width, height)
                            assert len(image.convert('RGB').getcolors(width * height)) > 32, 'Blank canvas screenshot'
                        log = '\n'.join(messages)
                        (OUT / f'web-{scene}-{label}.log').write_text(log)
                        assert not failures, failures
                        assert not any(message.startswith('error:') for message in messages), log
                        records.append({'scene': scene, 'viewport': [width, height], 'png': png.name,
                                        'sha256': digest(png), 'wasmFetched': True, 'fixture': True,
                                        'visualReview': 'pending human or image inspection; pixels alone are not layout acceptance'})
                        context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (OUT / 'web-capture-passed.json').write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    main()
