"""Local fake-worker/loopback qualifications only: these tests do not run an LLM."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from .transport import call, canonical, digest, reconcile

IDENTITY = {"kind": "offline_fixture", "model_id": "fixture", "revision": "test-v1"}
CONTEXT = {"task_id": "t", "arm": "direct_stop", "repeat": 0, "protocol_sha256": "a"*64}


def provider(code):
    return {"kind": "local", "argv": [sys.executable, "-c", code], "identity": IDENTITY}


def reply(text="answer"):
    return {"model_id": "fixture", "revision": "test-v1", "text": text,
            "usage": {"input_tokens": 3, "output_tokens": 2}, "provider_request_id": "request-1"}


def invoice(event, amount=0.):
    return {"request_id": event["request_id"], "status": "final", "amount": amount, "currency": "USD",
            "invoice_sha256": "b"*64, "line_id": event["request_id"], "usage": event["usage"],
            "identity_sha256": event["expected_identity_sha256"], "identity_evidence_sha256": "c"*64,
            "provider_request_sha256": event["provider_request_sha256"]}


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = str(Path(self.tmp.name)/"ledger.jsonl")

    def test_private_payload_and_estimated_price_never_become_actual_bill(self):
        response = {**reply("never-log-this-answer"), "amount": .01, "currency": "USD"}
        event, text = call(provider("print("+repr(json.dumps(response))+")"),
                           {"private": "never-log-this-input"}, CONTEXT, self.ledger, 2)
        content = Path(self.ledger).read_text()
        self.assertNotIn("never-log-this", content)
        self.assertEqual(text, "never-log-this-answer")
        self.assertIsNone(event["actual_amount"])
        costs, errors = reconcile([event], [], "USD")
        self.assertIsNone(costs[event["request_id"]])
        self.assertTrue(errors)
        costs, errors = reconcile([event], [invoice(event, .04)], "USD")
        self.assertFalse(errors)
        self.assertEqual(costs[event["request_id"]], .04)

    def test_timeout_keeps_attempt_and_cleans_child_group(self):
        marker = str(Path(self.tmp.name)/"escaped.txt")
        child = "import time,pathlib;time.sleep(.3);pathlib.Path("+repr(marker)+").write_text('bad')"
        code = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"+repr(child)+"]);time.sleep(2)"
        event, text = call(provider(code), {}, CONTEXT, self.ledger, .12)
        self.assertEqual(event["status"], "timeout")
        self.assertIsNone(text)
        self.assertEqual(len(Path(self.ledger).read_text().splitlines()), 2)
        self.assertIsNone(event["usage"])
        time.sleep(.35)
        self.assertFalse(Path(marker).exists())
        bill = invoice(event, .02)
        bill["usage"] = {"input_tokens": 5, "output_tokens": 1}
        costs, errors = reconcile([event], [bill], "USD")
        self.assertFalse(errors)
        self.assertEqual(costs[event["request_id"]], .02)

    def test_nonfinite_and_invalid_utf8_are_receipted_failures(self):
        for code in ("print('{\"x\":[1e999]}')", "import sys;sys.stdout.buffer.write(b'\\xff')"):
            event, text = call(provider(code), {}, CONTEXT, self.ledger, 2)
            self.assertEqual(event["status"], "failure")
            self.assertIsNone(text)
        for payload in ({"nested": float("inf")}, {"object": object()}):
            event, text = call(provider("raise RuntimeError"), payload, CONTEXT, self.ledger, 2)
            self.assertEqual(event["status"], "failure")
            self.assertFalse(event["dispatched"])
            self.assertIsNone(text)
        self.assertEqual(len(Path(self.ledger).read_text().splitlines()), 8)

    def test_wrong_revision_is_not_fixed_by_matching_invoice(self):
        response = {**reply(), "revision": "changed-v2"}
        event, text = call(provider("print("+repr(json.dumps(response))+")"), {}, CONTEXT, self.ledger, 2)
        self.assertEqual(event["status"], "identity_mismatch")
        self.assertIsNone(text)
        self.assertTrue(reconcile([event], [invoice(event)], "USD")[1])

    def test_usage_missing_and_duplicate_billing_are_not_zero(self):
        response = {**reply(), "usage": None}
        event, _ = call(provider("print("+repr(json.dumps(response))+")"), {}, CONTEXT, self.ledger, 2)
        bill = invoice(event)
        for invalid in (None, {}, {"input_tokens": 2}, {"input_tokens": 2, "output_tokens": True}):
            event["usage"] = invalid
            self.assertTrue(reconcile([event], [bill], "USD")[1])
        event["usage"] = None
        bill["usage"] = {"input_tokens": 2, "output_tokens": 1}
        self.assertFalse(reconcile([event], [bill], "USD")[1])
        self.assertTrue(reconcile([event], [bill, bill], "USD")[1])
        bill["status"] = "estimate"
        self.assertIsNone(reconcile([event], [bill], "USD")[0][event["request_id"]])

    def test_loopback_http_uses_auth_without_logging_credentials(self):
        observed = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                observed.append((self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = canonical(reply("http-fixture")).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            config = {"kind": "http", "identity": IDENTITY, "url_env": "NDU_TEST_URL", "key_env": "NDU_TEST_KEY",
                      "decoding": {"temperature": 0}, "response_map": {k: [k] for k in
                         ("model_id", "revision", "text", "provider_request_id")}}
            config["response_map"].update({k: ["usage", k] for k in ("input_tokens", "output_tokens")})
            with patch.dict(os.environ, {"NDU_TEST_URL": "http://127.0.0.1:"+str(server.server_port),
                                         "NDU_TEST_KEY": "secret-fixture-token"}):
                event, text = call(config, {"question": "hello"}, CONTEXT, self.ledger, 2)
            self.assertEqual(event["status"], "ok")
            self.assertEqual(text, "http-fixture")
            self.assertEqual(observed[0][0], "Bearer secret-fixture-token")
            self.assertEqual(observed[0][1]["revision"], "test-v1")
            self.assertNotIn("secret-fixture-token", Path(self.ledger).read_text())
            self.assertEqual(event["usage"]["output_tokens"], 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
