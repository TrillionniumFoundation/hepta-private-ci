"""Actual isolated browser I/O and retained evidence; no task-benefit claim."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from perc1.browser_capture import configured_browser_capture
from perc1.schema import Invalid, sha
from perc1.source_capture import retain_source_evidence, verify_source_evidence

BROWSER = os.environ.get("PERC_TEST_CHROMIUM", "/usr/lib/chromium/chromium")
ACTUAL = Path(BROWSER).is_file() and importlib.util.find_spec("playwright")


@unittest.skipUnless(ACTUAL, "explicit installed Chromium and Playwright required")
class BrowserCaptureTests(unittest.TestCase):
    def test_actual_capture_preserves_dom_and_denies_outside_origin(self):
        visits = []
        exact_text = "amount=0019.90 USD; date=2026-11-12; dose=10 mg; 原文"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                visits.append(self.path)
                body = (
                    '<!doctype html><meta charset="utf-8"><body><main>'
                    + exact_text
                    + '<img src="http://127.0.0.1:1/denied.png"></main></body>'
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        with Path(BROWSER).open("rb") as stream:
            binary_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        config = {
            "schema": "perc1.browser-capture.v1",
            "url": origin + "/document",
            "allowed_origins": [origin],
            "selector": "main",
            "viewport": {"width": 800, "height": 600},
            "timeout_ms": 10000,
            "executable": BROWSER,
            "executable_sha256": binary_sha,
            "source_group": "controlled-local-browser-fixture",
            "ocr": None,
        }
        result = configured_browser_capture(config, {"source_id": "page"})
        self.assertEqual(result["exact_text"]["bytes"].decode(), exact_text)
        self.assertIn("/document", visits)
        artifacts = result["source_evidence"]["artifacts"]
        browser = json.loads(artifacts["browser_receipt"])
        self.assertGreaterEqual(browser["request_counts"]["blocked"], 1)
        self.assertFalse(browser["javascript_enabled"])
        self.assertIn(exact_text.encode(), artifacts["raw_dom"])
        with tempfile.TemporaryDirectory() as folder:
            metadata = retain_source_evidence(
                folder,
                sha(b"operation"),
                result["source_evidence"],
                sha(result["image_bytes"]),
                "page",
            )
            restored = verify_source_evidence(metadata, folder)
            self.assertEqual(restored, artifacts)
            dom_path = Path(folder) / metadata["artifacts"]["raw_dom"]["relative_path"]
            dom_path.write_bytes(b"changed")
            with self.assertRaisesRegex(Invalid, "digest mismatch"):
                verify_source_evidence(metadata, folder)

    def test_binary_pin_refuses_before_any_navigation(self):
        config = {
            "schema": "perc1.browser-capture.v1",
            "url": "https://example.invalid/",
            "allowed_origins": ["https://example.invalid"],
            "selector": "body",
            "viewport": {"width": 800, "height": 600},
            "timeout_ms": 1000,
            "executable": BROWSER,
            "executable_sha256": "1" * 64,
            "source_group": "controlled-refusal",
            "ocr": None,
        }
        with self.assertRaisesRegex(Invalid, "executable changed"):
            configured_browser_capture(config, {"source_id": "page"})


if __name__ == "__main__":
    unittest.main()
