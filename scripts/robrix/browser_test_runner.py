#!/usr/bin/env python3
"""Drive the official wasm-bindgen interactive test page and retain bootstrap errors.

The official server generates and executes the unchanged application's tests. This
wrapper replaces only its WebDriver observation layer, which omits page errors
when an ES module fails before the first test. No import or test-code shims.
"""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from qualify import OUT


def passing_summary(output):
    return re.search(r'test result: ok\. [1-9]\d* passed; 0 failed; 0 ignored;', output) is not None


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, NO_HEADLESS='1', WASM_BINDGEN_KEEP_TEST_BUILD='1',
               WASM_BINDGEN_TEST_ADDRESS='127.0.0.1:0')
    process = subprocess.Popen(['wasm-bindgen-test-runner', *sys.argv[1:]], env=env,
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = queue.Queue()
    def drain():
        with (OUT / 'browser-test-server.log').open('w') as log:
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
                lines.put(line)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    receipt = {'schema': 1, 'fixture': True, 'liveAccounts': False,
               'runner': 'official wasm-bindgen 0.2.129 interactive server',
               'pageErrors': [], 'console': [], 'requestFailures': [], 'responses': [],
               'passed': False, 'output': ''}
    try:
        # This is server/bootstrap setup, not a longer allowance for test execution.
        deadline = time.monotonic() + 60
        origin = None
        while time.monotonic() < deadline and origin is None:
            if process.poll() is not None:
                raise RuntimeError(f'Test server exited before startup: {process.returncode}')
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                continue
            match = re.search(r'available at (http://127\.0\.0\.1:\d+)', line)
            if match:
                origin = match.group(1)
        if origin is None:
            raise RuntimeError('Official test server did not announce a loopback address')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context()
                def route(request_route):
                    url = request_route.request.url
                    if url.startswith(origin + '/') or url.startswith(('blob:', 'data:')):
                        request_route.continue_()
                    else:
                        receipt['requestFailures'].append('External request blocked: ' + urlsplit(url).netloc)
                        request_route.abort()
                context.route('**/*', route)
                page = context.new_page()
                page.on('pageerror', lambda error: receipt['pageErrors'].append(str(error)))
                page.on('console', lambda message: receipt['console'].append(f'{message.type}: {message.text}'[:8192]))
                page.on('requestfailed', lambda request: receipt['requestFailures'].append(request.url))
                page.on('response', lambda response: receipt['responses'].append({'url': response.url, 'status': response.status}))
                # Preserve the existing 120-second test deadline. Fail sooner on
                # loader exceptions rather than reporting them as a vague timeout.
                deadline = time.monotonic() + 120
                page.goto(origin, wait_until='domcontentloaded', timeout=30000)
                while time.monotonic() < deadline:
                    receipt['output'] = page.locator('#output').inner_text()
                    if receipt['pageErrors'] or receipt['requestFailures']:
                        raise RuntimeError('Browser test bootstrap failed; see browser-test-bootstrap.json')
                    if 'test result:' in receipt['output']:
                        print(receipt['output'], flush=True)
                        if not passing_summary(receipt['output']):
                            raise RuntimeError('Actual browser tests failed, were ignored, or did not execute')
                        receipt['passed'] = True
                        break
                    if process.poll() is not None:
                        raise RuntimeError('Official test server exited during browser tests')
                    page.wait_for_timeout(100)
                if not receipt['passed']:
                    raise RuntimeError('Actual browser tests did not complete within the existing 120 seconds')
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reader.join(timeout=10)
        process.stdout.close()
        receipt['serverExitAfterCleanup'] = process.returncode
        (OUT / 'browser-test-bootstrap.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
